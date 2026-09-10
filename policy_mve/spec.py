"""Frozen synthetic MVE assumptions; these are not Beijing estimates."""

SPEC_VERSION = "policy-mve-1.2"
ACTORS = {1: "受理派单", 2: "供水办理", 3: "基础设施办理", 4: "专项负责人"}
DEFAULT_CONFIG = {
    "q0": 0.0, "q1": 1.0,
    "signal_window": 6, "signal_threshold": 3, "signal_cooldown": 6,
    "project_lag": 2, "project_steps": 2,
    "labor_per_actor": 100.0, "capital": 24.0,
    "decision_cost": 0.1, "route_cost": 0.5, "inspect_cost": 1.0,
    "coordination_cost": 1.0, "work_cost": 1.0,
    "case_work_capital": 0.5, "shared_crew_capacity": 2,
    "project_proposal_cost": 1.0, "project_diagnosis_cost": 2.0,
    "project_work_cost": 2.0, "project_accept_cost": 0.5,
    "project_step_capital": 3.0, "board_cost": 0.5,
    "recommendation_cost": 0.2,
    "shock_probability": 0.10, "common_root_shock_probability": 0.22,
    "repaired_root_shock_probability": 0.025,
    "repeat_report_interval": 4,
}

SOURCE_V2 = "outputs/01a08490-e194-7ea1-a585-319e4cb1a9ef/政策操作化表_V2_状态动作与判定规程.md"
SOURCE_CARDS = "outputs/01a08490-e194-7ea1-a585-319e4cb1a9ef/北京2022优秀案例_案例卡与参数来源_阅读版.md"
PARAMETER_PROVENANCE = {
    name: {
        "value": value, "basis_type": "synthetic_research_assumption",
        "source": SOURCE_V2,
        "locator": "lines 238-247 (parameters require evidence or explicit assumptions)",
        "note": "Exploratory value; not calibrated from Beijing operating data.",
    }
    for name, value in DEFAULT_CONFIG.items()
}
SCENARIO_PROVENANCE = {
    "districts": 4, "facilities_per_district": 3, "initial_issues": 12,
    "horizon": 30,
    "basis_type": "synthetic_design_with_case_informed_constraints",
    "source": SOURCE_CARDS,
    "locator": "lines 5-9, 25-35, 45-55, 64-74, 83-93",
    "note": "Four synthetic archetypes, not four mutually exclusive empirical case classifications.",
}
ALLOWED_KINDS = {
    "wait", "route", "inspect", "request_coordination", "confirm_joint_task", "work",
    "propose_project", "diagnose_project", "implement_project", "accept_project",
}
ACTION_PARAM_KEYS = {
    "wait": set(), "route": {"department", "use_recommendation"},
    "inspect": set(), "request_coordination": {"mode"}, "confirm_joint_task": set(), "work": set(),
    "propose_project": {"mode"}, "diagnose_project": set(),
    "implement_project": {"plan"}, "accept_project": set(),
}
