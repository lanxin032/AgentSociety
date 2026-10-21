"""Official PersonAgent lifecycle with strict business completion boundaries."""
from copy import deepcopy
import json
from pathlib import Path
from jsonschema import validate as validate_schema
from agentsociety2.agent.person import PersonAgent
from agentsociety2.agent.base import ReactToolResult
from .io import append_jsonl, read_json, write_json
from .interface import canonical, decode_candidate_choice, decode_material_read
from .prompt import WORLD_DESCRIPTION
from .work import WorkContext
from uuid import uuid4
from .router import RUNTIME_VERSION


class TurnIncomplete(RuntimeError):
    """An unfinished model turn cannot commit memory or advance the world."""


def strict_object(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate field: " + key)
            value[key] = item
        return value
    value = json.loads(text, object_pairs_hook=pairs,
        parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be an object")
    canonical(value)
    return value


def tool_response(name, arguments):
    from litellm import ModelResponse
    return ModelResponse(model="offline-policy-fixture", choices=[{"index": 0,
        "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
        "tool_calls": [{"id": "offline-call", "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}}])


class ScriptedClient:
    """Explicit offline fixture that still traverses the official loop."""
    model_name = "offline-policy-fixture"
    def __init__(self, actor):
        self.actor = actor
    def for_context(self, purpose, audit_context=None):
        return self
    def raise_if_failed(self):
        pass
    async def call(self, **kwargs):
        if not kwargs.get("tools"):
            from litellm import ModelResponse
            return ModelResponse(choices=[{"message": {"role": "assistant", "content": "排队不等于执行成功。"}, "finish_reason": "stop"}])
        actor = self.actor
        if actor._submission is not None:
            return tool_response("finish", {"memories": [{"type": "observation", "text": "已排队提交，下一轮核对实际结算。", "importance": .2}]})
        from .scripted import finite_witness_action, scripted_action
        obs = actor._policy_observation
        chooser = finite_witness_action if actor._frozen["record"].get("workload_mode") == "finite" else scripted_action
        action = chooser(obs)
        option = next(x for x in obs["candidate_options"] if x["kind"] == action["kind"]
            and x["target"] == action.get("target") and (x["kind"] == "propose_project" or canonical(x["params"]) == canonical(action["params"])))
        payload = {"candidate_id": option["candidate_id"], "reason": action["reason"]}
        if action["kind"] == "propose_project":
            payload["analysis"] = action["params"]
        return tool_response("ask_env", {"instruction": "submit candidate {candidate_id} with reason {reason}",
                                         "variables": payload, "readonly": False})


class OfficerDispatcher:
    """One restore-time callback routes official decision and memory purposes."""
    def __init__(self, actor, client):
        self.actor, self.client = actor, client
    async def call(self, **kwargs):
        actor = self.actor
        actor._check_failure()
        decision = bool(kwargs.get("tools"))
        purpose = "agent_decision" if decision else "memory"
        if decision:
            actor._completion_calls += 1
        response = await self.client.for_context(purpose, audit_context=actor._context()).call(**kwargs)
        if decision:
            actor._last_request = {"request_id": getattr(response, "request_id", None),
                "request_options": {k: deepcopy(kwargs[k]) for k in ("tools", "tool_choice") if k in kwargs},
                **({"messages": deepcopy(kwargs["messages"])} if not getattr(response, "request_id", None) else {})}
        else:
            append_jsonl(actor.workspace_root_path() / "native_memory.jsonl", {
                "actor_id": actor.id, "round": actor._policy_round,
                "offline": getattr(response, "request_id", None) is None,
                "request_id": getattr(response, "request_id", None),
                **({"messages": kwargs["messages"], "response": response.model_dump(mode="json")}
                   if not getattr(response, "request_id", None) else {})})
        return response


from agentsociety2.agent.memory_runtime import PersonMemoryRuntime


class CheckedMemoryRuntime(PersonMemoryRuntime):
    """Preserve official consolidation while exposing its swallowed failure."""
    def __init__(self, *, on_failure, **kwargs):
        super().__init__(**kwargs)
        self._on_failure = on_failure

    async def _consolidate_memory_md(self, **kwargs):
        try:
            return await super()._consolidate_memory_md(**kwargs)
        except Exception as exc:
            self._on_failure(exc)
            raise


class PolicyOfficer(PersonAgent):
    def build_agent_json(self, *, tick=None, t=None):
        # Official positioning: <agent> carries identity and a brief state
        # pointer, not the full workbench — the overview arrives via observe
        # and read_work (attempt-0059..0068 attention-overload lesson).
        value = super().build_agent_json(tick=tick, t=t)
        observation = getattr(self, "_policy_observation", None)
        if observation is not None:
            from .work import business_receipt
            queued = getattr(self, "_submission", None)
            value["current_work"] = {"phase": "finish" if queued else "choose",
                "round": observation.get("round"), "role": observation.get("role"),
                "candidate_count": len(observation.get("candidate_options", [])),
                "queued_receipt": business_receipt(queued["receipt"]) if queued else None,
                "note": "完整候选、材料与字段经observe和read_work获取。"}
        return value

    def build_react_messages(self, **kwargs):
        from .official_adapter import adapt_official_messages
        return adapt_official_messages(super().build_react_messages(**kwargs))

    def _build_memory_runtime(self):
        # Build the official configuration once at restore, then use an official
        # runtime subclass only to retain failures after_step otherwise catches.
        super()._build_memory_runtime()
        from agentsociety2.logger import get_logger
        self._memory_runtime = CheckedMemoryRuntime(agent_id=self.id, agent_name=self.name,
            config=self._memory_runtime.config, get_model_name=lambda: self._model_name,
            dispatch_llm=lambda **kwargs: self._dispatcher.call(**kwargs),
            get_profile=self.get_profile, logger=get_logger(), trace_span=self.trace_span,
            on_failure=lambda exc: setattr(self, "_fatal", "Memory consolidation failed: " + str(exc)))

    @classmethod
    def mcp_description(cls):
        return "PolicyOfficer: official PersonAgent with authorized business tools."

    async def restore(self, workspace_path, service_proxy):
        await super().restore(workspace_path, service_proxy)
        # Official restore clears this field even when initialized_at survives.
        # Both new and restored actors use the same public business description.
        self._world_description = WORLD_DESCRIPTION
        if self._max_react_turns != 10 or not self._enable_memory or self._enable_todo_list:
            raise ValueError("PolicyOfficer requires official ten-turn memory lifecycle and no TODO tools")
        if self._config.get("runtime_version") != RUNTIME_VERSION:
            raise ValueError("Incompatible officer checkpoint")
        self._run_dir = next((p for p in self.workspace_root_path().parents if (p / "run_config.json").is_file()), None)
        if self._run_dir is None:
            raise ValueError("Frozen run configuration is required")
        self._frozen = read_json(self._run_dir / "run_config.json")
        from .profiles import validate_profile
        profile = validate_profile(self._config["runtime_profile"])
        if profile != self._frozen["runtime_profile"]:
            raise ValueError("Officer profile differs from frozen run")
        self._client = ScriptedClient(self) if self._config.get("decision_mode") == "scripted" else self._dispatcher
        self._model_name = self._client.model_name
        self._dispatcher = OfficerDispatcher(self, self._client)
        # PersonMemoryRuntime's original callback dereferences self._dispatcher;
        # the dispatcher routes memory without patching the memory implementation.
        self._fatal = None
        self._policy_round = self._step_count
        self._policy_observation = self._submission = None
        self._explicit_finish = False
        self._completion_calls = self._schema_errors = 0
        self._official_turn = 0
        self._last_request = {}
        self._last_ask_id = None
        self.skill_runtime.set_visible_skills(set())

    async def _load_world_description(self):
        return WORLD_DESCRIPTION

    def _refresh_visible_skills(self):
        self.skill_runtime.set_visible_skills(set())

    def _context(self):
        return {"run_id": self._frozen["record"]["run_id"], "attempt_id": str(self._run_dir.resolve()),
            "actor_id": self.id, "round": self._policy_round,
            "trace_path": str(self._run_dir / "model_requests.jsonl")}

    def _check_failure(self):
        if self._fatal:
            raise TurnIncomplete(self._fatal)
        self._client.raise_if_failed()

    def env_ask_env_ctx_overlay(self):
        return {**super().env_ask_env_ctx_overlay(), "actor_id": self.id, "round": self._policy_round, "actor_call_index": self._completion_calls - 1, "lifecycle_complete": False}

    async def step(self, tick, t):
        self._policy_round = self._step_count
        self._policy_observation = self._submission = None
        self._explicit_finish = False
        self._completion_calls = self._schema_errors = self._official_turn = 0
        try:
            await super().step(tick, t)
            self._check_failure()
            # A queued submission is the authoritative filing; a missing
            # explicit finish only degrades memory to the official fallback.
            unfiled = self._submission is None
            if unfiled:
                from .failure import unfiled_receipt
                await self._env.ask({**self.env_ask_env_ctx_overlay(), "lifecycle_unfiled": True}, "abandon", readonly=False)
                result = {"runtime_version": RUNTIME_VERSION, "actor_id": self.id, "round": self._policy_round,
                    "receipt": unfiled_receipt(self.id, self._policy_round),
                    "submitted": False, "unfiled": True, "step_completed": True,
                    "schema_repairs": self._schema_errors, "completion_calls": self._completion_calls}
            else:
                await self._env.ask({**self.env_ask_env_ctx_overlay(), "lifecycle_complete": True}, "complete", readonly=False)
                result = {"runtime_version": RUNTIME_VERSION, "actor_id": self.id, "round": self._policy_round,
                    **self._submission, "submitted": True, "unfiled": False, "step_completed": True,
                    "schema_repairs": self._schema_errors, "completion_calls": self._completion_calls}
            write_json(self.workspace_root_path() / "state/native-turn.json", result)
            return canonical(result)
        except Exception as exc:
            self._fatal = str(exc)
            append_jsonl(self.workspace_root_path() / "native_failures.jsonl", {
                "actor_id": self.id, "round": self._policy_round, "error": str(exc)})
            raise

    # run_react_loop / _synthesize_step_fallback_memory / run_lifecycle_hooks
    # stay official: an exhausted or unfinished turn degrades to the official
    # fallback memory and settles as an unfiled round in step() below — the
    # run never dies on model-quality noise (see policy_sim/failure.py).

    async def ask(self, message, readonly=True, **kwargs):
        raise ValueError("External QA is not part of the policy execution interface")

    def _parse_react_responses(self, response, *, readonly=False):
        """Only response integrity and domain completion extend the official parser."""
        error = ""
        try:
            if len(response.choices) != 1 or response.choices[0].finish_reason not in {"tool_calls", "stop"}:
                raise ValueError("Incomplete response: no tools in this batch executed")
            calls = response.choices[0].message.tool_calls or []
            if not calls:
                raise ValueError("Use the provided structured tool calls")
            schemas = {x["function"]["name"]: x["function"]["parameters"]
                       for x in self._last_request.get("request_options", {}).get("tools", [])}
            for call in calls:
                if call.function.name not in schemas:
                    raise ValueError("Tool not offered in this request")
                validate_schema(strict_object(call.function.arguments), schemas[call.function.name])
            if any(c.function.name == "finish" for c in calls) and (self._submission is None or len(calls) != 1):
                raise ValueError("Finish requires the queued business receipt from a previous tool result")
            decisions, error = super()._parse_react_responses(response, readonly=readonly)
            if not error and any(d.action == "finish" for d in decisions):
                self._explicit_finish = True
        except (ValueError, TypeError, AttributeError, IndexError) as exc:
            decisions, error = [], str(exc)
        except Exception as exc:
            from jsonschema import ValidationError
            if not isinstance(exc, ValidationError):
                raise
            decisions, error = [], exc.message
        if error:
            self._schema_errors += 1
        request = self._last_request
        append_jsonl(self.workspace_root_path() / "native_decisions.jsonl", {
            "actor_id": self.id, "round": self._policy_round, "official_turn": self._official_turn,
            "call_index": self._completion_calls - 1, **request,
            **({"response": response.model_dump(mode="json")} if not request.get("request_id") else {}),
            "context_sha256": (self._policy_observation or {}).get("context_sha256"),
            "response_error": error or None, "readonly": readonly})
        return decisions, error

    async def _call_react_llm(self, **kwargs):
        self._check_failure()
        self._official_turn += 1
        return await super()._call_react_llm(**kwargs)

    async def ask_env(self, ctx, message, readonly, **kwargs):
        self._check_failure()
        ask_id = str(uuid4())
        try:
            result, answer = await super().ask_env({**ctx, "ask_id": ask_id}, message, readonly, **kwargs)
            self._last_ask_id = ask_id
            if "observation" in result and result["observation"] != self._policy_observation:
                self._policy_observation = deepcopy(result["observation"])
            for receipt in result.get("receipts", []):
                if receipt["operation"] == "submit" and receipt["ok"]:
                    self._submission = deepcopy(receipt["result"])
            return result, answer
        except Exception as exc:
            self._fatal = str(exc)
            raise

    async def dispatch_react_tool(self, action, args, *, readonly=False):
        self._check_failure()
        if action == "ask_env":
            self._last_ask_id = None
        # Workspace isolation protects research traces and authoritative business
        # files. The actual read/write/memory operations remain official tools.
        if action in {"read", "write", "append", "grep", "list"}:
            path = str(args.get("path", ""))
            resolved = (self.workspace_root_path() / path).resolve()
            notes = self.workspace_root_path() / "notes"
            allowed = resolved.is_relative_to(notes)
            if not allowed:
                result = ReactToolResult(False, "Personal files go in notes/; business data comes via observe/read_work; memory tools for memory.", {"path": path})
            else:
                result = await super().dispatch_react_tool(action, args, readonly=readonly)
        else:
            result = await super().dispatch_react_tool(action, args, readonly=readonly)
        self._check_failure()
        if action == "ask_env":
            result = ReactToolResult(result.ok, result.observation, {**(result.data or {}), "ask_id": self._last_ask_id})
        append_jsonl(self.workspace_root_path() / "native_tool_receipts.jsonl", {
            "actor_id": self.id, "round": self._policy_round, "official_turn": self._official_turn,
            "call_index": self._completion_calls - 1, "action": action, "args": args,
            "ok": result.ok, "observation": result.observation, "data": result.data})
        return result
