"""Read-only, independent event/record audit. No LLM or framework dependency."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def state_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_world(state):
    """Return failures and independently reconstructed metrics, including replay."""
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    try:
        from .spec import SPEC_VERSION
        if state.get("spec_version") != SPEC_VERSION:
            return {"passed": False, "errors": ["state version differs from active verifier; verify legacy evidence using its archived source snapshot"], "metrics": None}
        events, issues = state["events"], state["issues"]
        tickets, projects, config = state["tickets"], state["projects"], state["config"]
        rounds = state["round"]
        check(0 <= rounds <= state["horizon"], "round outside horizon")
        check([e["event_index"] for e in events] == list(range(len(events))), "event_index not continuous")
        results = [e for e in events if e["kind"] == "action_result"]
        for r in range(rounds):
            check(Counter(e["actor_id"] for e in results if e["round"] == r) == Counter([1, 2, 3, 4]), f"round {r}: not four unique action results")
            ordering = [e for e in events if e["kind"] == "settlement_order" and e["round"] == r]
            actors = [2, 3, 4]
            expected_order = [1] + actors[r % 3:] + actors[:r % 3]
            check(len(ordering) == 1 and ordering[0]["actors"] == expected_order, "settlement rotation mismatch")
            check([e["actor_id"] for e in results if e["round"] == r] == expected_order, "action result order mismatch")
        check(all(0 <= e["round"] < rounds for e in results), "action_result outside completed rounds")
        created = [e for e in events if e["kind"] == "issue_created"]
        resolved_events = [e for e in events if e["kind"] == "issue_resolved"]
        check(Counter(e["issue"] for e in created) == Counter(issues.keys()), "issue_created records differ from issue table")
        resolution = {}
        for e in resolved_events:
            check(e["issue"] not in resolution, "issue resolved more than once: " + e["issue"])
            resolution[e["issue"]] = e["round"] + 1
        for e in created:
            i = issues[e["issue"]]
            check((i["created"], i["initial"], i["facility"]) == (e["round"], e["initial"], e["facility"]), "issue creation metadata mismatch: " + e["issue"])
            check(i["resolved"] == resolution.get(e["issue"]), "issue resolution metadata mismatch: " + e["issue"])
            check(i["resolved"] is None or i["created"] < i["resolved"] <= rounds, "invalid issue lifetime: " + e["issue"])
        for fid in state["facilities"]:
            episodes = sorted((i for i in issues.values() if i["facility"] == fid), key=lambda i: i["created"])
            for earlier, later in zip(episodes, episodes[1:]):
                check(earlier["resolved"] is not None and earlier["resolved"] <= later["created"], "duplicate unresolved facility issue: " + fid)
        initial_ids = [e["issue"] for e in created if e["initial"]]
        check(len(initial_ids) == 12 and len(set(initial_ids)) == 12, "initial queue must contain 12 unique issues")
        check(state["initial_ids"] == initial_ids, "initial_ids differs from created fixed queue")
        check(all(issues[i]["created"] == 0 for i in initial_ids), "initial queue not created at zero")
        # Settlement burden excludes work resolved this round and excludes next-round shocks.
        burden_per_round = [sum(e["round"] <= r and (e["issue"] not in resolution or resolution[e["issue"]] > r + 1) for e in created) for r in range(rounds)]
        burden = sum(burden_per_round)
        check(state["burden"] == burden, "cumulative burden mismatch")
        completed_rounds = [e for e in events if e["kind"] == "round_completed"]
        check([e["completed_round"] for e in completed_rounds] == list(range(1, rounds + 1)), "round completion sequence mismatch")
        for e in completed_rounds:
            check(e["burden"] == sum(burden_per_round[:e["completed_round"]]), "round cumulative burden mismatch")

        spent = [e for e in events if e["kind"] == "resource_spent"]
        labor = {str(actor): 0.0 for actor in (1, 2, 3, 4)}
        capital = 0.0
        for e in spent:
            check(all(isinstance(e[k], (int, float)) and math.isfinite(e[k]) and e[k] >= 0 for k in ("labor", "capital")), "invalid resource consumption")
            labor[str(e["actor_id"])] += e["labor"]
            capital += e["capital"]
            check(labor[str(e["actor_id"])] <= config["labor_per_actor"] + 1e-7, "actor labor overdraw")
            check(capital <= config["capital"] + 1e-7, "capital overdraw")
        for actor, used in labor.items():
            check(state["labor"][actor] >= -1e-7 and abs(config["labor_per_actor"] - used - state["labor"][actor]) < 1e-7, "labor conservation mismatch: " + actor)
        check(state["capital"] >= -1e-7 and abs(config["capital"] - capital - state["capital"]) < 1e-7, "capital conservation mismatch")
        crew_by_round = Counter()
        for e in spent:
            check(isinstance(e["crew"], (int, float)) and math.isfinite(e["crew"]) and e["crew"] >= 0, "invalid crew consumption")
            crew_by_round[e["round"]] += e["crew"]
            check(crew_by_round[e["round"]] <= config["shared_crew_capacity"], "shared crew overdraw")
        # Snapshot is between rounds: advance refreshes the next round's crew pool.
        check(state["crew_remaining"] == config["shared_crew_capacity"], "shared crew conservation mismatch")

        success = [e for e in results if e["status"] == "executed"]
        routed = [e for e in events if e["kind"] == "routed"]
        used_a = {e["ticket"] for e in routed if e["recommendation_used"]}
        used_b = {e["action"]["target"] for e in success if e["action"]["kind"] == "request_coordination" and e["action"]["params"].get("mode") == "joint"}
        confirmations = [e for e in events if e["kind"] == "joint_task_confirmed"]
        activations = [e for e in events if e["kind"] == "joint_board_activated"]
        confirmation_actions = [e for e in success if e["action"]["kind"] == "confirm_joint_task"]
        check(Counter((e["round"], e["actor_id"], e["ticket"]) for e in confirmations) == Counter((e["round"], e["actor_id"], e["action"]["target"]) for e in confirmation_actions), "joint confirmation events differ from successful bound actions")
        check(all(e["ticket"] in used_b for e in confirmations + activations), "confirmation or activation without joint case")
        confirmed_count, fully_confirmed, confirmed_resolved = 0, 0, 0
        for tid in used_b:
            ticket = tickets[tid]
            # Independent participant set from assigned lead and inspected requirements.
            participants = sorted(set([ticket["lead"]] + ticket["known_required"]))
            check(ticket["joint_participants"] == participants, "joint participant set mismatch: " + tid)
            cevents = [e for e in confirmations if e["ticket"] == tid]
            actors = [e["actor_id"] for e in cevents]
            check(len(actors) == len(set(actors)), "duplicate joint confirmation: " + tid)
            check(set(actors).issubset(participants), "nonparticipant joint confirmation: " + tid)
            check(sorted(ticket["joint_confirmed_by"]) == sorted(actors), "joint confirmation checkpoint mismatch: " + tid)
            check(len(ticket["joint_confirmed_by"]) == len(set(ticket["joint_confirmed_by"])), "duplicate checkpoint confirmer: " + tid)
            established = next(e for e in success if e["action"]["kind"] == "request_coordination" and e["action"]["target"] == tid)
            check(all(e["event_index"] > established["event_index"] for e in cevents), "confirmation precedes joint establishment: " + tid)
            aevents = [e for e in activations if e["ticket"] == tid]
            expected_active = set(actors) == set(participants) and bool(participants)
            check(len(aevents) == (1 if expected_active else 0), "joint activation count mismatch: " + tid)
            check(ticket["shared_board"] is expected_active, "joint shared board checkpoint mismatch: " + tid)
            if aevents:
                activated = aevents[0]
                check(activated["participants"] == participants, "activation participants mismatch: " + tid)
                check(bool(cevents) and activated["event_index"] > cevents[-1]["event_index"] and activated["round"] == cevents[-1]["round"], "joint activation does not follow final confirmation: " + tid)
                check(ticket["joint_activated_round"] == activated["round"], "joint activation checkpoint mismatch: " + tid)
            else:
                check(ticket["joint_activated_round"] is None, "unconfirmed joint checkpoint marked active: " + tid)
            # Ordinary work remains legal before all confirmations; only the
            # enhanced shared board is gated, not the underlying repair path.
            confirmed_count += len(cevents)
            fully_confirmed += int(expected_active)
            confirmed_resolved += int(expected_active and ticket["issue"] in resolution)
        proposed = [e for e in events if e["kind"] == "project_proposed"]
        used_c = {e["project"] for e in proposed if e["mode"] == "structured"}
        pcompleted = [e for e in events if e["kind"] == "project_completed"]
        pfailed = [e for e in events if e["kind"] == "project_failed"]
        check(len({e["project"] for e in pcompleted}) == len(pcompleted), "project completed twice")
        for e in pcompleted:
            p = projects[e["project"]]
            check(p["state"] == "completed", "project completion state mismatch")
            steps = [x for x in success if x["action"]["kind"] == "implement_project" and x["action"]["target"] == p["id"]]
            check(len(steps) >= config["project_steps"], "project completed without required construction")
            if steps:
                check(e["round"] >= steps[-1]["round"] + config["project_lag"], "project effect lag violated")
            check(p["ready_round"] is not None and e["round"] >= p["ready_round"], "project ready_round violated")
        check({p["id"] for p in projects.values() if p["state"] == "completed"} == {e["project"] for e in pcompleted}, "completed project table differs from events")
        check({p["id"] for p in projects.values() if p["state"] == "failed"} == {e["project"] for e in pfailed}, "failed project table differs from events")
        process = {}
        for tool, used, completed in (("A", len(used_a), len(used_a)), ("B", len(used_b), sum(tickets[t]["issue"] in resolution for t in used_b)), ("C", len(used_c), sum(e["project"] in used_c for e in pcompleted))):
            opportunities = [e for e in events if e["kind"] == "tool_opportunity" and e["tool"] == tool]
            unique = {e["opportunity"]: e["offered"] for e in opportunities}
            check(len(unique) == len(opportunities), "duplicate tool opportunity: " + tool)
            check(all(type(v) is bool for v in unique.values()), "nonboolean offer: " + tool)
            offered, eligible = sum(unique.values()), len(unique)
            check(0 <= completed <= used <= offered <= eligible, "tool denominator ordering violated: " + tool)
            if tool in ("A", "B"):
                check(all(unique.get(k) is True for k in (used_a if tool == "A" else used_b)), "tool used without eligible offer: " + tool)
            else:
                for proposal in proposed:
                    if proposal["project"] in used_c:
                        candidates = [e for e in opportunities if e["round"] <= proposal["round"] and e["opportunity"].rsplit("@", 1)[0] == proposal["topic"]]
                        check(bool(candidates) and candidates[-1]["offered"] is True, "C used without an offered topic opportunity")
            process[tool] = {"eligible": eligible, "offered": offered, "offer_rate": offered / eligible if eligible else None, "used": used, "use_rate": used / offered if offered else None, "completed": completed, "completion_rate": completed / used if used else None}
        process["A"]["objective_resolved"] = sum(tickets[t]["issue"] in resolution for t in used_a)
        process["B"]["objective_resolved"] = process["B"]["completed"]
        process["B"]["confirmed_participations"] = confirmed_count
        process["B"]["fully_confirmed_cases"] = fully_confirmed
        process["B"]["confirmed_and_resolved"] = confirmed_resolved
        process["C"]["objective_resolved"] = 0
        resolved_initial = sum(i in resolution for i in initial_ids)
        metrics = {"round": rounds, "horizon": state["horizon"], "policy": state["policy"], "seed": state["seed"], "initial_issues": len(initial_ids), "initial_resolved": resolved_initial, "initial_resolution_rate": resolved_initial / len(initial_ids), "initial_censored_mean_time": sum(resolution.get(i, rounds) for i in initial_ids) / len(initial_ids), "unresolved_issues": len(issues) - len(resolution), "cumulative_issue_burden": burden, "new_issues": len(issues) - len(initial_ids), "recurrent_episodes": sum(i["recurrence"] for i in issues.values()), "first_routing_match_rate": sum(e["initially_matched"] for e in routed) / len(routed) if routed else None, "repeat_contacts": sum(e["kind"] == "repeat_contact" for e in events), "projects_completed": len(pcompleted), "projects_failed": len(pfailed), "labor_spent": round(sum(labor.values()), 8), "capital_spent": round(capital, 8), "tool_process": process, "business_rejections": sum(e["status"] == "business_rejected" for e in results), "parameter_basis": "synthetic_uncalibrated"}

        metrics["shared_crew_units_spent"] = sum(crew_by_round.values())
        metrics["tool_process_definitions"] = {
            "A_completed": "accepted routing action using offered recommendation; not objective resolution",
            "B_completed": "all required individual-case tasks verified complete",
            "C_completed": "shared structural intervention independently accepted after lag",
            "objective_resolved": "resolved existing issues among tool users; descriptive, not causal attribution; C changes future risk and directly resolves no local-damage issues",
            "C_prevention": "compare new_issues across paired simulations; never infer prevention from acceptance alone",
        }
        # Separate exact action replay catches state/event corruption beyond metric checks.
        from .core import PolicyWorld
        replay = PolicyWorld(policy=state["policy"], seed=state["seed"], horizon=state["horizon"], config=config)
        submitted = [e for e in events if e["kind"] == "action_submitted"]
        for r in range(rounds + 1):
            for e in submitted:
                if e["round"] == r:
                    receipt = replay.submit(e["actor_id"], e["action"])
                    check(receipt.get("code") == "accepted_for_settlement", "replay submission rejected")
            if r < rounds:
                replay.advance()
        replay_hash, actual_hash = state_hash(replay.export_state()), state_hash(state)
        check(replay_hash == actual_hash, "full state action replay hash mismatch")
        return {"passed": not errors, "errors": errors, "metrics": metrics, "burden_per_round": burden_per_round, "state_sha256": actual_hash, "replay_sha256": replay_hash, "verification_mode": "independent_event_metrics_and_exact_action_replay_no_llm"}
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError) as exc:
        errors.append("malformed evidence: " + str(exc))
        return {"passed": False, "errors": errors, "metrics": None}


def verify_run(run_dir):
    """Read world, metrics and committed hashes without modifying artifacts."""
    run_dir = Path(run_dir).resolve()
    try:
        def read(name):
            return json.loads((run_dir / name).read_text(encoding="utf-8"))
        state, stored, committed = read("world.json"), read("metrics.json"), read("committed.json")
        report = verify_world(state)
        if stored != report["metrics"]:
            report["errors"].append("metrics.json differs from independent metrics")
        if committed.get("round") != state["round"] or committed.get("world_sha256") != state_hash(state):
            report["errors"].append("committed round/world hash mismatch")
        files = committed.get("files", {})
        if not isinstance(files, dict) or not {"world.json", "metrics.json"}.issubset(files):
            report["errors"].append("committed manifest missing world/metrics hashes")
        else:
            for name, expected in files.items():
                path = (run_dir / name).resolve()
                if not path.is_relative_to(run_dir):
                    report["errors"].append("manifest path escapes run directory")
                    continue
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    report["errors"].append("committed file hash mismatch: " + name)
        report["passed"] = not report["errors"]
        return report
    except (OSError, ValueError, TypeError) as exc:
        return {"passed": False, "errors": ["cannot read run evidence: " + str(exc)]}
