# 六案例理解题与标准答案（人工审阅专用）

状态：offline_prepared_not_model_tested。只完成零API材料准备，尚未验证模型理解表现。

本文件和cases.json含答案，不得作为模型输入。未来导出理解题只能取id、prompt、options；不得带answer_key、evidence、审阅标题或本文件解释。自主选择任务不带任何理解题。

所有证据pointer按RFC6901解析，根对象为{observation:原观察,history:原recent_history}。源码只提供公共操作语义，不提供任何个案隐藏状态；unknown是实质答案。

计划为6案例×2版说明×2任务×2独立重复=48个首次作答。理解和选择各自新建会话，不共享问答、选择或反馈；两版使用完全相同的原观察及既往业务history。理解任务用专门问答system，不混入原system的‘选择一个行动’要求。

48次不等于已授权调用；如果未来每次允许一次格式修复，硬上限是96次，须另行明确额度和规则。任何格式修复不得提供答案；不追加调用追求通过。两次重复不足以推断普遍错误率。

理解正确率与自主选择分别记录；不按是否采用B/C判定好坏，不因未选强化通道而判理解错误。该基准是有目的选择的六个真实观察，不是错误率的随机代表样本。

## C01 调查形成任务定义与向他人派工的区别

原观察：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B1_C0/observations.jsonl` 第23行；round=5、actor_id=3。
原决策输入：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B1_C0/agents/agent_0003/decisions.jsonl` 第6行（attempt=0）。原观察与messages内observation逐字段一致。
原观察文件SHA256：`fc25d256c2e6fa8d95252475c7deb95e8c37a82f2c5ddab769bd410f42c4fddb`。

### C01_Q1

观察中的T:F4-3:0任务列actor=2、state=pending。仅据这些字段和当前记录，哪项判断成立？

- A：部门2的任务已完成。
- B：部门2已收到派工并确认承接。
- C：已知任务责任角色，但不能据此证明部门2已收到或承接派工。
- D：此工单不再存在协调需要。

标准答案：**C**。

- `/observation/visible_tickets/3/tasks/0`：可见的是责任角色和本地pending任务视图，不含对方接收或承接证据。
- `/observation/last_receipt`：上次执行结果是调查形成本地任务计划，并非协调请求执行回执。
- `/observation/sent_messages`：本观察的本人发送列表为空；不据此读取他人隐藏知识。

### C01_Q2

不评价本轮应该选哪个动作：当前针对T:F4-3:0的候选中，哪些操作语义属于向其他必要部门发送任务联系或邀请？

- A：request_coordination的conventional与joint候选。
- B：只有query_status。
- C：wait会自动完成派工。
- D：任何report_status都等同新派工。

标准答案：**A**。

- `/observation/available_actions`：观察同时给出conventional向部门2和joint候选。规则依据：policy_v3/core.py:_communication_action的request_coordination分支发送任务材料；这不是采用建议。
- `/observation/public_rules/case_workflow`：公开规则分别保留普通联系和联合本人确认流程；不把任务定义当接收回执。

## C02 空状态回复能够证明与不能证明的内容

原观察：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B1_C0/observations.jsonl` 第31行；round=7、actor_id=3。
原决策输入：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B1_C0/agents/agent_0003/decisions.jsonl` 第8行（attempt=0）。原观察与messages内observation逐字段一致。
原观察文件SHA256：`fc25d256c2e6fa8d95252475c7deb95e8c37a82f2c5ddab769bd410f42c4fddb`。

### C02_Q1

message-4是部门2返回的status_reply，payload.records为空。该回复能支持哪个结论？

- A：部门2已经完成任务。
- B：部门2已经承接了派工。
- C：部门2事实上从未执行任何工作。
- D：回复没有提供进度记录，实际办理进度仍不能由它确定。

标准答案：**D**。

- `/observation/inbox/1/payload`：空records不是完成、承接或未工作的证据；本题答案为未知实际进度。

### C02_Q2

本人此前发送的message-2是否在该条消息中携带了任务定义或完成材料？

- A：携带了该工单全部任务。
- B：没有；其保存payload为空。
- C：携带了项目P:1的全部材料。
- D：空payload表示接收方已完成，所以无需材料。

标准答案：**B**。

- `/observation/sent_messages/0/payload`：本人保存的status_query payload为{}。只判断该条可见消息，不猜测对方隐藏状态。

## C03 本人施工完成后的报告与查询语义

原观察：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C1/observations.jsonl` 第53行；round=13、actor_id=2。
原决策输入：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C1/agents/agent_0002/decisions.jsonl` 第14行（attempt=0）。原观察与messages内observation逐字段一致。
原观察文件SHA256：`9bbc2024fab7ff5313cb1030b01e0d4801c394d60a760620f562fb5294932a5e`。

### C03_Q1

部门2此时的last_receipt及本人任务记录能够确认哪件事？

- A：本人施工尚未开始。
- B：只有本人的专业评审完成。
- C：本人在P:1的施工分项已完成。
- D：P:1整体已经通过物理验收。

标准答案：**C**。

- `/observation/last_receipt`：上一轮implement_project执行成功、code为work_completed，记录实际付费。
- `/observation/projects/0/tasks/2`：本人分项state=completed、completed_round=12；不等同项目验收。

### C03_Q2

不判断本轮最优选择：若只比较接口含义，以下哪个动作表示主动把本人持有的P:1记录发给负责人4？

- A：report_status，target=P:1，recipient=4。
- B：query_status，target=P:1，department=4。
- C：wait。
- D：confirm_project_task会代替向负责人报告全部施工材料。

标准答案：**A**。

