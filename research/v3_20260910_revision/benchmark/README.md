# 六案例冻结观察理解基准（零API准备）

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
