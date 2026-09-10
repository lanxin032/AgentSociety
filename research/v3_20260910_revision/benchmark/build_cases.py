"""Build six frozen-observation fixtures without importing any project runtime.

This standard-library-only extractor reads saved observations/decision inputs,
never world.json, and makes no network or model calls. Existing unequal outputs
are refused. Run with --check to verify without writing any file.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = "runs/v3-autonomous-diagnostic-20260909"
VERSION = "v3-action-comprehension-benchmark-20260910-1.0"
STATUS = "offline_prepared_not_model_tested"
RUN_PREFIX = "v3_diagnostic_s1001_r0_diagnostic_"
CONFIG = [
    ("C01", "调查形成任务定义与向他人派工的区别", "A0_B1_C0", 5, 3, 23, 6),
    ("C02", "空状态回复能够证明与不能证明的内容", "A0_B1_C0", 7, 3, 31, 8),
    ("C03", "本人施工完成后的报告与查询语义", "A0_B0_C1", 13, 2, 53, 14),
    ("C04", "本人专项确认与他人确认的知识边界", "A0_B0_C1", 8, 2, 33, 9),
    ("C05", "负责人已知阶段与未获知的物理进度", "A0_B0_C1", 29, 4, 120, 32),
    ("C06", "已派单对象与当前候选集合的区别", "A0_B0_C0", 18, 1, 73, 19),
]
FROZEN_HASHES = {
    "A0_B1_C0/observations.jsonl": "fc25d256c2e6fa8d95252475c7deb95e8c37a82f2c5ddab769bd410f42c4fddb",
    "A0_B1_C0/agents/agent_0003/decisions.jsonl": "e5b61aeee1975414f8d6f805892e73edc909d957ed25e56cf6389258fcfdff04",
    "A0_B0_C1/observations.jsonl": "9bbc2024fab7ff5313cb1030b01e0d4801c394d60a760620f562fb5294932a5e",
    "A0_B0_C1/agents/agent_0002/decisions.jsonl": "4a31f37f6ed18371031a6431c40434f178c31caab87593ec284ef459d95b8713",
    "A0_B0_C1/agents/agent_0004/decisions.jsonl": "b73fc8f01f21c1c8f87da240aaee4404f2b133b1e9c2bc5845451be2a0fdbbd5",
    "A0_B0_C0/observations.jsonl": "e64de3c19683c09c29bd80cfdb0b3c65dde2bf7a2e7c5d60099d4d0af29bd7a3",
    "A0_B0_C0/agents/agent_0001/decisions.jsonl": "dc6f877c27295b9d2ceb59719d521df1a3cfd4906f4f1e9dc1b54bbaef102e52",
}

CLARIFICATION = """以下是同一套既有接口的公共释义，不补充任何个案状态，不改变动作、权限、时序、费用或成功条件，也不要求采用任何特定通道。

一、观察和动作边界
1. available_actions列出本轮允许提交的候选。复制其kind、target、params，只另写reason；类型也须一致。工单或项目仍在观察列表中，不表示任意针对它的动作都可提交。候选资格不保证结算成功；实际执行仍核对前提和资源。
2. tasks中的actor表示任务的责任角色，pending表示本观察中该任务尚无完成状态；调查得到的任务定义不单独证明已经向其他角色发送任务、对方已经收到或已经开工。只有本人可见的发送记录、已送达消息和相关回执才能支持对应判断。
3. 已持有记录不等于所有参与者都已持有。没有收到完成回执时，不能仅由pending、approved或等待时间断言他人实际未完成或已经完成。as_of_round表示所见任务视图的时点；负责人state表示其依法已知的组织阶段。
4. 本次动作提交返回queued不等于执行成功。last_receipt显示本人上一已结算动作的结果；项目验收成功也不能由拟案、意见或施工申请代替。未获知的信息可以明确回答无法判断。

