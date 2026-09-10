"""Deterministic business environment. No network, framework or LLM imports.

Only observe() and its action skeletons may be passed to a model. export_state()
and events contain privileged ground truth for audit/checkpointing, not prompts.
Decisions are collected against a round snapshot, then settled by a fixed order.
"""

from copy import deepcopy
import hashlib
import json
import math

from .spec import ACTORS, ACTION_PARAM_KEYS, ALLOWED_KINDS, DEFAULT_CONFIG, SPEC_VERSION


def _action(kind, target=None, **params):
    return {"kind": kind, "target": target, "params": params, "reason": "按可见事实执行"}


class PolicyWorld:
    def __init__(self, policy="111", seed=0, horizon=30, config=None):
        if policy not in {f"{i:03b}" for i in range(8)}:
            raise ValueError("policy must be one of eight three-bit strings")
        if not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        self.policy, self.seed, self.horizon = policy, int(seed), horizon
        self.config = deepcopy(DEFAULT_CONFIG)
        if config:
            unknown = set(config) - set(self.config)
            if unknown:
                raise ValueError("unknown config keys: " + ",".join(sorted(unknown)))
            self.config.update(config)
        for name, value in self.config.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("invalid nonnegative finite parameter: " + name)
        for name in ("q0", "q1", "shock_probability", "common_root_shock_probability", "repaired_root_shock_probability"):
            if self.config[name] > 1:
                raise ValueError("probability exceeds one: " + name)
        for name in ("signal_window", "signal_threshold", "signal_cooldown", "project_lag", "project_steps", "repeat_report_interval", "shared_crew_capacity"):
            if self.config[name] < 1 or int(self.config[name]) != self.config[name]:
                raise ValueError("positive integer parameter required: " + name)
        if self.config["q0"] > self.config["q1"]:
            raise ValueError("q0 must not exceed q1")
        self.round = 0
        self.events, self.pending, self.issues, self.tickets, self.projects = [], {}, {}, {}, {}
        self.facilities, self.topic_history = {}, {}
        self.labor = {str(actor): float(self.config["labor_per_actor"]) for actor in ACTORS}
        self.capital = float(self.config["capital"])
        self.crew_remaining = self.config["shared_crew_capacity"]
        self.burden = 0
        self.initial_ids = []
        self._build()
        self._register_topics()

    def _random(self, *event_key):
        encoded = json.dumps([self.seed, *event_key], ensure_ascii=False, separators=(",", ":")).encode()
        return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") / 2**64

    def _offered(self, tool, key):
        q = self.config["q1"] if self.policy["ABC".index(tool)] == "1" else self.config["q0"]
        return self._random("offer", tool, key) < q

    def _log(self, kind, **details):
        event = {"event_index": len(self.events), "round": self.round, "kind": kind, **deepcopy(details)}
        self.events.append(event)
        return event

    def _build(self):
        for district in range(4):
            for number in range(3):
                fid = f"F{district + 1}-{number + 1}"
                # True infrastructure topology is privileged until paid investigation.
                self.facilities[fid] = {
                    "facility": fid, "district": f"片区{district + 1}",
                    "archetype": district, "root": "R-common" if district == 2 else f"R-{fid}",
                    "root_repaired": False,
                    "required": [2, 3] if district == 1 else [2 if number != 2 else 3],
                    "category": "供水波动" if district >= 2 else ["阀门漏水", "泵机停转", "路面破损"][number],
                }
                iid = self._new_issue(fid, initial=True)
                self.initial_ids.append(iid)
        self._log("initialized", policy=self.policy, seed=self.seed, spec_version=SPEC_VERSION,
                  resources={"labor": self.labor, "capital": self.capital})

    def _new_issue(self, fid, initial=False):
        facility = self.facilities[fid]
        iid = f"I{len(self.issues) + 1:05d}"
        tid = f"T{len(self.tickets) + 1:05d}"
        recurrence = any(i["facility"] == fid and i["resolved"] is not None for i in self.issues.values())
        issue = {"id": iid, "facility": fid, "created": self.round, "resolved": None,
                 "initial": initial, "recurrence": recurrence, "required": facility["required"][:], "done": []}
        self.issues[iid] = issue
        descriptor = "供水与道路接入同时异常" if facility["archetype"] == 1 else facility["category"]
        self.tickets[tid] = {
            "id": tid, "issue": iid, "facility": fid, "district": facility["district"],
            "text": descriptor, "category": facility["category"], "reported": self.round,
            "public_episode": f"{fid}:居民记录{self.round}", "lead": None,
            "inspected": False, "known_required": [], "coordination": None,
            "shared_board": False, "done": [], "closed": False,
            "joint_participants": [], "joint_confirmed_by": [], "joint_activated_round": None,
            "a_offered": self._offered("A", tid), "a_called": False,
        }
        self._log("issue_created", issue=iid, ticket=tid, facility=fid, initial=initial)
        self._log("tool_opportunity", tool="A", opportunity=tid, offered=self.tickets[tid]["a_offered"])
        return iid

    def _visible_ticket(self, ticket, actor):
        # Explicit whitelist. Never copy a raw ticket/issue into an observation.
        result = {k: deepcopy(ticket[k]) for k in (
            "id", "facility", "district", "text", "category", "reported",
            "public_episode", "lead", "closed")}
        if actor == 1:
            result["a_offered"] = ticket["a_offered"]
            if ticket["a_offered"]:
                # This rule reads public text, never issue.required or facility.root.
                text = ticket["text"]
                candidates = [3, 2] if "路面" in text else [2, 3]
                result["recommendation"] = {
                    "type": "deterministic_visible_text_rule_not_ai",
                    "provenance": "rule_fixture",
                    "candidates": candidates,
                    "uncertain": "同时" in text or "波动" in text,
                    "basis": "公开目录：供水先联系供水办理；路面先联系基础设施办理；可核查后调整。",
                    "additional_labor_cost": self.config["recommendation_cost"],
                }
        if actor in (2, 3) and (ticket["lead"] == actor or actor in ticket["known_required"]):
            result["inspected"] = ticket["inspected"]
            result["known_required"] = ticket["known_required"][:]
            result["own_task_done"] = actor in ticket["done"]
            result["coordination"] = ticket["coordination"]
            if ticket["coordination"] == "joint" and actor in ticket["joint_participants"]:
                result["joint_invitation"] = {
                    "participants": ticket["joint_participants"][:],
                    "confirmed_by": ticket["joint_confirmed_by"][:],
                    "activated_round": ticket["joint_activated_round"],
                }
            if ticket["shared_board"]:
                result["shared_board"] = {"required": ticket["known_required"][:], "done": ticket["done"][:]}
            else:
                result["conventional_feedback"] = "已收到反馈：" + ",".join(str(x) for x in ticket["done"])
        return result

    def _register_topics(self):
        recorded = {e["opportunity"] for e in self.events if e["kind"] == "tool_opportunity" and e["tool"] == "C"}
        for topic in self._topics():
            if topic["eligible"] and topic["episode"] not in recorded:
                self._log("tool_opportunity", tool="C", opportunity=topic["episode"], offered=topic["c_offered"])

    def _topics(self):
        groups = {}
        # Public episode keys are derived from submitted records, not hidden issue IDs.
        for ticket in self.tickets.values():
            if ticket["reported"] < self.round - self.config["signal_window"] + 1:
                continue
            key = ticket["district"] + "|" + ticket["category"]
            group = groups.setdefault(key, {"id": key, "district": ticket["district"],
                                           "category": ticket["category"], "episodes": set(), "facilities": set()})
            group["episodes"].add(ticket["public_episode"])
            group["facilities"].add(ticket["facility"])
        result = []
        for key in sorted(groups):
            group = groups[key]
            if len(group["episodes"]) < self.config["signal_threshold"]:
                continue
            active = any(p["topic"] == key and p["state"] not in ("completed", "failed") for p in self.projects.values())
            last = self.topic_history.get(key)
            eligible = not active and (last is None or self.round - last >= self.config["signal_cooldown"])
            episode = f"{key}@{0 if last is None else last + self.config['signal_cooldown']}"
            result.append({"id": key, "district": group["district"], "category": group["category"],
                           "record_count": len(group["episodes"]), "facilities": sorted(group["facilities"]),
                           "eligible": eligible, "episode": episode,
                           "c_offered": self._offered("C", episode)})
        return result

    def observe(self, actor_id):
        if type(actor_id) is not int or actor_id not in ACTORS:
            raise ValueError("unknown actor_id")
        # A queued submission is not the business verdict. Publish only this
        # actor's latest settlement and own costs, without exposing the audit log.
        latest = next((e for e in reversed(self.events) if e["kind"] == "action_result" and e["actor_id"] == actor_id), None)
        last_receipt = None
        if latest is not None:
            own_spending = [e for e in self.events if e["kind"] == "resource_spent"
                            and e["actor_id"] == actor_id and e["round"] == latest["round"]]
            last_receipt = {
                "round": latest["round"], "status": latest["status"], "code": latest["code"],
                "action_kind": latest["action"]["kind"], "target": latest["action"]["target"],
                "resources_paid": {key: round(sum(e[key] for e in own_spending), 8) for key in ("labor", "capital", "crew")},
            }
        visible = []
        for ticket in self.tickets.values():
            if actor_id in (1, 4) or ticket["lead"] == actor_id or (ticket["coordination"] and actor_id in ticket["known_required"]):
                visible.append(self._visible_ticket(ticket, actor_id))
        actions = [_action("wait")]
        projects, topics = [], self._topics() if actor_id == 4 else []
        if self.round < self.horizon:
            for ticket in visible:
                if ticket["closed"]:
                    continue
                if actor_id == 1 and ticket["lead"] is None:
                    for department in (2, 3):
                        actions.append(_action("route", ticket["id"], department=department, use_recommendation=False))
                    if ticket.get("recommendation"):
                        actions.append(_action("route", ticket["id"], department=ticket["recommendation"]["candidates"][0], use_recommendation=True))
                if actor_id in (2, 3):
                    if not ticket.get("inspected", False) and ticket["lead"] == actor_id:
                        actions.append(_action("inspect", ticket["id"]))
                    elif ticket.get("inspected"):
                        required = ticket["known_required"]
                        if (len(required) > 1 or ticket["lead"] not in required) and ticket["coordination"] is None and ticket["lead"] == actor_id:
                            actions.append(_action("request_coordination", ticket["id"], mode="conventional"))
                            if self._offered("B", ticket["id"]):
                                actions.append(_action("request_coordination", ticket["id"], mode="joint"))
                        invitation = ticket.get("joint_invitation")
                        if invitation and actor_id in invitation["participants"] and actor_id not in invitation["confirmed_by"]:
                            actions.append(_action("confirm_joint_task", ticket["id"]))
                        if actor_id in required and not ticket["own_task_done"] and (actor_id == ticket["lead"] or ticket["coordination"]):
                            actions.append(_action("work", ticket["id"]))
            if actor_id == 4:
                for topic in topics:
                    if topic["eligible"]:
                        actions.append(_action("propose_project", topic["id"], mode="conventional"))
                        if topic["c_offered"]:
                            actions.append(_action("propose_project", topic["id"], mode="structured"))
                for project in self.projects.values():
                    public = {key: deepcopy(project[key]) for key in (
                        "id", "topic", "state", "mode", "evidence", "plan", "steps_done", "ready_round")}
                    if project["mode"] == "structured":
                        public["project_board"] = {"next_stage": project["state"], "construction_steps_required": self.config["project_steps"], "capital_per_step": self.config["project_step_capital"]}
                    else:
                        public["conventional_record"] = "常规项目记录；方案审查、实施与验收仍须完成，施工分项数见公共规程。"
                    projects.append(public)
                    if project["state"] == "proposed":
                        actions.append(_action("diagnose_project", project["id"]))
                    elif project["state"] in ("diagnosed", "building"):
                        for plan in ("replace_shared_main", "local_repairs"):
                            actions.append(_action("implement_project", project["id"], plan=plan))
                    elif project["state"] == "awaiting_acceptance":
                        actions.append(_action("accept_project", project["id"]))
        return {
            "spec_version": SPEC_VERSION, "round": self.round, "horizon": self.horizon,
            "actor_id": actor_id, "role": ACTORS[actor_id],
            "last_receipt": last_receipt,
            "visible_tickets": visible, "topics": topics, "projects": projects,
            "resources": {"own_labor": self.labor[str(actor_id)], "capital": self.capital,
                          "shared_crew_remaining": self.crew_remaining},
            "public_rules": {
                "directory": {"2": "供水及机泵", "3": "路面及基础设施"},
                "project_steps": self.config["project_steps"], "project_lag": self.config["project_lag"],
                "root_evidence_rule": "调查至少三处设施发现同一上游资产缺陷，方支持共享主干线更换；高频本身不证明共同根因。",
                "baseline": "常规协调及专项治理在全部情景合法可用。",
                "case_workflow": "角色1先route派单；角色2或3作为承办方inspect取得个案任务信息，依法普通协调或选择可用的联合流程，再work执行本部门任务。inspect只用于个案且仅角色2或3可执行；任务完成与实际解决由环境核验。联合确认可选，普通work不以全体确认作为前提。",
                "project_workflow": "角色4处理专项：先对符合条件的可见选题propose_project，再对已立项项目diagnose_project取得调查证据，然后根据证据选择可实施方案并执行implement_project各工序；完成工序后等待公开project_lag，再accept_project申请验收。角色4不使用inspect调查个案；立项、诊断、施工及验收均不自动保证成功，也不要求选择专项而放弃常规处理。",
            },
            "available_actions": actions,
        }

    def submit(self, actor_id, action):
        if type(actor_id) is not int or actor_id not in ACTORS:
            return {"status": "technical_error", "code": "unknown_actor", "round": self.round}
        receipt = {"actor_id": actor_id, "round": self.round}
        if not isinstance(action, dict) or set(action) != {"kind", "target", "params", "reason"} or not isinstance(action.get("kind"), str) or not isinstance(action.get("params"), dict) or not isinstance(action.get("reason"), str) or (action.get("target") is not None and not isinstance(action["target"], str)):
            return {**receipt, "status": "technical_error", "code": "invalid_action_schema"}
        allowed_params = ACTION_PARAM_KEYS.get(action["kind"], set())
        if set(action["params"]) - allowed_params:
            return {**receipt, "status": "technical_error", "code": "unexpected_action_params"}
        try:
            canonical = json.dumps(action, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            return {**receipt, "status": "technical_error", "code": "non_json_action"}
        if self.round >= self.horizon:
            return {**receipt, "status": "business_rejected", "code": "horizon_reached"}
        key = str(actor_id)
        if key in self.pending:
            if self.pending[key]["canonical"] == canonical:
                return {**receipt, "status": "queued", "code": "duplicate_idempotent"}
            return {**receipt, "status": "business_rejected", "code": "one_action_per_round"}
        self.pending[key] = {"action": deepcopy(action), "canonical": canonical}
        self._log("action_submitted", actor_id=actor_id, action=action)
        return {**receipt, "status": "queued", "code": "accepted_for_settlement"}

    def _pay(self, actor, labor, capital=0, crew=0):
        key = str(actor)
        if self.labor[key] + 1e-9 < labor or self.capital + 1e-9 < capital or self.crew_remaining < crew:
            return False
        self.labor[key] = round(self.labor[key] - labor, 8)
        self.capital = round(self.capital - capital, 8)
        self.crew_remaining -= crew
        self._log("resource_spent", actor_id=actor, labor=labor, capital=capital, crew=crew)
        return True

    def _execute(self, actor, action):
        kind, target, params = action["kind"], action["target"], action["params"]
        if kind == "wait":
            return True, "waited"
        if not self._pay(actor, self.config["decision_cost"]):
            return False, "insufficient_decision_labor"
        if kind not in ALLOWED_KINDS:
            return False, "unknown_business_action"
        if kind in ("route", "inspect", "request_coordination", "confirm_joint_task", "work"):
            ticket = self.tickets.get(target)
            if ticket is None:
                return False, "unknown_ticket"
            if ticket["closed"]:
                return False, "already_closed"
            if kind == "route":
                if actor != 1 or ticket["lead"] is not None:
                    return False, "route_not_permitted"
                department = params.get("department")
                use_recommendation = params.get("use_recommendation", False)
                if type(department) is not int or department not in (2, 3) or type(use_recommendation) is not bool:
                    return False, "invalid_route_parameters"
                if use_recommendation and not ticket["a_offered"]:
                    return False, "recommendation_not_offered"
                cost = self.config["route_cost"] + (self.config["recommendation_cost"] if use_recommendation else 0)
                if not self._pay(actor, cost):
                    return False, "insufficient_labor"
                ticket["lead"] = department
                ticket["a_called"] = use_recommendation
                self._log("routed", ticket=target, department=department, recommendation_used=use_recommendation,
                          initially_matched=department in self.issues[ticket["issue"]]["required"])
                return True, "routed"
            if actor not in (2, 3):
                return False, "department_action_required"
            if kind == "inspect":
                if ticket["lead"] != actor or ticket["inspected"]:
                    return False, "inspection_not_permitted"
                if not self._pay(actor, self.config["inspect_cost"]):
                    return False, "insufficient_labor"
                ticket["inspected"] = True
                ticket["known_required"] = self.issues[ticket["issue"]]["required"][:]
                if len(ticket["known_required"]) > 1 or actor not in ticket["known_required"]:
                    self._log("tool_opportunity", tool="B", opportunity=target, offered=self._offered("B", target))
                return True, "inspection_revealed_task_requirements"
            if kind == "request_coordination":
                if ticket["lead"] != actor or not ticket["inspected"] or ticket["coordination"]:
                    return False, "coordination_not_permitted"
                if len(ticket["known_required"]) < 2 and actor in ticket["known_required"]:
                    return False, "no_detected_cross_department_need_or_dispute"
                mode = params.get("mode", "conventional")
                if mode not in ("conventional", "joint"):
                    return False, "invalid_coordination_mode"
                if mode == "joint" and not self._offered("B", target):
                    return False, "joint_board_not_offered"
                cost = self.config["coordination_cost"] + (self.config["board_cost"] if mode == "joint" else 0)
                if not self._pay(actor, cost):
                    return False, "insufficient_labor"
                ticket["coordination"] = mode
                if mode == "joint":
                    ticket["joint_participants"] = sorted(set([ticket["lead"]] + ticket["known_required"]))
                    ticket["joint_confirmed_by"] = []
                    ticket["joint_activated_round"] = None
                    ticket["shared_board"] = False
                return True, "coordination_established"
            if kind == "confirm_joint_task":
                if ticket["coordination"] != "joint" or actor not in ticket["joint_participants"]:
                    return False, "joint_confirmation_not_permitted"
                if actor in ticket["joint_confirmed_by"]:
                    return False, "joint_task_already_confirmed"
                # Confirmation spends only the common decision cost already paid above.
                # It neither completes a repair nor gates the ordinary work route.
                ticket["joint_confirmed_by"] = sorted(ticket["joint_confirmed_by"] + [actor])
                self._log("joint_task_confirmed", ticket=target, actor_id=actor)
                if ticket["joint_confirmed_by"] == ticket["joint_participants"]:
                    ticket["joint_activated_round"] = self.round
                    ticket["shared_board"] = True
                    self._log("joint_board_activated", ticket=target, participants=ticket["joint_participants"])
                return True, "joint_task_confirmed"
            if not ticket["inspected"] or actor not in ticket["known_required"] or actor in ticket["done"]:
                return False, "work_not_permitted"
            if actor != ticket["lead"] and not ticket["coordination"]:
                return False, "no_assignment_or_coordination"
            if not self._pay(actor, self.config["work_cost"], self.config["case_work_capital"], crew=1):
                return False, "insufficient_work_labor_capital_or_crew"
            ticket["done"].append(actor)
            issue = self.issues[ticket["issue"]]
            issue["done"] = ticket["done"][:]
            if set(issue["required"]).issubset(issue["done"]):
                self._resolve(issue, source="individual_tasks")
            return True, "work_completed"
        if actor != 4:
            return False, "project_role_required"
        if kind == "propose_project":
            topic = next((x for x in self._topics() if x["id"] == target and x["eligible"]), None)
            if topic is None:
                return False, "topic_not_eligible"
            mode = params.get("mode", "conventional")
            if mode not in ("conventional", "structured"):
                return False, "invalid_project_mode"
            if mode == "structured" and not topic["c_offered"]:
                return False, "project_board_not_offered"
            cost = self.config["project_proposal_cost"] + (self.config["board_cost"] if mode == "structured" else 0)
            if not self._pay(actor, cost):
                return False, "insufficient_labor"
            pid = f"P{len(self.projects) + 1:04d}"
            self.projects[pid] = {"id": pid, "topic": target, "facilities": topic["facilities"],
                                  "state": "proposed", "mode": mode, "evidence": [], "plan": None,
                                  "steps_done": 0, "ready_round": None, "created": self.round}
            self._log("project_proposed", project=pid, topic=target, mode=mode)
            return True, "project_proposed"
        project = self.projects.get(target)
        if project is None:
            return False, "unknown_project"
        if kind == "diagnose_project":
            if project["state"] != "proposed":
                return False, "diagnosis_not_permitted"
            if not self._pay(actor, self.config["project_diagnosis_cost"]):
                return False, "insufficient_labor"
            # Paid physical tracing reveals an observable asset connection, not a root ID.
            for fid in project["facilities"]:
                facility = self.facilities[fid]
                shared = facility["archetype"] == 2
                project["evidence"].append({"facility": fid, "method": "现场溯源检查",
                    "observed_asset": "片区3共享主干线" if shared else fid + "局部设备",
                    "defect_observed": not facility["root_repaired"], "verified": True})
            project["state"] = "diagnosed"
            return True, "field_evidence_collected"
        if kind == "implement_project":
            if project["state"] not in ("diagnosed", "building") or not project["evidence"]:
                return False, "evidence_or_stage_missing"
            plan = params.get("plan")
            if plan not in ("replace_shared_main", "local_repairs"):
                return False, "plan_not_in_action_library"
            if project["plan"] and project["plan"] != plan:
                return False, "cannot_change_plan_mid_construction"
            # Wrong but physically possible plans may consume resources; verdict stays independent.
            if not self._pay(actor, self.config["project_work_cost"], self.config["project_step_capital"], crew=1):
                return False, "insufficient_project_resources"
            project["plan"] = plan
            project["steps_done"] += 1
            project["state"] = "building"
            if project["steps_done"] >= self.config["project_steps"]:
                project["state"] = "awaiting_acceptance"
                project["ready_round"] = self.round + self.config["project_lag"]
            return True, "construction_step_completed"
        if kind == "accept_project":
            if project["state"] != "awaiting_acceptance":
                return False, "construction_incomplete"
            if self.round < project["ready_round"]:
                return False, "effect_lag_not_elapsed"
            if not self._pay(actor, self.config["project_accept_cost"]):
                return False, "insufficient_labor"
            facilities = [self.facilities[fid] for fid in project["facilities"]]
            matching = (project["plan"] == "replace_shared_main" and len(facilities) >= 3
                        and len({f["root"] for f in facilities}) == 1
                        and all(f["archetype"] == 2 and not f["root_repaired"] for f in facilities)
                        and all(e["verified"] and e["defect_observed"] for e in project["evidence"]))
            if not matching:
                project["state"] = "failed"
                self.topic_history[project["topic"]] = self.round
                self._log("project_failed", project=target, reason="no_matching_shared_structural_cause")
                return False, "no_matching_shared_structural_cause"
            for facility in facilities:
                facility["root_repaired"] = True
            project["state"] = "completed"
            self.topic_history[project["topic"]] = self.round
            self._log("project_completed", project=target, facilities=project["facilities"])
            return True, "structure_changed_after_verification"
        return False, "unsupported_action"

    def _resolve(self, issue, source):
        issue["resolved"] = self.round + 1
        for ticket in self.tickets.values():
            if ticket["issue"] == issue["id"]:
                ticket["closed"] = True
        self._log("issue_resolved", issue=issue["id"], source=source)

    def advance(self):
        if self.round >= self.horizon:
            return
        # Public rotating priority prevents permanent last-place exclusion from shared crews.
        departments = [2, 3, 4]
        offset = self.round % len(departments)
        settlement_order = [1] + departments[offset:] + departments[:offset]
        self._log("settlement_order", actors=settlement_order, shared_crew_capacity=self.config["shared_crew_capacity"])
        for actor in settlement_order:
            action = self.pending.get(str(actor), {}).get("action", _action("wait"))
            ok, code = self._execute(actor, action)
            self._log("action_result", actor_id=actor, action=action,
                      status="executed" if ok else "business_rejected", code=code)
        self.pending = {}
        self.burden += sum(issue["resolved"] is None for issue in self.issues.values())
        self.round += 1
        if self.round < self.horizon:
            for fid, facility in self.facilities.items():
                probability = self.config["shock_probability"]
                if facility["archetype"] == 2:
                    probability = self.config["repaired_root_shock_probability"] if facility["root_repaired"] else self.config["common_root_shock_probability"]
                draw = self._random("external_shock", fid, self.round)
                self._log("external_shock", facility=fid, draw=draw, probability=probability)
                if draw < probability:
                    if any(i["facility"] == fid and i["resolved"] is None for i in self.issues.values()):
                        self._log("suppress_new_issue", facility=fid, reason="existing_unresolved_problem",
                                  contact_rule="subsequent contact is consolidated by public episode")
                    else:
                        self._new_issue(fid)
            # Repeat contact is a separate ticket, but preserves a public deduplication key.
            originals = list(self.tickets.values())
            for ticket in originals:
                if ticket.get("repeat_of") or ticket["closed"] or self.round - ticket["reported"] != self.config["repeat_report_interval"]:
                    continue
                duplicate = deepcopy(ticket)
                tid = f"T{len(self.tickets) + 1:05d}"
                duplicate.update(id=tid, reported=self.round, repeat_of=ticket["id"])
                # A repeat remains linked administratively; no extra assignable task or A opportunity.
                duplicate["closed"] = True
                self.tickets[tid] = duplicate
                self._log("repeat_contact", ticket=tid, repeat_of=ticket["id"], public_episode=ticket["public_episode"])
            self._register_topics()
        self.crew_remaining = self.config["shared_crew_capacity"]
        self._log("round_completed", completed_round=self.round, unresolved=sum(i["resolved"] is None for i in self.issues.values()), burden=self.burden)

    def metrics(self):
        initial = [self.issues[iid] for iid in self.initial_ids]
        resolved = [i for i in initial if i["resolved"] is not None]
        opportunities = [e for e in self.events if e["kind"] == "tool_opportunity"]
        offer = {}
        for tool in "ABC":
            unique = {e["opportunity"]: e["offered"] for e in opportunities if e["tool"] == tool}
            offer[tool] = {"eligible": len(unique), "offered": sum(unique.values()),
                           "offer_rate": sum(unique.values()) / len(unique) if unique else None}
        used = {"A": sum(t["a_called"] for t in self.tickets.values() if not t.get("repeat_of")),
                "B": sum(t["coordination"] == "joint" for t in self.tickets.values() if not t.get("repeat_of")),
                "C": sum(p["mode"] == "structured" for p in self.projects.values())}
        for tool in "ABC":
            offer[tool]["used"] = used[tool]
            offer[tool]["use_rate"] = used[tool] / offer[tool]["offered"] if offer[tool]["offered"] else None
        completed = {
            "A": used["A"],
            "B": sum(t["coordination"] == "joint" and t["closed"] for t in self.tickets.values() if not t.get("repeat_of")),
            "C": sum(p["mode"] == "structured" and p["state"] == "completed" for p in self.projects.values()),
        }
        for tool in "ABC":
            offer[tool]["completed"] = completed[tool]
            offer[tool]["completion_rate"] = completed[tool] / used[tool] if used[tool] else None
        offer["A"]["objective_resolved"] = sum(t["a_called"] and t["closed"] for t in self.tickets.values() if not t.get("repeat_of"))
        offer["B"]["objective_resolved"] = completed["B"]
        joint_cases = [t for t in self.tickets.values() if not t.get("repeat_of") and t["coordination"] == "joint"]
        offer["B"]["confirmed_participations"] = sum(len(t["joint_confirmed_by"]) for t in joint_cases)
        offer["B"]["fully_confirmed_cases"] = sum(t["joint_activated_round"] is not None for t in joint_cases)
        offer["B"]["confirmed_and_resolved"] = sum(t["joint_activated_round"] is not None and t["closed"] for t in joint_cases)
        offer["C"]["objective_resolved"] = 0
        routing = [e for e in self.events if e["kind"] == "routed"]
        return {"round": self.round, "horizon": self.horizon, "policy": self.policy, "seed": self.seed,
                "initial_issues": len(initial), "initial_resolved": len(resolved),
                "initial_resolution_rate": len(resolved) / len(initial),
                "initial_censored_mean_time": sum(i["resolved"] if i["resolved"] is not None else self.round for i in initial) / len(initial),
                "unresolved_issues": sum(i["resolved"] is None for i in self.issues.values()),
                "cumulative_issue_burden": self.burden,
                "new_issues": sum(not i["initial"] for i in self.issues.values()),
                "recurrent_episodes": sum(i["recurrence"] for i in self.issues.values()),
                "first_routing_match_rate": sum(e["initially_matched"] for e in routing) / len(routing) if routing else None,
                "repeat_contacts": sum(bool(t.get("repeat_of")) for t in self.tickets.values()),
                "projects_completed": sum(p["state"] == "completed" for p in self.projects.values()),
                "projects_failed": sum(p["state"] == "failed" for p in self.projects.values()),
                "labor_spent": round(4 * self.config["labor_per_actor"] - sum(self.labor.values()), 8),
                "capital_spent": round(self.config["capital"] - self.capital, 8),
                "shared_crew_units_spent": sum(e["crew"] for e in self.events if e["kind"] == "resource_spent"),
                "tool_process": offer,
                "tool_process_definitions": {
                    "A_completed": "accepted routing action using offered recommendation; not objective resolution",
                    "B_completed": "all required individual-case tasks verified complete",
                    "C_completed": "shared structural intervention independently accepted after lag",
                    "objective_resolved": "resolved existing issues among tool users; descriptive, not causal attribution; C changes future risk and directly resolves no local-damage issues",
                    "C_prevention": "compare new_issues across paired simulations; never infer prevention from acceptance alone",
                },
                "business_rejections": sum(e["kind"] == "action_result" and e["status"] == "business_rejected" for e in self.events),
                "parameter_basis": "synthetic_uncalibrated"}

    def export_state(self):
        return {"spec_version": SPEC_VERSION, **deepcopy(self.__dict__)}

    @classmethod
    def from_state(cls, state):
        if state.get("spec_version") != SPEC_VERSION:
            raise ValueError("unsupported state version")
        world = cls.__new__(cls)
        world.__dict__.update(deepcopy({k: v for k, v in state.items() if k != "spec_version"}))
        return world


def scripted_action(observation):
    """Transparent fixture controller, using only public observation/action skeletons."""
    actions = observation["available_actions"]
    actor = observation["actor_id"]
    if actor == 1:
        routes = [a for a in actions if a["kind"] == "route"]
        if routes:
            first = routes[0]["target"]
            ticket = next(t for t in observation["visible_tickets"] if t["id"] == first)
            candidates = [a for a in routes if a["target"] == first]
            tool = next((a for a in candidates if a["params"].get("use_recommendation")), None)
            if tool:
                return deepcopy(tool)
            department = 3 if "路面" in ticket["text"] else 2
            return deepcopy(next(a for a in candidates if a["params"]["department"] == department))
    if actor in (2, 3):
        for kind in ("request_coordination", "confirm_joint_task", "work", "inspect"):
            candidates = [a for a in actions if a["kind"] == kind]
            if candidates:
                return deepcopy(next((a for a in candidates if a["params"].get("mode") == "joint"), candidates[0]))
    if actor == 4:
        for project in observation["projects"]:
            candidates = [a for a in actions if a["target"] == project["id"]]
            for action in candidates:
                if action["kind"] == "diagnose_project":
                    return deepcopy(action)
                if action["kind"] == "implement_project":
                    evidence = project["evidence"]
                    shared = len(evidence) >= 3 and len({e["observed_asset"] for e in evidence}) == 1
                    desired = "replace_shared_main" if shared else "local_repairs"
                    if action["params"]["plan"] == desired:
                        return deepcopy(action)
                if action["kind"] == "accept_project" and observation["round"] >= project["ready_round"]:
                    return deepcopy(action)
        proposals = [a for a in actions if a["kind"] == "propose_project"]
        if proposals:
            first = proposals[0]["target"]
            candidates = [a for a in proposals if a["target"] == first]
            return deepcopy(next((a for a in candidates if a["params"].get("mode") == "structured"), candidates[0]))
    return deepcopy(next(a for a in actions if a["kind"] == "wait"))
