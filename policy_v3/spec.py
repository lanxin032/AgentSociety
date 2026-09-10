"""Versioned synthetic parameters for the complete V3 mechanism experiment.

Numbers below are research assumptions, not estimates of Beijing operations.
The service capabilities are explicit treatments; their net effect is unknown.
"""

SPEC_VERSION = SCHEMA_VERSION = "policy-v3-3.1"
ACTORS = {1: "受理派单员", 2: "供水办理部门", 3: "基础设施办理部门", 4: "专项负责人"}
DEFAULT_CONFIG = {
    "labor_per_actor": 100.0, "capital": 24.0, "shared_crew_capacity": 2,
    "decision_cost": 0.1, "route_cost": 0.5, "inspect_cost": 1.0,
    "work_cost": 1.0, "case_work_capital": 0.5,
    "communication_cost": 0.2, "review_cost": 0.5,
    "setup_cost": 0.5, "maintenance_cost": 0.1,
    "project_proposal_cost": 1.0, "project_diagnosis_cost": 2.0,
    "project_work_cost": 2.0, "project_accept_cost": 0.0,
    "project_commission_cost": 0.5,
    "project_step_capital": 3.0, "project_steps": 2, "project_lag": 2,
    "recommendation_cost": 0.2,
    "signal_window": 6, "signal_threshold": 3, "signal_cooldown": 6,
    "repeat_report_interval": 4,
    "shock_probability": 0.10, "common_root_shock_probability": 0.22,
    "repaired_root_shock_probability": 0.025,
    "zero_communication_friction": False, "fewer_shared_roots": False,
}
ENVIRONMENTS = {
    "baseline": {},
    "zero_communication_friction": {"zero_communication_friction": True},
    "tight_resources": {"labor_per_actor": 50.0, "capital": 12.0, "shared_crew_capacity": 1},
    "weak_slow_repair": {"repaired_root_shock_probability": 0.10, "project_lag": 6},
    "fewer_shared_roots": {"fewer_shared_roots": True},
}
COMMUNICATION_KINDS = {
    "reply_coordination", "query_status", "reply_status", "report_status",
    "request_review", "request_project_work",
}
ACTION_PARAM_KEYS = {
    "wait": set(),
    "route": {"department", "use_recommendation"},
    "inspect": set(),
    "request_coordination": {"mode", "department"},
    "reply_coordination": {"decision"},
    "confirm_joint_task": set(),
    "raise_objection": {"reason_code"},
    "withdraw_joint": set(),
    "query_status": {"department"},
    "reply_status": set(),
    "report_status": {"recipient"},
    "work": set(),
    "propose_project": {"mode"},
    "confirm_project_lead": set(),
    "diagnose_project": set(),
    "draft_plan": {"plan", "budget"},
    "request_review": {"department"},
    "confirm_project_task": set(),
    "review_project": {"opinion"},
    "request_budget": set(),
    "request_project_work": {"department"},
    "implement_project": set(),
    "commission_project": set(),
    "cancel_project": {"reason_code"},
    "adjust_project": {"decision", "reason_code"},
    "accept_project": set(),
}
ALLOWED_KINDS = set(ACTION_PARAM_KEYS)
SOURCE_V2 = "outputs/01a08490-e194-7ea1-a585-319e4cb1a9ef/政策操作化表_V2_状态动作与判定规程.md"
PARAMETER_PROVENANCE = {
    name: {"value": value, "basis_type": "synthetic_research_assumption",
           "source": SOURCE_V2, "locator": "B lines 85-100; C lines 102-119; calibration lines 238-247",
           "note": "Prespecified V3 mechanism assumption; not an empirical Beijing estimate."}
    for name, value in DEFAULT_CONFIG.items()
}
for _name in ("project_commission_cost", "project_accept_cost", "project_lag"):
    PARAMETER_PROVENANCE[_name].update({
        "source": "research/v3_20260910_revision/state_transition_proposal.md",
        "locator": "推荐状态表；需要裁决的三项及默认建议",
        "note": "Exploratory V3.1: transfer technical labor0.5 to role2, administrative technical labor0; existing decision0.1 remains per action. Lag2 is synthetic pre-commission readiness, not calibrated from calendar dates."})
PUBLIC_RULES = {
    "commissioning_cost_basis": "旧验收技术劳动0.5转为部门2投运劳动；行政验收不重复收0.5，仍收每动作决策劳动0.1。新增一步占行动机会及0.1决策劳动；成本承担者改变，不声称总负担完全不变。投运暂不新增资本及施工队占用，属于最小合成假设。",
    "commissioning_workflow": "建成、技术投运、行政验收分列。供水角色2收到施工派工包中的投运职责及两分项完成回执后，待技术就绪时滞满足，可主动执行commission_project。投运执行冲洗/检测/切换的合成技术工序，正确工程才物理生效；负责人4收到合法投运成功记录后另行行政验收。行政未知或撤项不逆转已生效工程。角色2职责及成本为未校准假设。普通与强化物理条件相同，任务全局生成不等于本人收到分派。",
    "directory": {"2": "供水及机泵作业、供水专业评审", "3": "基础设施及接口作业、工程专业评审", "4": "专项组织、调查、拟案、预算申请和验收申请"},
    "case_workflow": "派单后主办部门调查；普通联系、回复和进度报告合法可用。联合清单需本人确认才激活共享；未确认仍可依法普通办理。作业依赖与资源对所有流程相同，技术交接须有已送达的合法完成回执。",
    "project_workflow": "专项负责人自愿立项、确认主责、现场调查及拟案；部门2和3作专业评审；负责人收到意见后申请预算；部门执行两个施工分项，按技术前提交接；部门2收到两分项回执且技术就绪时滞满足后，可执行独立投运工序；负责人收到投运成功和其他必要材料后申请行政验收。有依据可撤项，已耗资源不退；行政撤项不逆转已投运物理效果。",
    "project_template": {
        "plan": "replace_shared_main", "reviews": [2, 3],
        "construction": [{"department": 3, "predecessor_department": None}, {"department": 2, "predecessor_department": 3}],
        "commissioning": {"department": 2, "prerequisite_construction_departments": [2, 3]},
        "note": "Public proposed-plan template only; it does not establish a shared defect or a correct intervention.",
    },
    "evidence_standard": "共同根源拟案须有可核查现场材料；专业意见由部门自主给出，可以错误。预算只审查申请数额、意见是否齐备与当前资金，不认定真实根因。投运执行时环境核对实际工程匹配；行政验收只核对合法收到的本项目投运成功记录及材料，不重新改变物理效果。",
    "ordinary_channel": "普通流程可分别联系、取得反馈、完成协调和源头项目，不丧失法定办理能力。",
    "shared_channel": "联合/专项支持可归集已有授权记录、本人确认及同步执行回执；需要建立和维护成本，不生成专业判断、不保证更新成功或提高物理成功率。",
}
