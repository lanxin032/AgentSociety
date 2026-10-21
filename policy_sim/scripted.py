"""Transparent fixture controller using only the supplied lawful observation.

Its deliberate service uptake tests paths; it is never an autonomous-model result.
"""
from copy import deepcopy


def scripted_action(observation):
    actions = observation["available_actions"]
    actor = observation["actor_id"]
    def choose(kind, target=None, **params):
        items = [a for a in actions if a["kind"] == kind and (target is None or a["target"] == target)
                 and all(a["params"].get(k) == v for k, v in params.items())]
        return deepcopy(min(items, key=lambda a: (str(a["target"]), str(a["params"])))) if items else None
    wait = choose("wait")
    materials = observation.get("materials", {})
    if actor == 1:
        pending = sorted((t for t in observation["visible_tickets"] if t["lead"] is None and not t["closed"]), key=lambda t: (t["reported"], t["id"]))
        if not pending:
            return wait
        ticket = pending[0]
        packet = next((p for p in materials.get("analyses", []) if p["service"] == "A" and p["target"] == ticket["id"]), None)
        if packet:
            return choose("route", ticket["id"], department=packet["payload"]["candidates"][0]) or wait
        raw = next((r["data"] for r in materials.get("raw", []) if r["source_id"] == ticket["source_id"]), {})
        department = 3 if "接口破损" in raw.get("text", "") else 2
        return choose("route", ticket["id"], department=department) or wait

    projects = observation.get("projects", [])
    object_views = {obj["id"]: obj for obj in observation.get("visible_tickets", []) + projects}
    zero = observation.get("zero_communication_friction", False)
    sent = observation.get("sent_messages", [])
    def sent_records(oid, recipient):
        return {r["id"] for message in sent if message["object"] == oid and message["recipient"] == recipient for r in message.get("payload", {}).get("records", [])}
    def report_pending():
        possibilities = []
        for oid, obj in object_views.items():
            records = obj.get("received_records", [])
            own = [r for r in records if r["author"] == actor and r["kind"] in ("task_completed", "review_completed", "commissioning_result", "capacity_obstacle", "issue_closed", "project_terminal")]
            if not own:
                continue
            # A complete received activation record proves service availability.
            active = any(r["kind"] in ("joint_activation", "project_activation") for r in records)
            if active or zero:
                continue
            for candidate in actions:
                if candidate["kind"] != "report_status" or candidate["target"] != oid:
                    continue
                recipient = candidate["params"]["recipient"]
                if any(r["id"] not in sent_records(oid, recipient) for r in own):
                    # Send a technical handoff to a dependent worker before owner aggregation.
                    tasks = obj.get("tasks", [])
                    completed_tasks = {r["data"]["task"]["id"] for r in own
                                       if r["kind"] == "task_completed" and isinstance(r["data"].get("task"), dict)}
                    dependent = any(t["actor"] == recipient and any(p in completed_tasks for p in t["prerequisites"]) for t in tasks)
                    possibilities.append((0 if dependent else 1 if recipient == 4 else 2, oid, candidate))
        return deepcopy(min(possibilities, key=lambda r: (r[0], r[1], r[2]["params"]["recipient"]))[2]) if possibilities else None

    if actor in (2, 3):
        for project in sorted(projects, key=lambda p: p["id"]):
            confirmation = choose("confirm_project_task", project["id"])
            if confirmation:
                return confirmation
            evidence = project.get("evidence", [])
            shared = len(evidence) >= 3 and len({e["observed_asset"] for e in evidence}) == 1 and all(e["defect_observed"] for e in evidence)
            for task in project.get("tasks", []):
                if task["actor"] == actor and task["kind"] == "review_project" and task["state"] == "pending":
                    option = choose("review_project", task["id"], opinion="approve" if shared else "reject")
                    if option:
                        return option
        for oid, obj in sorted(object_views.items()):
            views = {t["id"]: t for t in obj.get("tasks", [])}
            for task in views.values():
                if task["actor"] == actor and task["kind"] == "implement_project" and task["state"] == "pending" and all(views.get(p, {}).get("state") == "completed" for p in task["prerequisites"]):
                    option = choose("implement_project", task["id"])
                    if option:
                        return option
        for project in sorted(projects, key=lambda p: p["id"]):
            views = {t["id"]: t for t in project.get("tasks", [])}
            for task in views.values():
                if task["actor"] != actor or task["kind"] != "commission_project" or task["state"] != "pending":
                    continue
                completed = [views.get(p, {}) for p in task["prerequisites"]]
                if len(completed) == 2 and all(t.get("state") == "completed" for t in completed):
                    ready = max(t["completed_round"] for t in completed) + observation["public_rules"]["project_lag"]
                    if observation["round"] >= ready:
                        option = choose("commission_project", task["id"])
                        if option:
                            return option
        confirmation = choose("confirm_joint_task")
        if confirmation:
            return confirmation
        reporting = report_pending()
        if reporting:
            return reporting
        replying = choose("reply_coordination", decision="accept")
        if replying:
            return replying
        for ticket in sorted(observation["visible_tickets"], key=lambda t: (t["reported"], t["id"])):
            views = {t["id"]: t for t in ticket.get("tasks", [])}
            for task in views.values():
                if task["actor"] == actor and task["kind"] == "work" and task["state"] == "pending" and all(views.get(p, {}).get("state") == "completed" for p in task["prerequisites"]):
                    option = choose("work", task["id"])
                    if option:
                        return option
            joint = choose("register_joint_workflow", ticket["id"])
            if joint:
                return joint
            ordinary = choose("request_coordination", ticket["id"], mode="conventional")
            already_requested = any(m["object"] == ticket["id"] and m["kind"] == "case_assignment" for m in sent)
            if ordinary and not already_requested:
                return ordinary
        reply = choose("reply_status")
        if reply:
            return reply
        inspection = choose("inspect")
        if inspection:
            return inspection
        return wait

    if actor == 4:
        for project in sorted(projects, key=lambda p: p["id"]):
            pid, state = project["id"], project.get("state")
            if state in ("cancelled", "completed", "failed"):
                continue
            registration = choose("register_joint_workflow", pid)
            if registration:
                return registration
            if state == "proposed":
                return choose("confirm_project_lead", pid) or wait
            if state == "lead_confirmed":
                return choose("diagnose_project", pid) or wait
            evidence = project.get("evidence", [])
            shared = len(evidence) >= 3 and len({e["observed_asset"] for e in evidence}) == 1 and all(e["defect_observed"] for e in evidence)
            if state == "diagnosed":
                return (choose("draft_plan", pid) if shared else choose("cancel_project", pid, reason_code="evidence_does_not_support")) or wait
            if state in ("planned", "under_review"):
                reviews = project.get("received_reviews", {})
                if any(opinion != "approve" for opinion in reviews.values()):
                    return choose("cancel_project", pid, reason_code="evidence_does_not_support") or wait
                if set(map(int, reviews)) == {2, 3}:
                    if project["budget_requested"] > observation["resources"]["capital"]:
                        return choose("cancel_project", pid, reason_code="budget_or_capacity_infeasible") or wait
                    return choose("request_budget", pid) or wait
                requested = project.get("requested", {}).get("review_project", [])
                for department in (2, 3):
                    if department not in requested:
                        request = choose("request_review", pid, department=department)
                        if request:
                            return request
                return wait
            if state in ("approved", "building", "awaiting_commissioning", "awaiting_acceptance", "commissioning_failed"):
                requested = project.get("requested", {}).get("implement_project", [])
                for department in (3, 2):
                    if department not in requested:
                        request = choose("request_project_work", pid, department=department)
                        if request:
                            return request
                successes = [r for r in project.get("received_records", []) if r["kind"] == "commissioning_result"
                             and r["data"].get("revision") == project["revision"] and r["data"].get("success") is True]
                if successes and observation["round"] >= successes[-1]["data"]["effective_at"]:
                    return choose("accept_project", pid) or wait
                return wait
        proposal = choose("propose_project")
        if proposal:
            groups = {}
            for packet in materials.get("analyses", []):
                if packet["service"] == "C":
                    groups.update({t["id"]: {"ids": t["source_ids"], "episodes": t["record_count"],
                                               "hypothesis": t["hypothesis"]} for t in packet["payload"]["topics"]})
            # Manual fixture analysis uses only default-delivered raw sources.
            # It is deliberately outside observe()/candidate generation.
            raw_groups = {}
            for row in materials.get("raw", []):
                if row["kind"] != "contact" or row["created_round"] < materials["window_start"]:
                    continue
                data = row["data"]
                key = data["district"] + "|" + data["category"]
                group = raw_groups.setdefault(key, {"ids": [], "episodes": set()})
                group["ids"].append(row["source_id"])
                group["episodes"].add(data["public_episode"])
            for key, group in raw_groups.items():
                groups.setdefault(key, {"ids": group["ids"], "episodes": len(group["episodes"]),
                                         "hypothesis": "同片区同类诉求，申请调查共同因素。"})
            rules = observation["public_rules"]["topic_analysis"]
            for key, group in sorted(groups.items()):
                if group["episodes"] < rules["minimum_distinct_episodes"]:
                    continue
                same = [p for p in projects if p["topic"] == key]
                if any(p.get("state") not in ("cancelled", "completed", "failed") for p in same):
                    continue
                terminal = [r["created_round"] for p in same for r in p.get("received_records", []) if r["kind"] == "project_terminal"]
                if terminal and observation["round"] < max(terminal) + rules["cooldown_rounds"]:
                    continue
                result = deepcopy(proposal)
                result["params"] = {"source_ids": group["ids"][:], "hypothesis": group["hypothesis"]}
                return result
    return wait
def finite_witness_action(observation):
    """Offline existence witness only; real LLM execution never calls this.

    This offline oracle operates on permissioned observations. Finite
    work has no financial gate and old investigations remain visible indefinitely.
    """
    from copy import deepcopy
    obs = deepcopy(observation)
    if obs['actor_id'] == 4:
        for project in obs['projects']:
            if (project.get('state') in ('planned', 'under_review')
                    and project.get('received_reviews') == {2: 'approve', 3: 'approve'}):
                return next(action for action in obs['available_actions']
                            if action['kind'] == 'request_budget' and action['target'] == project['id'])
        done = {project['topic'] for project in obs['projects']
                if project.get('state') in ('cancelled', 'completed', 'failed')}
        for packet in obs['materials'].get('analyses', []):
            if packet['service'] == 'C':
                packet['payload']['topics'] = [topic for topic in packet['payload']['topics']
                    if topic['id'] not in done]
        obs['materials']['raw'] = [row for row in obs['materials']['raw'] if row['kind'] != 'contact'
            or row['data']['district'] + '|' + row['data']['category'] not in done]
    return scripted_action(obs)
