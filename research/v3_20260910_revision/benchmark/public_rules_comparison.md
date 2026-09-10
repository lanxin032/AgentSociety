# 原公共规则与新增释义的人工对照

原规则留在每个原观察中，old/new完全相同；新版只额外拼接interface_clarification.txt。旧版额外说明为空。choice_system_original.txt逐字来自六例原始decision.messages[0].content。

理解任务两版均使用understanding_system.txt，不包含原system的行动选择指令；自主选择任务才使用原system。

## 保存的原public_rules

```json
{
  "budget": "审批授权额度不预留施工资源；实际执行仍竞争共同资金和施工容量。",
  "case_workflow": "派单后主办部门调查；普通联系、回复和进度报告合法可用。联合清单需本人确认才激活共享；未确认仍可依法普通办理。作业依赖与资源对所有流程相同，技术交接须有已送达的合法完成回执。",
  "communication": "消息结算后在下一轮送达；手动联系/请求/回复计通信劳动，平台同步不重复收人工发送费用。",
  "costs": {
    "case_work_capital": 0.5,
    "communication_cost": 0.2,
    "decision_cost": 0.1,
    "inspect_cost": 1.0,
    "maintenance_cost": 0.1,
    "project_accept_cost": 0.5,
    "project_diagnosis_cost": 2.0,
    "project_proposal_cost": 1.0,
    "project_step_capital": 3.0,
    "project_work_cost": 2.0,
    "recommendation_cost": 0.2,
    "review_cost": 0.5,
    "route_cost": 0.5,
    "setup_cost": 0.5,
    "work_cost": 1.0
  },
  "directory": {
    "2": "供水及机泵作业、供水专业评审",
    "3": "基础设施及接口作业、工程专业评审",
    "4": "专项组织、调查、拟案、预算申请和验收申请"
  },
  "evidence_standard": "共同根源拟案须有可核查现场材料；专业意见由部门自主给出，可以错误。预算只审查申请数额、意见是否齐备与当前资金，不认定真实根因。验收另核对真实物理条件。",
  "ordinary_channel": "普通流程可分别联系、取得反馈、完成协调和源头项目，不丧失法定办理能力。",
  "project_lag": 2,
  "project_steps": 2,
  "project_template": {
    "construction": [
      {
        "department": 3,
        "predecessor_department": null
      },
      {
        "department": 2,
        "predecessor_department": 3
      }
    ],
    "note": "Public proposed-plan template only; it does not establish a shared defect or a correct intervention.",
    "plan": "replace_shared_main",
    "reviews": [
      2,
      3
    ]
  },
  "project_workflow": "专项负责人自愿立项、确认主责、现场调查及拟案；部门2和3作专业评审；负责人收到意见后申请预算；部门执行两个施工分项，按技术前提交接；负责人取得回执后等待技术时滞并申请验收。有依据可撤项，已耗资源不退。",
  "shared_channel": "联合/专项支持可归集已有授权记录、本人确认及同步执行回执；需要建立和维护成本，不生成专业判断、不保证更新成功或提高物理成功率。"
}
```

## 新版释义与既有规则的对应

| 释义范围 | 原规则与源码定位 | 未改变的边界 |
|---|---|---|
| 任务定义、派工、收到与完成 | public_rules.case_workflow；core.py:_task_definition/_assign/inspect分支 | 不补入他人是否已收到或已开工的值 |
| 查询、主动报告、回复 | public_rules.communication；core.py:_communication_action | query发空payload，report/reply只发本人合法对应对象记录 |
| 普通与联合/专项请求、本人确认 | public_rules.ordinary_channel/shared_channel；core.py:_active_service及确认分支 | 两通道都可用；不自动替人确认、不规定采用 |
| 评审、预算、施工、验收 | public_rules.project_workflow/evidence_standard/budget；core.py:_task_action/_project_action | 意见不是真值，资源/时滞/回执与物理条件照旧 |
| 候选集合与本轮输出 | 原SYSTEM；llm.py:validate_action | 不放宽候选、不改字段类型、不自动代选 |
| 负责人已知阶段 | core.py:_visible_project/_learn；原观察project_package.note | 不将owner snapshot的物理进度提供给模型 |

## 新版统一释义全文

以下是同一套既有接口的公共释义，不补充任何个案状态，不改变动作、权限、时序、费用或成功条件，也不要求采用任何特定通道。

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

## 审阅提示

这是整体说明清晰度的配对检验，增加文本长度本身可能影响注意力；不能把差异精确归因于某一句说明。释义覆盖普通与强化通道全部动作族，无案例ID、时间、答案或隐含‘应选’动作。