二、各类动作的既有含义
wait：本轮不发起新业务动作；不表示所有事项结束。
route：把尚可派单的工单派给所选主办部门。use_recommendation表示是否采用已提供的推荐，推荐不是隐藏正确答案。
inspect：主办调查并形成其可见的任务定义与调查记录，办理本部门任务仍须另选work。一般通信环境下，调查本身不向其他部门派发任务；无通信摩擦环境另按观察中的规则被动通信。
request_coordination（conventional）：向指定必要部门发送普通任务联系及分派材料。
request_coordination（joint）：申请联合任务流程并发送邀请及任务材料，需参与者本人确认才能激活相应共享；邀请不代替本人确认或实际作业。
reply_coordination：对已收到的普通联系作接受或拒绝回复；回复不是实际作业完成。
confirm_joint_task / confirm_project_task：记录本人对联合任务或专项任务的确认，不代替另一参与者的确认，不等于专业意见、施工完成或验收。
raise_objection / withdraw_joint：提出范围或容量异议，或按权限退出联合流程；不虚构业务完成，不自动退还已耗资源。
query_status：向指定对象成员询问进展，查询消息本身不附发询问者的任务定义或完成记录。
report_status：主动向指定对象成员发送本人已持有的该对象合法记录；它不产生新事实，也不等同于另外发起任务分派。
reply_status：回复收到的查询，返回本人已持有的对应对象记录。空记录回复只说明该回复未提供这些记录，不能证明物理进度。
work：执行已分配给本人且满足技术交接与资源前提的个案任务，支付真实作业费用。
propose_project（conventional / structured）：分别经普通或专项支持通道提出项目；两者都不保证选题、方案或最终效果正确。
confirm_project_lead：由负责人确认承担主责，不等同于部门评审或施工。
diagnose_project：付出调查资源取得现场材料，不等同于方案批准。
draft_plan：提出方案、预算请求和任务模板；模板不是部门已经发表的意见。
request_review / request_project_work：按权限向部门发送评审或施工任务请求及材料，发送不等于相关任务完成。
review_project：部门依据本人已收到的材料提出approve、revise或reject意见，意见可能错误，不代替物理验收。
request_budget：依据已收到的意见申请预算上限；获批不预留共享资金或施工容量，不保证物理适配。
implement_project：本人执行获授权的施工分项；仍须合法收到技术前置回执并付出作业、工程资金和班组资源。
adjust_project / cancel_project：在权限及依据允许时暂停、恢复或撤项；不会凭空增加资源或返还已耗成本。
accept_project：负责人申请核验；仍需合法取得完成回执、满足技术时滞与资源条件，再核验物理条件。该候选出现不代表条件已全部满足。

