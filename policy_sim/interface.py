"""Pure presentation of one authorized observation; no world or history access."""
from copy import deepcopy
import hashlib
import json

INTERFACE_VERSION = "v3.3-materials-13"
# Kept beside the presentation layer because checkpoints and the independent
# audit re-derive it without importing the framework-bound runtime.
RUNTIME_VERSION = "official-policy-6"
DERIVED_FIELDS = frozenset({"interface_version", "context_sha256", "candidate_options", "evidence_index"})
INTERFACE_FIELDS = DERIVED_FIELDS


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def raw_observation(observation):
    """Remove only this module's reserved presentation fields, preserving all facts."""
    if not isinstance(observation, dict):
        raise ValueError("Observation must be an object")
    return deepcopy({k: v for k, v in observation.items() if k not in DERIVED_FIELDS})


def _hash(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _candidate_context(raw):
    """Bind business choices without treating another copy of evidence as new state."""
    state = deepcopy(raw)
    state["available_actions"] = [
        {key: action.get(key) for key in ("kind", "target", "params")}
        for action in raw["available_actions"]]
    materials = state.get("materials", {})
    materials.pop("reads_used", None)
    # source_index binds each lawful source's content version. Its raw delivery
    # copy adds no candidate semantics; genuinely new delivery still changes IDs.
    materials.pop("raw", None)
    if "delivered_raw_ids" in materials:
        materials["delivered_raw_ids"] = sorted(set(materials["delivered_raw_ids"]))
    return _hash(state)


def _evidence(raw):
    result = []
    for collection in ("visible_tickets", "projects"):
        for i, obj in enumerate(raw.get(collection, [])):
            base = f"/{collection}/{i}"
            oid = obj["id"]
            entry = {"object": oid, "source": base, "sent_messages": [],
                     "received_messages": [], "visible_confirmation_records": [],
                     "own_confirmation": {"value": "unknown", "source": None},
                     "tasks": []}
            if type(obj.get("own_confirmed")) is bool:
                entry["own_confirmation"] = {"value": obj["own_confirmed"], "source": base + "/own_confirmed"}
            elif isinstance(obj.get("joint_invitation"), dict) and type(obj["joint_invitation"].get("own_confirmed")) is bool:
                entry["own_confirmation"] = {"value": obj["joint_invitation"]["own_confirmed"], "source": base + "/joint_invitation/own_confirmed"}
            for field, dest in (("sent_messages", "sent_messages"), ("inbox", "received_messages")):
                for j, message in enumerate(raw.get(field, [])):
                    if message.get("object") == oid:
                        entry[dest].append({"id": message.get("id"), "kind": message.get("kind"), "source": f"/{field}/{j}"})
            for j, record in enumerate(obj.get("received_records", [])):
                if record.get("kind") in ("joint_confirmation", "project_confirmation", "project_lead_confirmation"):
                    entry["visible_confirmation_records"].append({"author": record.get("author"), "kind": record["kind"], "source": base + f"/received_records/{j}"})
            for j, task in enumerate(obj.get("tasks", [])):
                tid = task["id"]
                refs = {"dispatch_sent_evidence": [], "received_assignment_evidence": [], "received_record_evidence": []}
                for field, dest in (("sent_messages", "dispatch_sent_evidence"), ("inbox", "received_assignment_evidence")):
                    for m, message in enumerate(raw.get(field, [])):
                        # A status query/reply or task plan alone is not dispatch evidence.
                        if message.get("kind") not in ("case_assignment", "joint_invitation", "review_assignment", "construction_assignment", "commissioning_assignment"):
                            continue
                        for n, defined in enumerate(message.get("payload", {}).get("tasks", [])):
                            if defined.get("id") == tid:
                                refs[dest].append(f"/{field}/{m}/payload/tasks/{n}")
                for n, record in enumerate(obj.get("received_records", [])):
                    record_task = record.get("data", {}).get("task")
                    # Obstacle records use a task ID string; completion records use a snapshot.
                    record_task_id = record_task.get("id") if isinstance(record_task, dict) else record_task
                    if record_task_id == tid:
                        refs["received_record_evidence"].append(base + f"/received_records/{n}")
                entry["tasks"].append({"task_id": tid, "source": base + f"/tasks/{j}",
                    "visible_snapshot_state": task.get("state", "unknown"), "as_of_round": task.get("as_of_round"),
                    "current_other_actor_actual_state": "unknown", **refs})
            result.append(entry)
    return {"note": "仅索引本次合法观察的材料。空证据列表表示未知；发送不证明对方已收到或承担，历史状态不证明当前实际状态。", "objects": result}


def decorate_observation(raw_obs):
    raw = raw_observation(raw_obs)
    if type(raw.get("actor_id")) is not int or type(raw.get("round")) is not int:
        raise ValueError("Observation needs integer actor_id and round")
    context = _hash(raw)
    candidate_context = _candidate_context(raw)
    options = []
    for index, action in enumerate(raw["available_actions"]):
        fields = {k: deepcopy(action[k]) for k in ("kind", "target", "params")}
        if "blocked_by" in action:
            fields["blocked_by"] = deepcopy(action["blocked_by"])
        # Short copyable label: position is unique within this observation;
        # 64 business-state bits bind actor, round, source versions and actions.
        # The complete SHA-256 remains in the observation and decision trace.
        candidate_id = f"C{index + 1:02d}-{candidate_context[:16]}"
        options.append({"candidate_id": candidate_id, **fields})
    return {**raw, "interface_version": INTERFACE_VERSION, "context_sha256": context,
            "candidate_options": options, "evidence_index": _evidence(raw)}


def decode_candidate_choice(value, observation):
    if not isinstance(value, dict) or set(value) not in ({"candidate_id", "reason"}, {"candidate_id", "reason", "analysis"}):
        raise ValueError("Choice requires candidate_id/reason; only a topic proposal adds analysis")
    if type(value["candidate_id"]) is not str or type(value["reason"]) is not str or len(value["reason"]) > 1000:
        raise ValueError("Invalid candidate_id or reason")
    # Recompute from the current business state, never trust a supplied mapping.
    fresh = decorate_observation(observation)
    for option in fresh["candidate_options"]:
        if option["candidate_id"] == value["candidate_id"]:
            action = {k: deepcopy(option[k]) for k in ("kind", "target", "params")} | {"reason": value["reason"]}
            if option["kind"] == "propose_project":
                action["params"] = validate_topic_parameters(value.get("analysis"), observation)
            elif "analysis" in value:
                raise ValueError("Only a topic proposal accepts analysis")
            return action
    raise ValueError("Unknown or stale candidate_id for this observation")


def validate_topic_parameters(value, observation):
    from .materials import MAX_SOURCES_PER_READ
    if not isinstance(value, dict) or set(value) != {"source_ids", "hypothesis"}:
        raise ValueError("Topic analysis requires exactly source_ids and hypothesis")
    ids, hypothesis = value["source_ids"], value["hypothesis"]
    if (not isinstance(ids, list) or not ids or len(ids) > MAX_SOURCES_PER_READ
            or any(type(s) is not str for s in ids) or len(set(ids)) != len(ids)):
        raise ValueError(f"Topic sources must be at most {MAX_SOURCES_PER_READ} unique source ids")
    if not isinstance(hypothesis, str) or not hypothesis.strip() or len(hypothesis) > 1200:
        raise ValueError("Topic hypothesis must be nonempty bounded text")
    # Availability, actual delivery, time window and grouping are business
    # preconditions. The world checks the trusted delivered context at settlement,
    # returning an exact receipt without granting a free extra model decision.
    return {"source_ids": ids[:], "hypothesis": hypothesis}


def decode_material_read(value, observation):
    from .materials import MAX_READS_PER_TURN
    from .work import MAX_MATERIAL_BATCH
    if not isinstance(value, dict) or set(value) != {"read_materials", "reason"}:
        raise ValueError("Material read requires read_materials and reason")
    ids = value["read_materials"]
    if (not isinstance(ids, list) or not ids or len(ids) > MAX_MATERIAL_BATCH
            or any(type(x) is not str for x in ids) or len(set(ids)) != len(ids)):
        raise ValueError(f"Material read requires at most {MAX_MATERIAL_BATCH} unique source ids per request")
    if not isinstance(value["reason"], str) or len(value["reason"]) > 1000:
        raise ValueError("Invalid material-read reason")
    materials = observation.get("materials", {})
    limit = materials.get("read_limit", MAX_READS_PER_TURN)
    if limit is not None and materials.get("reads_used", 0) >= limit:
        raise ValueError("Material read limit reached; choose a business action")
    allowed = {r["source_id"] for r in materials.get("source_index", [])}
    if not set(ids) <= allowed:
        raise ValueError("Requested material is outside this actor's source index")
    return ids[:]


INSTRUCTION_HELP = ("submit candidate {candidate_id} with reason {reason}",
                    "read_work section {section} offset {offset}",
                    "read_materials source_ids {source_ids} reason {reason}")
_MATERIAL_ID_KEYS = frozenset({"source_id", "source_ids", "read_materials"})


def dispatch_plan(instruction, variables):
    """Translate one actor template ask into its single environment tool call.

    The actor has already made the business decision; the environment never
    re-decides it. The first instruction word selects the operation and typed
    template variables carry the arguments, so the plan is a pure function of
    the recorded ask and the audit recomputes it exactly. Every mismatch
    raises ValueError with corrective guidance for the actor's next call.
    """
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("ask_env requires a nonempty instruction")
    if not isinstance(variables, dict):
        raise ValueError("Template variables must be an object")
    operation = instruction.split(None, 1)[0]
    if operation == "observe":
        if variables:
            raise ValueError("observe takes no variables")
        return "observe", {}
    if operation == "submit":
        if set(variables) not in ({"candidate_id", "reason"}, {"candidate_id", "reason", "analysis"}):
            raise ValueError("submit requires variables candidate_id and reason; "
                             "a propose_project candidate adds analysis={source_ids, hypothesis}")
        if type(variables["candidate_id"]) is not str or type(variables["reason"]) is not str:
            raise ValueError("candidate_id and reason must be strings")
        if "analysis" in variables and type(variables["analysis"]) is not dict:
            raise ValueError("analysis must be an object with source_ids and hypothesis")
        return "submit", dict(variables)
    if operation == "read_work":
        if set(variables) not in ({"section"}, {"section", "offset"}):
            raise ValueError("read_work requires variables section and optional integer offset")
        if type(variables["section"]) is not str:
            raise ValueError("section must be a string")
        if "offset" in variables and type(variables["offset"]) is not int:
            raise ValueError("offset must be an integer")
        return "read_work", {"section": variables["section"], "offset": variables.get("offset", 0)}
    if operation == "read_materials":
        id_keys = set(variables) & _MATERIAL_ID_KEYS
        if len(id_keys) != 1 or not set(variables) <= _MATERIAL_ID_KEYS | {"reason"}:
            raise ValueError("read_materials requires variables source_ids (one source_id "
                             "string or a list) and optional reason")
        value = variables[id_keys.pop()]
        ids = [value] if type(value) is str else value
        if (not isinstance(ids, list) or not ids
                or any(type(source_id) is not str for source_id in ids)):
            raise ValueError("source_ids must be a source_id string or a nonempty list of strings")
        reason = variables.get("reason", "ask_env read_materials")
        if type(reason) is not str:
            raise ValueError("reason must be a string")
        return "read_materials", {"read_materials": ids, "reason": reason}
    raise ValueError("Unsupported instruction; ask_env executes exactly: "
                     + "; ".join(INSTRUCTION_HELP))
