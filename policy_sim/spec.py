"""Versioned synthetic parameters for the complete V3 mechanism experiment.

Numbers below are research assumptions, not estimates of Beijing operations.
The service capabilities are explicit treatments; their net effect is unknown.
"""

SPEC_VERSION = SCHEMA_VERSION = "policy-v3-3.3"
ACTORS = {1: "受理派单员", 2: "供水办理部门", 3: "基础设施办理部门", 4: "专项负责人"}
# Frozen parameter metadata is retained byte-for-value for original event evidence.
# Resource quotas, incident probabilities, expiry windows, and horizon settings
# do not control this finite-only world; their historical execution paths are removed.
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
    "route": {"department"},
    "inspect": set(),
    "request_coordination": {"mode", "department"},
    "reply_coordination": {"decision"},
    "confirm_joint_task": set(),
    "register_joint_workflow": set(),
    "raise_objection": {"reason_code"},
    "withdraw_joint": set(),
    "query_status": {"department"},
    "reply_status": set(),
    "report_status": {"recipient"},
    "work": set(),
    "propose_project": {"source_ids", "hypothesis"},
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
# Shared public definitions used by the finite actor-facing rules.
PUBLIC_RULES = {'directory': {'2': '供水及机泵作业、供水专业评审', '3': '基础设施及接口作业、工程专业评审', '4': '专项组织、调查、拟案、预算申请和验收申请'}, 'project_template': {'plan': 'replace_shared_main', 'reviews': [2, 3], 'construction': [{'department': 3, 'predecessor_department': None}, {'department': 2, 'predecessor_department': 3}], 'commissioning': {'department': 2, 'prerequisite_construction_departments': [2, 3]}, 'note': 'Public proposed-plan template only; it does not establish a shared defect or a correct intervention.'}}

# Actor-facing business rules for a fixed inventory of complaints.
FINITE_PUBLIC_RULES = {
    "stage_boundaries": "派单依据当前诉求与职责，后续调查揭示具体任务或根因。立项先提出待检验假设，再确认主责和现场诊断；假设不是根因结论。已有材料持续可用。",
    "confirmation_receipts": "本人根据已收到的当前分工确认，不依赖其他参与者先确认。联办登记后，当前分工的确认与异议按正常消息时序送达；全部确认与已送达激活记录仍是后续作业前提。异议不会强制他人服从。",
    "commissioning_workflow": "建成、技术投运、行政验收分列。供水部门收到投运职责及两分项完成回执后，待技术就绪时滞满足，可执行commission_project。投运执行冲洗、检测和切换，工程匹配才物理生效；负责人收到合法投运成功记录后另行行政验收。行政未知或撤项不逆转已生效工程。",
    "directory": PUBLIC_RULES["directory"],
    "case_workflow": "派单后主办部门调查。调查确认跨部门任务时，须联办的事项要登记分工并由参与人确认；必经确认和交接不可绕过。其他事项可人工联系、回复及报告。",
    "project_workflow": "专项负责人立项、确认主责、现场调查及拟案；两部门专业评审；负责人收到意见后申请作业授权；部门按技术前提交接并施工；供水部门收到两分项回执且技术就绪后投运；负责人收到投运成功和必要材料后行政验收。有依据可撤项。",
    "project_template": PUBLIC_RULES["project_template"],
    "evidence_standard": "共同根源拟案须有可核查现场材料；专业意见由部门自主给出，可以错误。作业授权核对意见是否齐备，不认定真实根因。投运核对实际工程匹配；行政验收核对合法收到的投运成功记录及必要材料。",
    "ordinary_channel": "未规定必经联办的事项可通过普通请求和回执完成个案与源头项目。必经联办内可补充联系，但不能退出后绕过确认、职责和交接。",
    "shared_channel": "联办登记支持分工确认、派发及授权回执共享，不生成专业判断。分析材料不能替代联办登记或派工。",
}