三、同等保留选择空间
普通联系、主动报告、查询回复、联合或专项支持以及等待各有含义和代价。适用、提供、采用、执行和完成是不同事件。上述释义没有规定本轮最佳动作，不要求增加联合或专项采用率，也不替任何角色确认、评审、报告或施工。
"""

UNDERSTANDING_SYSTEM = """你正在完成冻结业务观察的接口理解题，不是在执行仿真，也不需要选择本轮业务行动。
只使用给定observation、recent_history及公共规则说明；区分本人已知信息、接口规则与无法从观察确定的事项。
每题选择一个选项键。不要假设未送达的信息，不读取文件，不执行动作，不以是否采用某类工具作为答题标准。
仅返回JSON对象，格式为{"answers":{"题目ID":"选项键"}}，不添加解释或其他字段。
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def canon_sha(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def select_index(rows, **fields):
    indices = [i for i, row in enumerate(rows) if all(row.get(k) == v for k, v in fields.items())]
    if len(indices) != 1:
        raise ValueError(f"Expected unique visible record: {fields}")
    return indices[0]


def evidence(pointer, explanation):
    return {"pointer": pointer, "explanation": explanation}


def question(identifier, prompt, options, answer, *sources):
    if answer not in options:
        raise ValueError("Answer is not an option")
    return {"id": identifier, "prompt": prompt, "options": options, "answer_key": answer, "evidence": list(sources)}


def questions(case_id, obs):
    if case_id in {"C01", "C02"}:
        ti = select_index(obs["visible_tickets"], id="T:F4-3:0")
        tp = f"/observation/visible_tickets/{ti}"
        if obs["visible_tickets"][ti]["tasks"][0]["actor"] != 2:
            raise ValueError("Frozen task changed")
    if case_id in {"C03", "C04", "C05"}:
        pi = select_index(obs["projects"], id="P:1")
        pp = f"/observation/projects/{pi}"
    if case_id == "C01":
        assert obs["last_receipt"]["code"] == "inspection_revealed_local_task_plan" and not obs["sent_messages"]
        return [question("C01_Q1", "观察中的T:F4-3:0任务列actor=2、state=pending。仅据这些字段和当前记录，哪项判断成立？", {
            "A": "部门2的任务已完成。", "B": "部门2已收到派工并确认承接。", "C": "已知任务责任角色，但不能据此证明部门2已收到或承接派工。", "D": "此工单不再存在协调需要。"}, "C",
            evidence(tp + "/tasks/0", "可见的是责任角色和本地pending任务视图，不含对方接收或承接证据。"),
            evidence("/observation/last_receipt", "上次执行结果是调查形成本地任务计划，并非协调请求执行回执。"),
            evidence("/observation/sent_messages", "本观察的本人发送列表为空；不据此读取他人隐藏知识。")),
            question("C01_Q2", "不评价本轮应该选哪个动作：当前针对T:F4-3:0的候选中，哪些操作语义属于向其他必要部门发送任务联系或邀请？", {
                "A": "request_coordination的conventional与joint候选。", "B": "只有query_status。", "C": "wait会自动完成派工。", "D": "任何report_status都等同新派工。"}, "A",
                evidence("/observation/available_actions", "观察同时给出conventional向部门2和joint候选。规则依据：policy_v3/core.py:_communication_action的request_coordination分支发送任务材料；这不是采用建议。"),
                evidence("/observation/public_rules/case_workflow", "公开规则分别保留普通联系和联合本人确认流程；不把任务定义当接收回执。"))]
    if case_id == "C02":
        mi = select_index(obs["inbox"], id="message-4")
        si = select_index(obs["sent_messages"], id="message-2")
        assert obs["inbox"][mi]["payload"] == {"records": []} and obs["sent_messages"][si]["payload"] == {}
        return [question("C02_Q1", "message-4是部门2返回的status_reply，payload.records为空。该回复能支持哪个结论？", {
            "A": "部门2已经完成任务。", "B": "部门2已经承接了派工。", "C": "部门2事实上从未执行任何工作。", "D": "回复没有提供进度记录，实际办理进度仍不能由它确定。"}, "D",
            evidence(f"/observation/inbox/{mi}/payload", "空records不是完成、承接或未工作的证据；本题答案为未知实际进度。")),
            question("C02_Q2", "本人此前发送的message-2是否在该条消息中携带了任务定义或完成材料？", {
                "A": "携带了该工单全部任务。", "B": "没有；其保存payload为空。", "C": "携带了项目P:1的全部材料。", "D": "空payload表示接收方已完成，所以无需材料。"}, "B",
                evidence(f"/observation/sent_messages/{si}/payload", "本人保存的status_query payload为{}。只判断该条可见消息，不猜测对方隐藏状态。"))]
    if case_id == "C03":
        task_i = select_index(obs["projects"][pi]["tasks"], id="J:P:1:1:implement_project:2")
        report_i = next(i for i, a in enumerate(obs["available_actions"]) if a["kind"] == "report_status" and a["target"] == "P:1" and a["params"] == {"recipient": 4})
        assert obs["last_receipt"]["code"] == "work_completed" and obs["projects"][pi]["tasks"][task_i]["state"] == "completed"
        return [question("C03_Q1", "部门2此时的last_receipt及本人任务记录能够确认哪件事？", {
            "A": "本人施工尚未开始。", "B": "只有本人的专业评审完成。", "C": "本人在P:1的施工分项已完成。", "D": "P:1整体已经通过物理验收。"}, "C",
            evidence("/observation/last_receipt", "上一轮implement_project执行成功、code为work_completed，记录实际付费。"),
            evidence(pp + f"/tasks/{task_i}", "本人分项state=completed、completed_round=12；不等同项目验收。")),
            question("C03_Q2", "不判断本轮最优选择：若只比较接口含义，以下哪个动作表示主动把本人持有的P:1记录发给负责人4？", {
                "A": "report_status，target=P:1，recipient=4。", "B": "query_status，target=P:1，department=4。", "C": "wait。", "D": "confirm_project_task会代替向负责人报告全部施工材料。"}, "A",
                evidence(f"/observation/available_actions/{report_i}", "这是可见报告候选。规则依据：policy_v3/core.py:_communication_action的report_status发送本人对应对象合法记录，query_status仅询问。"),
                evidence(pp + "/received_records", "本角色已持有本人完成记录及收到的其他P:1材料；没有引入隐藏世界状态。"))]
    if case_id == "C04":
        assert obs["projects"][pi]["own_confirmed"] is False
        assert not any(r["kind"] == "project_confirmation" and r["author"] == 3 for r in obs["projects"][pi]["received_records"])
        return [question("C04_Q1", "观察能否确认本角色已经作出P:1专项任务确认？", {
            "A": "能，完成评审就等于专项确认。", "B": "不能；own_confirmed明确为false。", "C": "能，收到任务包就等于本人确认。", "D": "这个字段证明项目已经验收。"}, "B",
            evidence(pp + "/own_confirmed", "本人确认状态为false。专业意见与本人任务确认是不同事件。")),
            question("C04_Q2", "仅依据本角色当前持有的材料，关于部门3是否已经作出专项任务确认，哪项结论成立？", {
                "A": "可以确定已确认。", "B": "可以确定从未确认。", "C": "两部门已经自动互相确认。", "D": "目前无法确定；未收到该确认记录不能证明对方未作出确认。"}, "D",
                evidence(pp + "/received_records", "可见记录无部门3的project_confirmation；不能引用另一个角色或owner的实际确认状态。"),
                evidence(pp + "/project_package/note", "原观察明确未收到的意见和进度仍未知。"))]
    if case_id == "C05":
        assert obs["projects"][pi]["state"] == "approved"
        tasks = obs["projects"][pi]["tasks"]
        assert all(t["state"] == "pending" for t in tasks if t["kind"] == "implement_project")
        accept_i = select_index(obs["available_actions"], kind="accept_project", target="P:1")
        return [question("C05_Q1", "负责人看到state=approved、施工任务视图仍为pending。仅凭该观察，对两分项实际最新施工进度可作何判断？", {
            "A": "可以确定两项实际都没开始。", "B": "可以确定两项实际都完成了。", "C": "可以确定项目已经验收失败。", "D": "实际最新进度无法确定；这表示负责人已知阶段及尚无完成更新的任务视图。"}, "D",
            evidence(pp + "/state", "approved是负责人可见的组织阶段；不是物理状态的全知读数。规则依据：policy_v3/core.py:_visible_project与_learn按负责人收到的记录更新阶段。"),
            evidence(pp + "/tasks", "所持施工视图为较早时点的pending，不能证明客观未完成或已完成。")),
            question("C05_Q2", "accept_project出现在本轮候选中，是否单独证明验收所需条件已齐备？", {
                "A": "是，候选出现等于核验通过。", "B": "是，预算获批等于工程与回执都完成。", "C": "不是；可提交申请与拥有完成回执、满足时滞及其他核验条件不同。", "D": "不是，因为该角色在所有情景都没有验收权限。"}, "C",
                evidence(f"/observation/available_actions/{accept_i}", "该候选证明允许提出申请，不保证执行成功。"),
                evidence("/observation/public_rules/project_workflow", "原公开规则要求负责人取得回执、等待技术时滞并申请验收；执行还核对物理条件。"),
                evidence(pp + "/received_records", "所持记录没有两分项施工完成回执；不补入隐藏的真实完成情况。"))]
    if case_id == "C06":
        ti = select_index(obs["visible_tickets"], id="T:F2-1:0")
        assert obs["visible_tickets"][ti]["lead"] == 3
        assert not any(a["kind"] == "route" and a["target"] == "T:F2-1:0" for a in obs["available_actions"])
        wait_i = select_index(obs["available_actions"], kind="wait", target=None)
        return [question("C06_Q1", '若输出{"kind":"route","target":"T:F2-1:0","params":{"department":3,"use_recommendation":false}}，仅检查当前候选契约，应如何判断？', {
            "A": "是有效候选，因为这是有效JSON。", "B": "不是当前有效候选；该kind、target、params组合不在available_actions中。", "C": "是有效候选，因为工单仍在visible_tickets中。", "D": "是有效候选，只要把reason写得更完整。"}, "B",
            evidence("/observation/available_actions", "原17候选没有该目标的route组合；判断不依赖历史失败响应或隐藏事件。"),
            evidence(f"/observation/visible_tickets/{ti}/lead", "该工单可见lead=3。出现在工单列表不等于本轮可再派单。")),
            question("C06_Q2", "以下哪项仅描述当前候选契约，而不替角色决定业务优先级？", {
                "A": "只能从本轮available_actions复制候选，包括其中的wait；旧动作不会因曾经合法而继续合法。", "B": "只要没有收到反馈，任何以前的route都可重复提交。", "C": "可以自行添加一个新目标，等引擎判断。", "D": "必须选择列表第一个候选。"}, "A",
                evidence("/observation/available_actions", "候选契约限定本轮集合，但不规定最优候选或顺序优先级。"),
                evidence(f"/observation/available_actions/{wait_i}", "wait确在当前候选内；这不是要求本轮选择wait。"))]
    raise ValueError(case_id)


def resolve_pointer(context, pointer):
    if not pointer.startswith("/"):
        raise ValueError("Evidence pointer must be RFC6901")
    value = context
    for token in pointer.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def read_source(suffix, relative):
    path = ROOT / BASE / (RUN_PREFIX + suffix) / relative
    raw = path.read_bytes()
    if sha(raw) != FROZEN_HASHES[suffix + "/" + relative]:
        raise ValueError("Frozen source changed: " + str(path))
    return path, raw, raw.decode("utf-8").splitlines()


def build():
    outputs, cases, provenance, systems, common_rules = {}, [], [], [], []
    for cid, title, suffix, round_no, actor, obs_line, decision_line in CONFIG:
        op, oraw, olines = read_source(suffix, "observations.jsonl")
        dp, draw, dlines = read_source(suffix, f"agents/agent_{actor:04d}/decisions.jsonl")
        record = json.loads(olines[obs_line - 1])
        obs = record["observation"]
        dec = json.loads(dlines[decision_line - 1])
        ctx = json.loads(dec["messages"][1]["content"])
        if (record["round"], record["actor_id"], obs["round"], obs["actor_id"]) != (round_no, actor, round_no, actor):
            raise ValueError("Frozen observation locator mismatch")
        if dec["round"] != round_no or dec["actor_id"] != actor or dec.get("attempt") != 0 or ctx["observation"] != obs:
            raise ValueError("Saved model input does not match frozen observation")
        history = ctx["recent_history"]
        if not isinstance(history, list):
            raise ValueError("Invalid saved recent history")
        systems.append(dec["messages"][0]["content"])
        common_rules.append(obs["public_rules"])
        observation_path, history_path = f"observations/{cid}.json", f"histories/{cid}.json"
        qs = questions(cid, obs)
        for q in qs:
            for e in q["evidence"]:
                resolve_pointer({"observation": obs, "history": history}, e["pointer"])
        case = {"id": cid, "title": title, "source": {
            "run_dir": op.parent.relative_to(ROOT).as_posix(),
            "observations_path": op.relative_to(ROOT).as_posix(), "line": obs_line,
            "sha256": sha(oraw), "round": round_no, "actor_id": actor,
            "decision_path": dp.relative_to(ROOT).as_posix(), "decision_line": decision_line, "decision_sha256": sha(draw)},
            "observation_path": observation_path, "history_path": history_path, "questions": qs}
        cases.append(case)
        outputs[observation_path] = encoded(obs)
        outputs[history_path] = encoded(history)
        provenance.append({"case_id": cid, "source_observation_line_sha256": sha(olines[obs_line - 1].encode()),
                           "source_decision_line_sha256": sha(dlines[decision_line - 1].encode()),
                           "observation_canonical_sha256": canon_sha(obs), "history_canonical_sha256": canon_sha(history),
                           "observation_file_sha256": sha(outputs[observation_path]), "history_file_sha256": sha(outputs[history_path]),
                           "saved_decision_input_observation_exact_equal": True,
                           "selected_response_not_exported": True, "old_new_observation_identical": True,
                           "source_history_note": "Original recent_history only; no benchmark answers or new task responses."})
    if len(set(systems)) != 1 or not all(r == common_rules[0] for r in common_rules):
        raise ValueError("Original systems/public rules differ; do not silently homogenize")
    tree = ast.parse((ROOT / "policy_v3/llm.py").read_text(encoding="utf-8"))
    current_system = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SYSTEM" for t in n.targets))
    if current_system != systems[0]:
        raise ValueError("Current SYSTEM differs from saved original; preserve history explicitly")
    outputs["choice_system_original.txt"] = systems[0].encode("utf-8")  # Exact saved text; no appended newline.
    outputs["interface_clarification.txt"] = CLARIFICATION.encode("utf-8")
    outputs["interface_clarification_original.txt"] = b""
    outputs["understanding_system.txt"] = UNDERSTANDING_SYSTEM.encode("utf-8")
    outputs["public_rules_original.json"] = encoded(common_rules[0])
    payload = {"version": VERSION, "status": STATUS, "cases": cases}
    outputs["cases.json"] = encoded(payload)
    code_paths = ["policy_v3/llm.py", "policy_v3/core.py", "policy_v3/spec.py"]
    outputs["source_provenance.json"] = encoded({"version": VERSION, "status": STATUS,
        "pointer_context": {"observation": "case.observation_path JSON", "history": "case.history_path JSON"},
        "source_sha256_scope": "Full source JSONL file bytes; line SHA256 excludes the line terminator.",
        "old_system_sha256": sha(outputs["choice_system_original.txt"]), "case_evidence": provenance,
        "rule_definition_sources": [{"path": p, "sha256": sha((ROOT / p).read_bytes())} for p in code_paths],
        "hidden_world_files_read": [], "network_calls": 0, "world_executions": 0,
        "validation_scope": "File extraction and visible-evidence pointer checks only; no model comprehension test."})
    outputs["questions_and_answers.md"] = render_review(cases).encode("utf-8")
    outputs["public_rules_comparison.md"] = render_rules(common_rules[0]).encode("utf-8")
    outputs["README.md"] = README.encode("utf-8")
    return outputs


def render_review(cases):
    lines = ["# 六案例理解题与标准答案（人工审阅专用）", "", "状态：offline_prepared_not_model_tested。只完成零API材料准备，尚未验证模型理解表现。", "",
             "本文件和cases.json含答案，不得作为模型输入。未来导出理解题只能取id、prompt、options；不得带answer_key、evidence、审阅标题或本文件解释。自主选择任务不带任何理解题。", "",
             "所有证据pointer按RFC6901解析，根对象为{observation:原观察,history:原recent_history}。源码只提供公共操作语义，不提供任何个案隐藏状态；unknown是实质答案。", "",
             "计划为6案例×2版说明×2任务×2独立重复=48个首次作答。理解和选择各自新建会话，不共享问答、选择或反馈；两版使用完全相同的原观察及既往业务history。理解任务用专门问答system，不混入原system的‘选择一个行动’要求。", "",
             "48次不等于已授权调用；如果未来每次允许一次格式修复，硬上限是96次，须另行明确额度和规则。任何格式修复不得提供答案；不追加调用追求通过。两次重复不足以推断普遍错误率。", "",
             "理解正确率与自主选择分别记录；不按是否采用B/C判定好坏，不因未选强化通道而判理解错误。该基准是有目的选择的六个真实观察，不是错误率的随机代表样本。", ""]
    for case in cases:
        s = case["source"]
        lines += [f"## {case['id']} {case['title']}", "", f"原观察：`{s['observations_path']}` 第{s['line']}行；round={s['round']}、actor_id={s['actor_id']}。",
                  f"原决策输入：`{s['decision_path']}` 第{s['decision_line']}行（attempt=0）。原观察与messages内observation逐字段一致。",
                  f"原观察文件SHA256：`{s['sha256']}`。", ""]
        for q in case["questions"]:
            lines += [f"### {q['id']}", "", q["prompt"], ""]
            lines += [f"- {key}：{value}" for key, value in q["options"].items()]
            lines += ["", f"标准答案：**{q['answer_key']}**。", ""]
            lines += [f"- `{e['pointer']}`：{e['explanation']}" for e in q["evidence"]]
            lines.append("")
    lines += ["## 边界", "", "C03选择在本人实际取得施工成功回执之后，但标准答案只引用本人保存观察。C04不把另一部门事实上确认的情况作为角色可知答案。C05不把负责人未获知的实际施工完成情况写入答案。C06判断当前候选，不把原失败response或其理由注入未来选择任务。", "",
              "old/new改变的仅为统一公共释义；本包没有新增个案assignment状态、共同确认状态、物理进度或原因判断字段。candidate ID属于另一种接口改动，本包维持复制原动作对象，不混入比较。", ""]
    return "\n".join(lines)


def render_rules(rules):
    lines = ["# 原公共规则与新增释义的人工对照", "", "原规则留在每个原观察中，old/new完全相同；新版只额外拼接interface_clarification.txt。旧版额外说明为空。choice_system_original.txt逐字来自六例原始decision.messages[0].content。", "",
             "理解任务两版均使用understanding_system.txt，不包含原system的行动选择指令；自主选择任务才使用原system。", "", "## 保存的原public_rules", "", "```json", json.dumps(rules, ensure_ascii=False, indent=2), "```", "",
             "## 新版释义与既有规则的对应", "", "| 释义范围 | 原规则与源码定位 | 未改变的边界 |", "|---|---|---|",
             "| 任务定义、派工、收到与完成 | public_rules.case_workflow；core.py:_task_definition/_assign/inspect分支 | 不补入他人是否已收到或已开工的值 |",
             "| 查询、主动报告、回复 | public_rules.communication；core.py:_communication_action | query发空payload，report/reply只发本人合法对应对象记录 |",
             "| 普通与联合/专项请求、本人确认 | public_rules.ordinary_channel/shared_channel；core.py:_active_service及确认分支 | 两通道都可用；不自动替人确认、不规定采用 |",
             "| 评审、预算、施工、验收 | public_rules.project_workflow/evidence_standard/budget；core.py:_task_action/_project_action | 意见不是真值，资源/时滞/回执与物理条件照旧 |",
             "| 候选集合与本轮输出 | 原SYSTEM；llm.py:validate_action | 不放宽候选、不改字段类型、不自动代选 |",
             "| 负责人已知阶段 | core.py:_visible_project/_learn；原观察project_package.note | 不将owner snapshot的物理进度提供给模型 |", "",
             "## 新版统一释义全文", "", CLARIFICATION, "## 审阅提示", "",
             "这是整体说明清晰度的配对检验，增加文本长度本身可能影响注意力；不能把差异精确归因于某一句说明。释义覆盖普通与强化通道全部动作族，无案例ID、时间、答案或隐含‘应选’动作。", ""]
    return "\n".join(lines)


README = """# 六案例冻结观察理解基准（零API准备）

状态：offline_prepared_not_model_tested。这里只准备材料，不包含模型测试结果、真实调用或实验授权。

- cases.json：案例索引、问题、选项及答案证据。**仅供人工与评分器读取，禁止整体发给模型。**
- observations/C01..C06.json：原保存观察，字段值及列表顺序保留；old/new共用。
- histories/C01..C06.json：原decision.messages内recent_history；两版共用，不是本次理解题或选择结果。
- choice_system_original.txt：原SYSTEM精确文本，仅自主选择任务使用。
- understanding_system.txt：理解任务专用公共system，两版一致，不要求选择业务动作。
- interface_clarification.txt：新版统一中性释义；旧版附加文本为空（interface_clarification_original.txt）。
- public_rules_original.json：六例共同原public_rules的便于审阅副本；模型仍获得各自原观察中的同一规则。
- source_provenance.json：原文件、行内容、观察、历史与说明的哈希和一致性证据。
- questions_and_answers.md、public_rules_comparison.md：人工审阅材料，不作为模型输入。

复跑：在项目根目录执行 `python -B research/v3_20260910_revision/benchmark/build_cases.py --check`，只读核验；不带--check时只创建不存在文件，相同文件不重写，已有内容不同即拒绝。脚本只写自身所在benchmark目录，不导入runtime，不读取world.json，不联网。

理解题导出仅取id/prompt/options；自主选择导出不含任何理解题。不同任务、版本和重复均使用独立新会话，不提供答案反馈、不共享本次理解结果。保留同一原业务history是为控制上下文，不把该history等同于本次任务之间的信息传播。

拟议规模6×2版×2任务×2重复=48次首次作答。若每次额外允许1次格式修复，最多96次请求；两者目前均未授权也未执行。实际导出计划、独立验证及后续收费审批由主任务单独管理。

本包为针对性可理解性案例，不用于估计所有情景的错误率，不以B/C采用增多为成功，不根据隐藏世界状态判角色答错。
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build()
    # Preflight all outputs before writing; never replace a reviewer's edits.
    for relative, content in outputs.items():
        path = HERE / relative
        if not path.resolve().is_relative_to(HERE):
            raise ValueError("Output escaped benchmark directory")
        if path.exists() and path.read_bytes() != content:
            raise ValueError("Refusing to overwrite different existing file: " + str(path))
        if args.check and not path.is_file():
            raise ValueError("Missing generated file: " + str(path))
    if not args.check:
        for relative, content in outputs.items():
            path = HERE / relative
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(content)
    print(json.dumps({"status": STATUS, "cases": 6, "questions": 12, "generated_files_verified": len(outputs),
                      "check_only": args.check, "model_calls": 0, "world_executions": 0}))


if __name__ == "__main__":
    main()
