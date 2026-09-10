"""Pure presentation of one authorized observation; no world or history access."""
from copy import deepcopy
import hashlib
import json

INTERFACE_VERSION = "v3.1-candidate-id-1"
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
    options = []
    for index, action in enumerate(raw["available_actions"]):
        fields = {k: deepcopy(action.get(k)) for k in ("kind", "target", "params")}
        candidate_id = "candidate-" + _hash({"context": context, "index": index, "action": fields})
        options.append({"candidate_id": candidate_id, **fields})
    return {**raw, "interface_version": INTERFACE_VERSION, "context_sha256": context,
            "candidate_options": options, "evidence_index": _evidence(raw)}


def decode_candidate_choice(value, observation):
    if not isinstance(value, dict) or set(value) != {"candidate_id", "reason"}:
        raise ValueError("Choice must contain exactly candidate_id and reason")
    if type(value["candidate_id"]) is not str or type(value["reason"]) is not str or len(value["reason"]) > 1000:
        raise ValueError("Invalid candidate_id or reason")
    # Recompute from the entire raw context, never trust a supplied mapping.
    fresh = decorate_observation(observation)
    for option in fresh["candidate_options"]:
        if option["candidate_id"] == value["candidate_id"]:
            return {k: deepcopy(option[k]) for k in ("kind", "target", "params")} | {"reason": value["reason"]}
    raise ValueError("Unknown or stale candidate_id for this observation")
