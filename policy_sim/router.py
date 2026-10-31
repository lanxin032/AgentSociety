"""Official structured-tool router with one trusted policy session."""
import asyncio
import json
from contextvars import ContextVar
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from uuid import UUID
from jsonschema import validate as validate_schema
from jsonschema.exceptions import ValidationError
from agentsociety2.env import EnvBase, tool
from agentsociety2.env.router_react import ReActRouter
from .core import PolicyWorld
from .interface import RUNTIME_VERSION, canonical, decorate_observation, decode_candidate_choice, decode_material_read
from .materials import MATERIAL_VERSION
from .llm import validate_action
from .io import append_jsonl, digest, read_json, write_json
from .services import PolicyServices
from .work import WorkContext, business_material_result, _size
from .messaging import PolicyMailbox
from .prompt import WORLD_DESCRIPTION

ACTOR_IDS = {1, 2, 3, 4}
_TRUSTED = ContextVar("policy_business_request", default=None)


class PolicyEnv(EnvBase):
    def __init__(self, owner, world):
        super().__init__()
        self.owner, self.world = owner, world

    @classmethod
    def mcp_description(cls):
        return "Read legally delivered materials or queue one available business action."

    @tool(readonly=True, kind="observe")
    async def observe(self) -> dict:
        """Return this actor's current legal overview; repeated reads do not advance time."""
        return await self.owner._execute("observe", {})

    @tool(readonly=True)
    async def read_materials(self, read_materials: list[str], reason: str) -> dict:
        """Read up to four source IDs from the current actor's material catalog."""
        return await self.owner._execute("read_materials", {"read_materials": read_materials, "reason": reason})

    @tool(readonly=True)
    async def read_work(self, section: str, offset: int = 0) -> dict:
        """Read legal work records: candidate_options, visible_tickets, projects, topics, inbox, sent_messages, public_rules, source_catalog, analyses, last_receipt or resources. Follow returned read_work references for project tasks and records. Use next_offset to continue. No workspace paths."""
        return await self.owner._execute("read_work", {"section": section, "offset": offset})

    @tool(readonly=False)
    async def submit(self, candidate_id: str, reason: str, analysis: dict | None = None) -> dict:
        """Queue exactly one candidate from the legal observation. Wait is a valid candidate. Only propose_project requires analysis. A queued receipt is not execution success."""
        payload = {"candidate_id": candidate_id, "reason": reason}
        if analysis is not None:
            payload["analysis"] = analysis
        return await self.owner._execute("submit", payload)

    async def init(self, start_datetime):
        self.t = start_datetime
        await self.owner.mailbox.init(start_datetime)

    async def step(self, tick, t):
        owner = self.owner
        owner._healthy()
        if ACTOR_IDS - owner.completed - owner.unfiled:
            raise RuntimeError("Every actor must persist successfully before settlement")
        before, before_time = self.world.export_state(), self.t
        try:
            self.world.advance()
            self.t = t + timedelta(seconds=tick)
            await owner.mailbox.deliver(self.world, self.t)
            rows = []
            for actor in sorted(ACTOR_IDS):
                settled = self.world._latest_receipt(actor)
                if settled is None or settled["round"] != before["round"]:
                    raise RuntimeError("Missing authoritative settlement")
                row = {"actor_id": actor, "submission_id": owner.receipts[actor]["submission_id"]
                       if actor in owner.receipts else None, **settled}
                append_jsonl(owner.run_dir / "native_settlements.jsonl", row)
                rows.append(row)
            snapshot = self.world.export_state()
            append_jsonl(owner.run_dir / "rounds.jsonl", {"round": self.world.round,
                "state_sha256": digest(snapshot), "metrics": self.world.metrics()})
            owner.settlements.extend(rows)
            owner.last_snapshot = snapshot
            owner.completed.clear(); owner.unfiled.clear(); owner.receipts.clear(); owner.observed.clear()
            owner._saved_round = None
        except Exception as exc:
            owner.world = PolicyWorld.from_state(before)
            self.t = before_time
            owner.fatal_error = exc
            raise

    async def to_workspace(self, workspace_path=None):
        if workspace_path is not None:
            self._bind_workspace(Path(workspace_path))
        write_json(self._workspace_root / "state/ENV_STATE.json", self.world.export_state())
        await self.owner.mailbox.to_workspace(self._workspace_root / "mailbox")

    async def restore(self, workspace_path):
        self._bind_workspace(Path(workspace_path))
        path = self._workspace_root / "state/ENV_STATE.json"
        if not path.exists():
            return False
        self.owner.world = PolicyWorld.from_state(read_json(path), workload_mode=self.world.workload_mode)
        self.owner.mailbox = PolicyMailbox(self.world)
        if not await self.owner.mailbox.restore(self._workspace_root / "mailbox"):
            raise RuntimeError("Missing official mailbox checkpoint")
        self.t = self.owner.mailbox.t
        return True

    async def close(self):
        await self.owner.mailbox.native.close()


