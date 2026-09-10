"""Project construction, physical effects and administrative termination.

Instances are short-lived views over one project's existing dictionaries, never
checkpoint state. Records are published synchronously: receiving a record can
change the owner's lawful knowledge before the next lifecycle event is emitted.
The independent event auditor deliberately does not use this implementation.
"""
from copy import deepcopy


def activate_due_projects(projects, facilities, round_number, log):
    """Apply due physical effects without assembling unrelated project tasks."""
    for project in projects:
        if project["physical"] == "commissioned_pending_effect" and project["effective_at"] <= round_number:
            project["physical"] = "effective"
            for fid in project["facilities"]:
                facilities[fid]["root_repaired"] = True
            log("physical_effect_activated", project=project["id"], facilities=project["facilities"],
                effective_at=project["effective_at"], revision=project["revision"])


class ProjectLifecycle:
    def __init__(self, project, tasks, round, lag, *, pay, record, log,
                 task_view, close_topic):
        self.project = project
        self.tasks = tasks
        self.round = round
        self.lag = lag
        self.pay = pay
        self.record = record
        self.log = log
        self.task_view = task_view
        self.close_topic = close_topic

    def _construction(self):
        return [t for t in self.tasks.values()
                if t["revision"] == self.project["revision"]
                and t["kind"] == "implement_project"]

    def complete_construction(self, actor, task, capital, received_tasks):
        """Commit already paid construction, preserving receipt/event order."""
        project, pid = self.project, self.project["id"]
        project["construction"] = "in_progress"
        project["capital_spent"] = round(project["capital_spent"] + capital, 8)
        task["state"], task["completed_round"] = "completed", self.round
        received_tasks[task["id"]] = self.task_view(task)
        self.record(pid, actor, "task_completed", {"task": self.task_view(task), "capital_spent": capital})
        self.log("task_completed", task=task["id"], object=pid, actor_id=actor,
                 task_kind=task["kind"], opinion=task["opinion"])
        if all(t["state"] == "completed" for t in self._construction()):
            # Physical completion stays private until its receipts are received.
            project["construction"], project["built_at"] = "built", self.round
            project["physical_ready_round"] = self.round + self.lag
            self.log("project_built", project=pid, built_at=self.round, revision=project["revision"])
        return True, "work_completed"

    def receive_owner_record(self, record, received_tasks, received_records):
        """Advance the owner's stage only from the delivered revision's facts."""
        project, view = self.project, record["data"]["task"]
        if view["revision"] != project["revision"] or project["state"] in ("completed", "failed", "cancelled"):
            return
        if view["kind"] == "implement_project":
            construction = [v for v in received_tasks.values()
                            if v["object"] == project["id"] and v["revision"] == project["revision"]
                            and v["kind"] == "implement_project"]
            known_commission = [r for r in received_records
                                if r["kind"] == "commissioning_result"
                                and r["data"]["revision"] == project["revision"]]
            project["state"] = ("awaiting_acceptance" if known_commission[-1]["data"]["success"] else "commissioning_failed") if known_commission else "building"
            if len(construction) == 2 and all(v["state"] == "completed" for v in construction):
                project["ready_round"] = max(v["completed_round"] for v in construction) + self.lag
                if not known_commission:
                    project["state"] = "awaiting_commissioning"
        if record["kind"] == "commissioning_result":
            project["state"] = "awaiting_acceptance" if record["data"]["success"] else "commissioning_failed"

    def commission(self, actor, task, received_tasks, facilities, cost):
        project = self.project
        if actor != 2 or project["budget_approved"] is None:
            return False, "commissioning_authorization_missing"
        for prerequisite in task["prerequisites"]:
            received = received_tasks.get(prerequisite)
            if self.tasks[prerequisite]["state"] != "completed" or not received or received["state"] != "completed":
                return False, "prerequisites_or_received_handoff_missing"
        ready = max(self.tasks[t]["completed_round"] for t in task["prerequisites"]) + self.lag
        if self.round < ready:
            return False, "commissioning_readiness_lag_not_elapsed"
        if not self.pay(actor, cost, reason="commission_project", oid=project["id"]):
            self.record(project["id"], actor, "capacity_obstacle", {"task": task["id"], "reason": "insufficient_commissioning_labor", "as_of_round": self.round})
            return False, "insufficient_commissioning_labor"
        matching = (len(facilities) >= 3 and len({f["root"] for f in facilities}) == 1
                    and all(f["shared_root"] and not f["root_repaired"] for f in facilities))
        task["state"], task["completed_round"] = "completed", self.round
        project["commissioned_at"] = self.round
        project["physical"] = "commissioned_pending_effect" if matching else "commissioning_failed"
        project["effective_at"] = self.round + 1 if matching else None
        data = {"task": self.task_view(task), "revision": project["revision"], "success": matching,
                "effective_at": project["effective_at"], "commissioned_at": self.round,
                "code": "technical_commissioning_succeeded" if matching else "physical_intervention_not_matched"}
        project["commissioning_assessment"] = deepcopy(data)
        self.record(project["id"], actor, "commissioning_result", data)
        self.log("project_commissioned" if matching else "project_commissioning_failed", project=project["id"],
                 task=task["id"], revision=project["revision"], effective_at=project["effective_at"],
                 commissioned_at=self.round, success=matching, facilities=project["facilities"])
        return matching, data["code"]

    def accept(self, received_records, received_tasks, received_reviews, cost):
        project, pid = self.project, self.project["id"]
        successes = [r for r in received_records if r["kind"] == "commissioning_result"
                     and r["data"]["revision"] == project["revision"] and r["data"]["success"]]
        if not successes:
            return False, "commissioning_success_receipt_not_received"
        expected = self._construction()
        if project["budget_approved"] is None or received_reviews != {2: "approve", 3: "approve"} or len(expected) != 2 or not all(received_tasks.get(t["id"], {}).get("state") == "completed" for t in expected):
            return False, "administrative_documentation_incomplete"
        if self.round < successes[-1]["data"]["effective_at"]:
            return False, "commissioning_effect_boundary_not_reached"
        if not self.pay(4, cost, reason="accept_project", oid=pid):
            return False, "insufficient_acceptance_labor"
        project["accepted_at"] = self.round
        self.terminate("completed")
        self.log("project_completed", project=pid, facilities=project["facilities"],
                 accepted_at=self.round, effective_at=project["effective_at"], source="administrative_verification")
        return True, "administrative_acceptance_recorded_without_physical_change"

    def terminate(self, state):
        project = self.project
        project["state"] = state
        project["administrative"] = "accepted" if state == "completed" else state
        if state == "cancelled":
            project["cancelled_at"] = self.round
        self.close_topic(project["topic"], self.round)
        for task in self.tasks.values():
            if task["state"] == "pending":
                task["state"] = "cancelled"
        self.record(project["id"], 4, "project_terminal", {"state": state})