- `/observation/available_actions/1`：这是可见报告候选。规则依据：policy_v3/core.py:_communication_action的report_status发送本人对应对象合法记录，query_status仅询问。
- `/observation/projects/0/received_records`：本角色已持有本人完成记录及收到的其他P:1材料；没有引入隐藏世界状态。

## C04 本人专项确认与他人确认的知识边界

原观察：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C1/observations.jsonl` 第33行；round=8、actor_id=2。
原决策输入：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C1/agents/agent_0002/decisions.jsonl` 第9行（attempt=0）。原观察与messages内observation逐字段一致。
原观察文件SHA256：`9bbc2024fab7ff5313cb1030b01e0d4801c394d60a760620f562fb5294932a5e`。

### C04_Q1

观察能否确认本角色已经作出P:1专项任务确认？

- A：能，完成评审就等于专项确认。
- B：不能；own_confirmed明确为false。
- C：能，收到任务包就等于本人确认。
- D：这个字段证明项目已经验收。

标准答案：**B**。

- `/observation/projects/0/own_confirmed`：本人确认状态为false。专业意见与本人任务确认是不同事件。

### C04_Q2

仅依据本角色当前持有的材料，关于部门3是否已经作出专项任务确认，哪项结论成立？

- A：可以确定已确认。
- B：可以确定从未确认。
- C：两部门已经自动互相确认。
- D：目前无法确定；未收到该确认记录不能证明对方未作出确认。

标准答案：**D**。

- `/observation/projects/0/received_records`：可见记录无部门3的project_confirmation；不能引用另一个角色或owner的实际确认状态。
- `/observation/projects/0/project_package/note`：原观察明确未收到的意见和进度仍未知。

## C05 负责人已知阶段与未获知的物理进度

原观察：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C1/observations.jsonl` 第120行；round=29、actor_id=4。
原决策输入：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C1/agents/agent_0004/decisions.jsonl` 第32行（attempt=0）。原观察与messages内observation逐字段一致。
原观察文件SHA256：`9bbc2024fab7ff5313cb1030b01e0d4801c394d60a760620f562fb5294932a5e`。

### C05_Q1

负责人看到state=approved、施工任务视图仍为pending。仅凭该观察，对两分项实际最新施工进度可作何判断？

- A：可以确定两项实际都没开始。
- B：可以确定两项实际都完成了。
- C：可以确定项目已经验收失败。
- D：实际最新进度无法确定；这表示负责人已知阶段及尚无完成更新的任务视图。

标准答案：**D**。

- `/observation/projects/0/state`：approved是负责人可见的组织阶段；不是物理状态的全知读数。规则依据：policy_v3/core.py:_visible_project与_learn按负责人收到的记录更新阶段。
- `/observation/projects/0/tasks`：所持施工视图为较早时点的pending，不能证明客观未完成或已完成。

### C05_Q2

accept_project出现在本轮候选中，是否单独证明验收所需条件已齐备？

- A：是，候选出现等于核验通过。
- B：是，预算获批等于工程与回执都完成。
- C：不是；可提交申请与拥有完成回执、满足时滞及其他核验条件不同。
- D：不是，因为该角色在所有情景都没有验收权限。

标准答案：**C**。

- `/observation/available_actions/12`：该候选证明允许提出申请，不保证执行成功。
- `/observation/public_rules/project_workflow`：原公开规则要求负责人取得回执、等待技术时滞并申请验收；执行还核对物理条件。
- `/observation/projects/0/received_records`：所持记录没有两分项施工完成回执；不补入隐藏的真实完成情况。

## C06 已派单对象与当前候选集合的区别

原观察：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C0/observations.jsonl` 第73行；round=18、actor_id=1。
原决策输入：`runs/v3-autonomous-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C0/agents/agent_0001/decisions.jsonl` 第19行（attempt=0）。原观察与messages内observation逐字段一致。
原观察文件SHA256：`e64de3c19683c09c29bd80cfdb0b3c65dde2bf7a2e7c5d60099d4d0af29bd7a3`。

### C06_Q1

若输出{"kind":"route","target":"T:F2-1:0","params":{"department":3,"use_recommendation":false}}，仅检查当前候选契约，应如何判断？

- A：是有效候选，因为这是有效JSON。
- B：不是当前有效候选；该kind、target、params组合不在available_actions中。
- C：是有效候选，因为工单仍在visible_tickets中。
- D：是有效候选，只要把reason写得更完整。

标准答案：**B**。

- `/observation/available_actions`：原17候选没有该目标的route组合；判断不依赖历史失败响应或隐藏事件。
- `/observation/visible_tickets/3/lead`：该工单可见lead=3。出现在工单列表不等于本轮可再派单。

### C06_Q2

以下哪项仅描述当前候选契约，而不替角色决定业务优先级？

- A：只能从本轮available_actions复制候选，包括其中的wait；旧动作不会因曾经合法而继续合法。
- B：只要没有收到反馈，任何以前的route都可重复提交。
- C：可以自行添加一个新目标，等引擎判断。
- D：必须选择列表第一个候选。

标准答案：**A**。

- `/observation/available_actions`：候选契约限定本轮集合，但不规定最优候选或顺序优先级。
- `/observation/available_actions/9`：wait确在当前候选内；这不是要求本轮选择wait。

## 边界

C03选择在本人实际取得施工成功回执之后，但标准答案只引用本人保存观察。C04不把另一部门事实上确认的情况作为角色可知答案。C05不把负责人未获知的实际施工完成情况写入答案。C06判断当前候选，不把原失败response或其理由注入未来选择任务。

old/new改变的仅为统一公共释义；本包没有新增个案assignment状态、共同确认状态、物理进度或原因判断字段。candidate ID属于另一种接口改动，本包维持复制原动作对象，不混入比较。