class PolicyRouter(PolicyServices, ReActRouter):
    def __init__(self, run_dir, policy, seed, horizon, decision_mode, llm_client,
                 config=None, scenario=None, workload_mode=None):
        world = PolicyWorld(policy=policy, seed=seed, horizon=horizon, config=config,
            scenario=scenario, workload_mode=workload_mode or (scenario or {}).get("workload_mode", "finite"))
        self.env = PolicyEnv(self, world)
        self.mailbox = PolicyMailbox(world)
        super().__init__([self.env], max_steps=10, max_llm_call_retry=1)
        self.run_dir = Path(run_dir)
        self.env_path = self.run_dir / "env/PolicyEnv"
        self.env._bind_workspace(self.env_path)
        self.decision_mode, self.llm_client = decision_mode, llm_client
        self.completed, self.observed = set(), {}
        self.unfiled = set()
        self.receipts, self.advice_cache, self.settlements = {}, {}, []
        self.fatal_error = None
        self.last_snapshot = None
        self._saved_round = None
        self._ask_lock = asyncio.Lock()
        routes = self.run_dir / "native_routes.jsonl"
        self._route_ordinal = len(routes.read_text().splitlines()) if routes.exists() else 0

    @property
    def world(self):
        return self.env.world

    @world.setter
    def world(self, value):
        self.env.world = value

    @property
    def submitted(self):
        return {int(actor) for actor in self.world.pending}

    def _identity(self):
        path = self.run_dir / "run_config.json"
        if path.exists():
            return read_json(path)["record"]["run_id"]
        if self.decision_mode == "llm":
            raise RuntimeError("Model services require a frozen run identity")
        return "offline:" + str(self.world.seed) + ":" + self.world.scenario["id"]

    def _healthy(self):
        if self.fatal_error:
            raise RuntimeError("Business session failed") from self.fatal_error
        if self.llm_client is not None and hasattr(self.llm_client, "raise_if_failed"):
            self.llm_client.raise_if_failed()

    async def ask(self, ctx, instruction, readonly=False, template_mode=False, trace_id=None, parent_span_id=None):
        async with self._ask_lock:
            self._healthy()
            actor = ctx.get("actor_id")
            if type(actor) is not int or actor not in ACTOR_IDS:
                raise ValueError("Trusted actor identity required")
            if any(k in ctx and (type(ctx[k]) is not int or ctx[k] != actor) for k in ("id", "agent_id", "person_id")):
                raise ValueError("Conflicting caller identity")
            if type(ctx.get("round")) is not int or ctx["round"] != self.world.round or type(readonly) is not bool:
                raise ValueError("Stale trusted round or invalid readonly")
            ask_id = ctx["ask_id"]
            UUID(ask_id)
            trusted = {"actor": actor, "readonly": readonly, "ask_id": ask_id,
                "actor_call_index": ctx.get("actor_call_index", -1), "call_index": 0,
                "actor_turn": ctx.get("actor_turn", 0), "visible_asks": list(ctx.get("visible_asks", [])),
                "receipts": [], "instruction": instruction, "variables": deepcopy(ctx.get("variables", {})),
                "router_calls": 0, "router_call_index": None}
            token = _TRUSTED.set(trusted)
            try:
                if instruction == "<observe>":
                    if not readonly:
                        raise ValueError("Initial observation is readonly")
                    try:
                        value = await self.env.observe()
                    except Exception as exc:
                        self.fatal_error = exc
                        raise
                    return {"observation": deepcopy(self.observed[actor].observation)}, canonical(value)
                if actor not in self.observed:
                    raise ValueError("Business request requires initial observation")
                routing_ctx = {"actor_id": actor, "round": self.world.round,
                               "variables": deepcopy(trusted["variables"])}
                try:
                    await super().ask(routing_ctx, instruction, readonly=readonly,
                        template_mode=template_mode, trace_id=trace_id, parent_span_id=parent_span_id)
                except Exception:
                    # Preserve a metered failure swallowed by the router's formatter.
                    self._healthy()
                    raise
                self._healthy()
                return self._ask_answer(ask_id, actor, trusted)
            finally:
                _TRUSTED.reset(token)

    def _ask_answer(self, ask_id, actor, trusted, error=None):
        answer = {"status": "success" if trusted["receipts"] and all(r["ok"] for r in trusted["receipts"]) else "fail",
                  "receipts": trusted["receipts"]}
        if not trusted["receipts"]:
            answer["error"] = error or "No environment tool executed"
        return {"ask_id": ask_id, "receipts": deepcopy(trusted["receipts"]),
            "observation": deepcopy(self.observed[actor].observation)}, canonical(answer)

    async def _execute_tool(self, tool_name, args, readonly):
        trusted = _TRUSTED.get()
        if trusted is None or trusted["readonly"] != readonly:
            raise ValueError("Tool lacks trusted actor context")
        row = {"runtime_version": RUNTIME_VERSION, "round": self.world.round,
            "actor_id": trusted["actor"], "ask_id": trusted["ask_id"],
            "actor_turn": trusted["actor_turn"], "visible_asks": trusted['visible_asks'],
            "actor_call_index": trusted["actor_call_index"], "ordinal": self._route_ordinal,
            "operation": tool_name, "payload": deepcopy(args), "routing": "official_react",
            "router_call_index": trusted["router_call_index"]}
        self._route_ordinal += 1
        try:
            schema = next((x["function"]["parameters"] for x in self._all_tools
                           if x["function"]["name"] == tool_name), None)
            if schema is None:
                raise ValueError("Unknown environment tool: " + str(tool_name))
            validate_schema(args, schema)
            result = await super()._execute_tool(tool_name, args, readonly)
            row.update(ok=True, result=result)
            return result
        except Exception as exc:
            row.update(ok=False, result={"error": str(exc)})
            if not isinstance(exc, (ValueError, ValidationError)):
                self.fatal_error = exc
            raise
        finally:
            trusted["receipts"].append({k: row[k] for k in ("operation", "payload", "result", "ok")})
            try:
                append_jsonl(self.run_dir / "native_routes.jsonl", row)
            except Exception as exc:
                # The official router catches tool errors and keeps reasoning.
                self.fatal_error = exc
                raise

    async def _execute(self, operation, payload):
        trusted = _TRUSTED.get()
        if trusted is None:
            raise RuntimeError("Tool lacks trusted actor context")
        actor = trusted["actor"]
        if operation == "submit" and actor in self.submitted:
            raise ValueError("Already queued this round; at most one business submission is allowed")
        if operation == "observe":
            if actor not in self.observed:
                obs = deepcopy(self.world.observe(actor))
                obs.pop("policy", None)
                obs = decorate_observation(await self.enrich_advice(obs))
                self.observed[actor] = WorkContext(obs)
                self.world.bind_material_context(actor, obs)
                append_jsonl(self.run_dir / "observations.jsonl", {"round": self.world.round, "actor_id": actor, "observation": obs})
            return self.observed[actor].current_work
        if actor not in self.observed:
            raise ValueError("Initial legal observation required")
        if operation == "read_work":
            result = self.observed[actor].read_work_once(payload["section"], payload.get("offset", 0),
                ask_id=trusted['ask_id'], visible_asks=trusted['visible_asks'])
            return result
        if operation == "read_materials":
            session = self.observed[actor]
            obs = session.observation
            ids = decode_material_read(payload, obs)
            if session.seen_materials(ids, trusted['visible_asks']):
                # Identical re-read within the round: nothing new is served,
                # the read quota is not charged again and no state moves.
                from .work import material_stub
                return material_stub(ids, session.material_repeat_count(ids))
            from .materials import lawful_sources
            sources = lawful_sources(self.world, actor)
            if len(ids) > 4 or _size(business_material_result({"sources": [sources[sid] for sid in ids]})) > 10000:
                raise ValueError("Request at most four smaller legal sources")
            result = self.world.read_materials(actor, ids)
            session.receive(result)
            session.mark_materials(ids, trusted['ask_id'])
            append_jsonl(self.run_dir / "material_reads.jsonl", {"round": self.world.round,
                "actor_id": actor, "read_index": obs["materials"]["reads_used"], "source_ids": ids,
                "before_context_sha256": obs["context_sha256"], "result": result,
                "after_context_sha256": session.observation["context_sha256"]})
            self.world.bind_material_context(actor, session.observation)
            return business_material_result(result)
        if operation != "submit" or trusted["readonly"]:
            raise ValueError("Mutation not authorized")
        action = validate_action(decode_candidate_choice(payload, self.observed[actor].observation), self.observed[actor].observation)
        receipt = self.world.submit(actor, action)
        if receipt.get("status") != "queued":
            raise RuntimeError("Validated submission refused")
        receipt = {**receipt, "submission_id": digest([self._identity(), self.world.round, actor]),
                   "action_kind": action["kind"], "target": action["target"]}
        self.receipts[actor] = receipt
        append_jsonl(self.run_dir / "actions.jsonl", {"round": self.world.round, "actor_id": actor,
            "action": action, "receipt": receipt, "submission_id": receipt["submission_id"]})
        return {"action": action, "receipt": receipt}

    def _scripted_response(self, model, messages, **kwargs):
        """Offline model fixture; the installed router still executes its full loop."""
        from litellm import ModelResponse
        from .agent import tool_response
        if model == "coder" and kwargs.get("tools"):
            from .interface import dispatch_plan
            trusted = _TRUSTED.get()
            try:
                name, payload = dispatch_plan(trusted["instruction"], trusted["variables"])
            except ValueError:
                return ModelResponse(choices=[{"finish_reason": "stop", "message": {
                    "role": "assistant", "content": "Unsupported environment request."}}])
            return tool_response(name, payload)
        content = canonical({"status": "success", "summary": "Recorded tool results."})
        return ModelResponse(choices=[{"finish_reason": "stop", "message": {
            "role": "assistant", "content": content}}])

    async def acompletion(self, model, messages, **kwargs):
        self._healthy()
        trusted = _TRUSTED.get()
        if trusted is None or model not in {"coder", "summary"}:
            raise RuntimeError("Routing model lacks trusted request context")
        if kwargs.pop("stream", False):
            raise ValueError("Streaming routing responses are unsupported")
        # These control the official formatter's retries, never transport retries.
        for name in ("max_retries", "base_delay", "max_delay"):
            kwargs.pop(name, None)
        index = trusted["router_calls"]
        trusted["router_calls"] += 1
        trusted["router_call_index"] = index
        row = {"runtime_version": RUNTIME_VERSION, "round": self.world.round,
            "actor_id": trusted["actor"], "ask_id": trusted["ask_id"],
            "router_call_index": index, "model_role": model,
            "request_options": deepcopy(kwargs)}
        try:
            if self.decision_mode == "scripted":
                response = self._scripted_response(model, messages, **kwargs)
            else:
                if self.llm_client is None:
                    raise RuntimeError("Routing model requires the metered client")
                context = {"purpose": "environment_routing", "run_id": self._identity(),
                    "attempt_id": str(self.run_dir.resolve()), "round": self.world.round,
                    "actor_id": trusted["actor"], "ask_id": trusted["ask_id"], "substep": index}
                response = await self.llm_client.call(model=self.llm_client.model_name,
                    messages=messages, audit_context=context, **kwargs)
            request_id = getattr(response, "request_id", None)
            row.update(request_id=request_id, offline=request_id is None)
            if request_id is None:
                row.update(messages=deepcopy(messages), response=response.model_dump(mode="json"))
            append_jsonl(self.run_dir / "native_router_decisions.jsonl", row)
            if (len(response.choices) != 1
                    or response.choices[0].finish_reason not in {"stop", "tool_calls"}):
                raise ValueError("Incomplete routing response; no tools executed")
            return response
        except Exception as exc:
            self.fatal_error = exc
            raise

    def owner_actor_results(self, results):
        """Accept only successful official task results after workspace persistence."""
        self._healthy()
        for item in results:
            if not isinstance(item, dict) or item.get("ok") is not True:
                raise RuntimeError("Official agent task did not persist successfully")
            result = json.loads(item.get("summary") or "null")
            if not isinstance(result, dict):
                raise RuntimeError("Missing actor completion receipt")
            actor = result.get("actor_id")
            if (type(actor) is not int or actor not in ACTOR_IDS
                    or str(item.get("id")) != str(actor)
                    or result.get("runtime_version") != RUNTIME_VERSION
                    or type(result.get("round")) is not int or result["round"] != self.world.round
                    or result.get("step_completed") is not True
                    or actor in self.completed or actor in self.unfiled):
                raise RuntimeError("Invalid, stale or duplicate official actor result")
            submitted = actor in self.submitted
            if (result.get("submitted") is not submitted or result.get("unfiled") is not (not submitted)
                    or submitted and (result.get("receipt") != self.receipts[actor]
                                      or result.get("action") != self.world.pending[str(actor)]["action"])):
                raise RuntimeError("Actor result differs from the authoritative submission")
            (self.completed if submitted else self.unfiled).add(actor)
        return True

    async def to_workspaces(self):
        self._healthy()
        if self.submitted or self.completed or self.unfiled or self.observed or self.receipts:
            raise RuntimeError("Checkpoint requires a clean settled round")
        try:
            await self.env.to_workspace()
            write_json(self.env_path / "router.json", {"runtime_version": RUNTIME_VERSION,
                "material_version": MATERIAL_VERSION, "route_ordinal": self._route_ordinal, "run_id": self._identity(), "round": self.world.round,
                "world_sha256": digest(self.world.export_state()), "advice_cache": self.advice_cache,
                "settlements": self.settlements, "submitted": [], "completed": [], "unfiled": [], "receipts": {}})
            write_json(self.run_dir / "world.json", self.world.export_state())
            write_json(self.run_dir / "metrics.json", self.world.metrics())
            self._saved_round = self.world.round
        except Exception as exc:
            self.fatal_error = exc
            raise

    async def from_workspaces(self):
        self._healthy()
        if self.submitted or self.completed or self.unfiled or self.observed or self.receipts:
            raise RuntimeError("Cannot restore over an active business session")
        path = self.env_path / "router.json"
        if not path.exists():
            if (self.env_path / "state/ENV_STATE.json").exists():
                raise RuntimeError("Incomplete checkpoint")
            return False
        data = read_json(path)
        if (data.get("runtime_version") != RUNTIME_VERSION or data.get("run_id") != self._identity()
                or data.get("material_version") != MATERIAL_VERSION or data.get("submitted") != []
                or data.get("completed") != [] or data.get("receipts") != {} or data.get("unfiled") != []):
            raise RuntimeError("Incompatible checkpoint")
        if not await self.env.restore(self.env_path):
            raise RuntimeError("Missing world checkpoint")
        if data["round"] != self.world.round or data["world_sha256"] != digest(self.world.export_state()):
            raise RuntimeError("World/checkpoint mismatch")
        self.advice_cache, self.settlements = data["advice_cache"], data["settlements"]
        self._route_ordinal = data["route_ordinal"]
        self._saved_round = self.world.round
        return True

    def owner_checkpoint_status(self):
        self._healthy()
        if self._saved_round != self.world.round:
            raise RuntimeError("Environment checkpoint was not saved for this round")
        return {"round": self._saved_round}

    def get_token_usages(self):
        if self.llm_client is not None and hasattr(self.llm_client, "snapshot_token_stats"):
            return self.llm_client.snapshot_token_stats()
        return {}

    async def get_world_description(self):
        return WORLD_DESCRIPTION

    def owner_snapshot(self):
        return self.world.export_state()

    def owner_completion(self):
        return self.world.completion_status()

    def owner_metrics(self):
        return self.world.metrics()

    def owner_partial(self):
        return {"submitted": sorted(self.submitted), "completed": sorted(self.completed), "unfiled": sorted(self.unfiled),
                "receipts": deepcopy(self.receipts), "state": self.world.export_state(),
                "fatal_error": str(self.fatal_error) if self.fatal_error else None}
