# 固定任务的系统 token 效率实验

设计与依据：[按官方执行链重构](native-refactor-design.md)、[2.8.7 官方 agentic loop 与版本边界核查](official-agentic-loop-20261031.md)。运行状态以下列验收为准。

<a id="native-refactor"></a>
## 当前：官方 agentic loop 重构（2026-10-31）

提交前复查：对照安装的官方2.8.7源码，确认主体与环境都执行官方循环。修复工具/回执写盘失败未锁定技术失败的问题，保留Schema与业务拒绝的自纠；三个新回归先复现失败再修复；完整离线套件151项通过，最终暂存导出中的2项环境回归也通过，外网与Ray启动尝试均为0。删除重复的主体世界描述加载覆盖，统一调用官方公开getter。剩余适配及必要性见[适配清单](../../ARCHITECTURE.md#剩余适配与必要性提交前复查)。本轮复查证据见[独立记录](../../runs/native-review-20261031/validation.json)，仅离线验证。

当前为 `official-finite-5` / `native-tools-profile-5`，运行时 `official-policy-6`，接口 `v3.3-materials-13`，提示 `official-native-17`。依赖与模型设置保持；旧检查点不接入新版。

主体继续运行官方 PersonAgent；岗位指导迁入默认激活的静态 Skill，TODO 使用官方工具。业务请求实际执行官方 ReActRouter，保留工具 Schema、readonly 和可信岗位检查；不再以生产指令首词决定调用。coder与最终summary请求统一经原计量客户端、原loopback代理和原账本，计入全系统token。真实排队回执才证明立案，模型摘要success不充当业务事实。

业务结算移入 `PolicyEnv.step()`。complete/abandon握手由官方任务成功返回及工作区保存结果验收替代；模型可未提交便finish，记录未办理；提交后仍可合法查询，耗尽保留官方fallback记忆。技术失败阻止整轮结算；环境只保存一次，并在官方返回后核对保存状态。恢复按官方 `from_workspace → init` 顺序。

保留实体dict，增加本人/对象的记录与任务索引、材料接收轮索引及待投递deque；索引不进入权威快照，恢复时重建。正常与零摩擦条件下的顺序对照通过，候选、实际送达知识、事件和结算保持。未测加速倍数。

新增23项回归，完整离线套件 **148项通过**，外网连接与Ray启动尝试均为0。实际运行真实官方轻量类、使用离线模型替身；保存后重建再推进与不中断推进的世界和消息记录一致。源码包已生成并核对内容，未上传。本轮验收见[记录](../../runs/native-refactor-20261031/validation.json)与[日志](../../runs/native-refactor-20261031/offline-tests.log)。真实API、Ray与云端均未启动；旧125项回归仅作迁移起点。真实协调行为、额外路由开销及分布式恢复尚未验证；新架构下的000仍待新的明确授权，不能混用历史基准。

## 历史：零摩擦、协议标记与依赖冻结（2026-10-31）

零通信摩擦下的办理记录改由现有官方邮箱在整轮结算后被动交接，作者当轮可见，其他成员收到后才可见；非作者材料使用实际接收轮。完整离线见证中，000基准、000零摩擦、010零摩擦分别在49、30、37轮完成，事件审计和动作重放通过。这些轮数是脚本见证，不是模型表现或政策效果。正式清单仍使用baseline环境。

当前协议唯一生成入口为[policy_sim/protocol.py](../../policy_sim/protocol.py)：四主体、种子3001、12个初始问题，无新增和复发，无固定轮数，完成个案、必要根因修复和行政验收后比较全系统`T_system`；真实000通过后才开放其余七组。[旧60轮协议](design_protocol.json)和[八组合模板](design-8.json)已显式标为历史不可执行，原科学字段保留，不沿用旧T_agent/U推断解释当前结果。

[requirements.lock](../../requirements.lock)精确锁定当前已验收Mac arm64环境的125个Python包，environment.yml固定Python3.12.14并引用该清单。运行前核对包版本；实际Python、平台、架构和包版本进入冻结配置、driver报告及比较身份，恢复和独立审计核对一致性。本轮未安装或升级包；无网络安装预检无需更改任何包，pip依赖检查无冲突。

新增4项回归，完整离线套件**125项通过**，禁止外网和Ray启动、回环上游为替身，真实API请求为0。[验收与源码记录](../../runs/offline-followup-20261031/validation.json)、[测试日志](../../runs/offline-followup-20261031/offline-tests.log)。未启动真实API、Ray或云端仿真，未修改原账本和历史运行证据；尚未重建全新或其他平台环境。源码已变，旧冻结配置不能直接接续。

## 历史：审计前五项修复（2026-10-31）

接口更新为`v3.3-materials-12`；框架、运行时、提示、模型参数与领域规则沿用上轮。独立审计核对实际政策与冻结记录，比较阶段同时要求审计结果为000。开账和启动控制器前拒绝遗留的reserved请求，保留原账本。显式恢复仅接续已有尝试，后续prepared组正常首次启动；手动续跑不占用其他组的初始尝试名额。可信主体上下文覆盖内部未办理标记，模型传入的ctx不能改变生命周期。大项目保留当前状态，任务和收到的记录通过原read_work工具的受限子页完整读取，查询仅限本人可见项目。

新增7项回归，先确认原失败条件，再修复；完整离线套件**121项通过**。验证禁止外网和Ray启动，回环代理使用假上游，真实API请求为0。[验收记录与源码哈希](../../runs/offline-fixes-20261031/validation.json)、[测试日志](../../runs/offline-fixes-20261031/offline-tests.log)。本轮未启动仿真、未改原账本或历史运行证据；旧源码冻结的manifest和authorization不能直接接续。其余审计项未纳入本轮，不据此声称真实模型长程协作通过。

## 历史：AgentSociety 适配层七项修复（2026-10-20）

该阶段提示为`official-native-16`、配置为`native-tools-profile-4`、运行时为`official-policy-5`、执行策略为`official-finite-4`、接口为`v3.3-materials-11`。框架仍为AgentSociety2 2.8.7，模型参数与领域规则保持。旧冻结配置和检查点不能直接接续到本版。

本轮只修复代码逻辑并做离线验收，未启动实验、真实API或Ray，未改历史运行证据、授权和账本。初始工作概览直接进入官方首个提示；读取存根随最近8条工具观察失效，正文淘汰后可再次读取；节奏提示按ReAct迭代计数，监控比较正文时排除变化的读取计数和节奏提示。审计接受并严格核对正常finish、未办理与已立案但使用官方兜底记忆的轮次；停机期限覆盖请求排空；恢复复用不可变文件的硬链接，新请求写新attempt目录，并保留完整恢复谱系。

验收覆盖首个提示直接提交、批量8条工具结果后的工作页与材料重读、格式修正下的迭代计数、真实存根的重复告警、正常/未办理/兜底轮次审计及伪造记忆拒绝、连续两次恢复后的证据可读性与旧现场不变、控制器等待排空。完整离线套件 **114项通过**；运行时显式禁止外部网络和Ray启动，代理上游均为测试桩。首次沙箱执行的6项本机端口权限失败已在允许loopback的环境重验通过。[验收记录与源码哈希](../../runs/offline-fixes-20261020/validation.json)。这些检查不证明真实模型token降幅或自主协作成功。当前接口与恢复约定见[架构说明](../../ARCHITECTURE.md)。

## 历史：业务指令确定性分发已实施（2026-09-14）

现行提示为`official-native-15`、配置为`native-tools-profile-4`、运行时为`official-policy-4`、执行策略为`official-finite-4`、接口为`v3.3-materials-10`。模型、请求参数、领域规则和原费用账本保持；旧检查点不混用。

attempt-0056 的结构性根因已确认并修正：主体发出的模板指令（`submit candidate {candidate_id} with reason {reason}` 等三类）本身已是最终业务决定，但官方 ReActRouter 仍交给一个路由模型重新翻译。该模型按通用提示"逐步思考、按需收集信息"，对每次 submit 先 observe、读规则、读目录、读材料，3 步预算内从未执行 submit；`generate_final_answer` 又把"已执行的工具都成功"当作 success，主体看到"成功但无 queued 回执"只能重试，8 次重试 × 每次 3 个路由调用全部浪费。仅第 0 轮未完成即消耗 environment_routing 57 笔HTTP请求、182,950 token（原说明误记为114，按[保存的结算结果](../../runs/interface-contract-20260914-preflight/monitor/final-result.json)更正），占该次总量 423,844 的 43%。

- **确定性分发**：`interface.dispatch_plan` 以指令首词加类型化 variables 确定唯一工具调用；PolicyRouter 直接执行，不经任何路由模型。attempt-0056 中主体自发使用的三类指令模板 100% 可分发，容忍措辞差异，严格校验变量类型。
- **失败可自纠**：未知指令或变量不合法返回 `fail` 回执与纠正性错误，不执行工具、不调模型；业务校验拒绝（如 propose_project 缺 `analysis`）返回带精确错误的失败回执，主体下一轮可补正。运行时对任何模型路由调用立即失败。
- **审计更强**：独立审计用同一纯函数复算每次 ask 的应执行工具与参数，路由记录必须逐字相符；删除了原先只能核对路由模型请求/响应的证据链。
- **回执语义修正**：回答状态只反映请求操作本身的成败，不再把"执行了别的只读工具"标为 success。
- 前轮接口事实保持：环境`observe/read_work/read_materials/submit`形成可执行信息与行动链；官方`build_agent_json`每次携带本轮工作与提交阶段；`official_adapter.py`仅修正两处官方文本冲突；一个主体失败后停止新请求并在原截止期内保存在途回执。

**完整离线套件102项通过**，含 attempt-0056 回归（propose_project 缺 analysis 先失败后补正、未知指令零工具零模型、路由篡改检测）。离线通过不预测真实模型行为，也不代表 000 基准完成；真实新版 000 启动与监控状态见下方运行记录。

<!-- optimized-run-status -->
**真实000 attempt-0056已运行并自动暂停，完整基准未通过（历史证据）。** 北京时间11:13从初始状态启动；主体1/2/3均提交并finish，主体4耗尽10次迭代仍未提交，完整结算0轮、解决0/12。主动停止命令执行时driver已经退出，未发送SIGINT。

**此次仍遗漏立项提交契约。** 主体4连续8次要求提交同一propose_project候选，variables仅含candidate_id/reason，没有结构化analysis；路由每次重新observe、查规则/目录/材料，3次模型调用即耗尽，始终没有执行submit。当前回执把成功读取也标为success，未明确区分“请求的提交未完成”。旧版文件路径不可读问题未在本次重现，但不能据此宣称整体问题解决；增加路由步数是否足够尚未验证。[逐次提交失败链与最终结果](../../runs/interface-contract-20260914-preflight/monitor/final-result.json)、[整场失败审计](../../runs/interface-contract-20260914-preflight/monitor/final-audit.json)。

76笔HTTP200，共423,844 token：主体238,731、环境路由182,950、记忆2,163，A/C为0；费用估算0.909362元，非账单。原账本9217→9293；76份规范请求和76份原始响应均保存，用量对账无冲突，在途0、未知用量0，inflight_drained=true，Ray与控制器退出。运行源码保持冻结。
<!-- /optimized-run-status -->

<!-- optimized-run-status-0058-0059 -->
**attempt-0058（11:47启动）：确定性分发在真实运行中生效，因上游502停止。** 提交6个完整轮次、解决2/12，environment_routing请求数为0，主体4的submit全部成功；105笔请求后deepseek网关返回502传输错误，按设计停止并保留证据，账本9293→9398（约1.88元）。同源码下resume暴露两处缺陷：无API key的父进程无法导入检查点校验（router导入链强制要求密钥，attempt-0058失败报告中的checkpoint_inspection_error同根因），源码修复后旧检查点按完整性规则不可接续。

**attempt-0059（11:53启动）：第8轮因空状态回复呈现缺陷失败。** 提交8轮、解决2/12、169笔请求，environment_routing保持0。失败链：主体3对P:1的reply_status按领域规则送达空records（其时尚无办理记录，空集即完整答复）；主体4看到“部门3回复了我的项目”的信封后，10次官方迭代全部重复read_work inbox等待内容，从未提交，turn_incomplete停止。账本9398→9567（约3.04元）。修复：空records消息在概览recent与read_work正文中均携带显式content_note（“空records即完整答复，重读不产生新信息”），领域语义不变；WORLD_DESCRIPTION补充对应指引；提示版本official-native-8、接口v3.3-materials-2，新增回归测试（103项离线检查通过）。
<!-- /optimized-run-status-0058-0059 -->

<!-- optimized-run-status-0060 -->
**attempt-0060（12:08启动，official-native-8）：第5轮因轮内轮询与末轮提交失败。** 提交5轮、解决1/12、92笔请求，environment_routing保持0，空回复content_note未再引发读取循环。失败链：主体2在第4轮的work候选因前置任务K:T:F1-1:0:3（主体3承担）未完成被business_rejected；第5轮它在第3次迭代已查明原因，却连续轮询visible_tickets等待前置状态变化（6次相同返回），直到第10次（最后一次）迭代才提交另一工单的候选——排队成功但无剩余迭代调用finish，turn_incomplete停止。修复：WORLD_DESCRIPTION明确“工单/任务/项目状态只在整轮结算后更新，轮内重复查询只会得到相同状态，不能等待前置完成；不要把提交留到本轮最后一次工具调用”；read_work分页新增as_of_round状态时点锚定；提示版本official-native-9、接口v3.3-materials-3（104项离线检查通过）。
<!-- /optimized-run-status-0060 -->

<!-- optimized-run-status-0061 -->
**attempt-0061（12:26启动，official-native-9）：第2轮因批量上限错误不可自纠失败。** 提交2轮、解决1/12、96笔请求，environment_routing保持0。失败链：主体1一次read_materials请求5个source_id（上限4），错误信息"Material read requires bounded unique source ids"未说明上限数值，query_help也未教该约束；模型10次迭代反复重试不同组合，从未提交。修复：错误信息明确写出上限（"at most 4 unique source ids per request"，topic来源同理写明128），query_help教学“每次最多4个、不可重复”；提示版本official-native-10、接口v3.3-materials-4（105项离线检查通过）。教训：环境拒绝必须携带可执行的具体约束，教学文本必须预先覆盖会触发的所有限制。
**attempt-0062（12:47启动，official-native-10）：39轮后按用户指示停止；发现多主体协作死锁。** 570笔请求全部完整结算（0笔在途丢失），共4,687,388 token（主体决策+记忆，environment_routing保持0），估算约10.90元；提交39个完整轮次、解决2/12、0工程立项。第12轮后进度停滞：主体2对6个":2"任务提交work共28次，全部因前置未满足被拒；其前置":3"任务（主体3名下、无自身前置）对主体3不可见——联合流程未激活，主体3从未收到交接，37轮重复对T:F4-1:0发report_status；主体2作为T:F1-1:0的lead始终未被提供register_joint_workflow候选（该工单未完成inspect）。死锁链：lead需inspect→register_joint_workflow→部门3收到任务→完成0:3→部门2完成0:2；四主体均未发现该路径，环境仍持续提供注定失败的work候选且拒绝回执不含具体未满足项。停止方式：写入request_stop.json（reason=user_stop）后外部终止driver，batch_status残留running态、570/570请求证据完整，Ray残留进程已清理。此为模型集体策略与环境可发现性问题的组合，不是计量或完整性缺陷；是否通过更可执行的拒绝回执/候选可见性修正继续推进，等待用户决定。
<!-- /optimized-run-status-0061 -->

**attempt-0062（12:47启动，official-native-10）：39轮后按用户指示停止，见下方死锁记录。**

<!-- optimized-run-status-0062-stop -->
**attempt-0062最终状态（13:33用户停止）。**

以下保留attempt-0055的原诊断及更早历史；其中的“当前”“本次”均指各自冻结版本。

<a id="native-refactor-0055"></a>
## 历史：官方API已接入，真实000暴露接口缺陷（2026-09-14）

**最新复核：此前验收漏掉了主体与环境路由的信息接口。** 原始响应经实际官方生命周期离线回放，复现10次主体调用、6次路由调用后仍未提交；最小化到一次提交请求仍失败。同一候选和理由经官方submit工具可合法排队，排除本次参数丢失、编号无效或写入权限错误。主要接入缺陷是环境observe复用了主体文件概览，指向4类business文件并提示read/list，但路由根本没有这些工作区工具；它将文件路径当source_id查询而被拒绝。24次read中9次同正文回读，8次之前的正文已从最近8条工具观察窗口淘汰，另1次仍可见时重复。不能把全部冗余写成遗忘或模型问题。[完整HTML复核](token-diagnosis.html#api-recheck)、[原始回放](../../runs/native-api-20260914-preflight/monitor/diagnosis/full-replay.json)、[最小化](../../runs/native-api-20260914-preflight/monitor/diagnosis/minimal-replay.json)、[合法提交对照](../../runs/native-api-20260914-preflight/monitor/diagnosis/direct-submit-replay.json)。

另确认默认提示允许空memories而Schema要求至少1条，等待措辞也与业务契约存在冲突；它们不是主体1此次首轮失败的已证实原因。ModelClient取消探针复现只留request_started、不保存响应的问题；正常对照能完整保存。本次末尾2笔已计费缺响应与这一风险相符，仍不等于还原了全部Ray进程调度。原脚本路由直接把指令首词转成工具名，因而89项通过不能证明真实模型能完成信息查找与工具选择。[探针与分项用量](../../runs/native-api-20260914-preflight/monitor/diagnosis/probes.json)、[官方页面及安装源码核对](../../runs/native-api-20260914-preflight/monitor/diagnosis/official-contract.json)、[修正顺序与边界](../../runs/native-api-20260914-preflight/monitor/diagnosis/findings.json)。本轮仅诊断和离线对照，运行源码、模型与账本未改，000和监控保持暂停。

当前为 `official-finite-2` / `official-native-5`：原生PersonAgent工具、提示、finish记忆与工作区；原生ReActRouter业务派发；SimpleSocialSpace真正收发，包括首轮派单。删除自定义ask_env Schema、提示拼接、finish事实注入和read_history分页。供水领域规则、合法信息与独立审计集中保留。[HTML报告](token-diagnosis.html#current-run)、[架构及适配依据](../../ARCHITECTURE.md)。

**完整离线套件89项通过。** 最终官方Ray先运行3轮，保存退出后恢复至第4轮；16个主体轮次、16条原生记忆、6次官方消息投递通过独立审计，errors为空，Ray已退出。模型请求0。四轮属于接口与恢复验证，不代表完整000完成或真实模型行为通过。 [独立审计](../../runs/official-api-refactor-20260914/final-audit.json)、[验收摘要](../../runs/official-api-refactor-20260914/acceptance.json)。 工作概览≤12,000 UTF-8字节，正文文件≤6,000字节；这些是输入边界，不是token节省。[测试日志](../../runs/official-api-refactor-20260914/offline-tests.log)、[官方版本指纹](../../runs/official-api-refactor-20260914/official-contract.json)。

环境路由新增的真实调用必须计入 `environment_routing`，系统总token还包括主体、记忆、A/C。官方ReActRouter无embedding调用，本项目返回实际收据不再调用路由摘要模型。原模型、请求参数与费用账本保留；新版本不恢复旧检查点。零摩擦消息现在统一在整轮边界交付，须用同版协议重跑对照。

**最新真实000 attempt-0055于10:22按授权从初始状态重启，首轮未完成后自动暂停。** 冻结源码`87487901a34cc1e9fedcd69e3d849118b2b6879d4f2a44bc54560922630a6f74`；主体1两次要求提交合法候选，路由先observe，再将概览中的工作区文件路径当成材料编号查询，被权限校验拒绝，未执行submit。10次迭代用尽后仍未提交或finish，完整结算轮次0、解决0/12。该记录确认失败链，不代表已完成根因干预验证。[最终现场与逐请求核验](../../runs/native-api-20260914-preflight/monitor/final-result.json)、[冻结源码](../../runs/official-api-refactor-20260914/source-final.zip)。

36笔HTTP200请求，共175,095 token（主体139,451，环境路由35,644），费用估算0.376626元，非实际账单。原账本9181→9217条，源码未变；在途0、未知用量0，控制器与Ray已退出，五分钟监控暂停，不自动重跑。末尾2笔请求费用已结算，但本次工作区缺原始响应文件，保留为失败现场证据缺口；不能宣称完整审计通过。

前次attempt-0054于09:34启动，完成8轮、解决2/12；152笔请求、1,040,383 token（主体996,449，记忆43,934），在途0、未知用量0。按用户要求停止是为了更改重构范围，不是新确认的运行异常。[此前停止现场](../../runs/business-contract-20260914-preflight/monitor/final-result.json)、[此前冻结源码](../../runs/business-contract-20260914-validation/source-review.zip)。

下面保留按当时版本写下的历史结论；历史中的“本次”“当前”均不代表现行实现。新源码真实验证已触发失败边界，不能声称已经消除重复或通过完整000基准。


<!-- repetition-fix-current -->
<a id="context-optimization"></a>
## 历史复核：attempt-0053有限冗余与停止判断（2026-09-14）

**重复读取属实，但现有证据不足以认定本次发生系统失控或必须停机的持续故障。** 主体3第0轮三次读取空收件箱后，正常提交wait并finish，共7次决策调用。以保存响应重放实际安装的官方生命周期，原轨迹和逐项删减轨迹均正常收尾；删除至仅一次读取，重复指标才转为通过。回放验证执行与完成契约，不证明模型为何选择重复，也不预测改提示后的行为。[当前HTML复核](token-diagnosis.html#behavior-review)、[离线回放及最小化](../../runs/context-optimization-20260914-preflight/monitor/diagnosis/replay-result.json)。

已提交5轮的20个主体轮次共74次决策调用，平均3.7、中位数3、最大7，解析错误0；7个主体轮次存在相同历史页回读（共8次额外读取），均完成。触发停机的两次额外空箱查询对应9,070 token，占系统561,913的1.61%；这是这些请求的实际用量，不是全部冗余成本或可实现节省。三次读取来自不同模型请求，先前空结果可见，74份已结算决策的模型调用与工具派发逐项相符。[原始证据核查](../../runs/context-optimization-20260914-preflight/monitor/diagnosis/evidence-result.json)。

**停止判断需要更正：**监控脚本在最近80条工具回执中查找历史重复，没有将已经完成的轮次排除；它给出的本来是待核查线索。我在该主体已完成、整场已推进5轮时仍依据第0轮告警停止，过于敏感。仅将探针输入收窄为未结算轮次，重复告警即消失。历史停止现场保留，不改写成框架故障。

官方文档定义了模型选择工具、执行、反馈和finish的循环，没有规定“三次重复读即异常停机”。安装版2.8.7源码明确默认10次迭代、解析错误即时修正一次、最近8条工具观察；允许重复只读查询，不保证模型每步最省调用。[官方ReAct说明](https://agentsociety2.readthedocs.io/en/latest/agents.html#react-tool-loop)、[环境工具契约](https://agentsociety2.readthedocs.io/en/latest/env_modules.html#the-tool-decorator)、[安装版来源与哈希](../../runs/context-optimization-20260914-preflight/monitor/diagnosis/official-contract.json)。

另有两次可纠正的工具误用：把`/public_rules`当成材料ID，以及同批输出两个submit；权限和提交阶段校验拒绝了不合法调用，未出现越权读取或双重提交。空箱仍显示history_path，可能增加无收益查询的诱因，但提示已说明本轮快照与读取不推进世界，不能将提示缺失认定为已证实根因。后续优先明确空结果已完整、材料ID与历史路径的区别、单批提交约束；短期重复只记录，停机继续依据循环耗尽且未完成、请求超限或权限/证据/计量失效等明确边界。长期业务停滞须结合合法等待与依赖判断。

本次仅离线复核并更新当前说明，未改执行源码或模型参数，未重跑收费实验。完整000仍未完成，既不能确认基准通过，也不能仅凭这次短运行确认整体token效率正常。

### 当时实现与运行记录

`official-business-3`已按架构复核建议完成：统一业务会话的观察与送达更新；约束全部当前工作，并保留可直接回读的合法历史；修正未送达项目版本泄露；对齐reason、状态消息与既定拟案的真实能力；补独立送达检查与发送前请求预检。[HTML验收报告](token-diagnosis.html#context-optimization)、[架构与适配依据](../../ARCHITECTURE.md)。

- **离线套件：78项通过。** 包含8种政策组合的领域轨迹、非法读取、历史分页、官方循环/修正/记忆、计量、故障与检查点。
- **官方生命周期：12轮，4轮后恢复，48个主体轮次审计通过。** API调用0，Ray已退出；脚本不能证明模型行为。[官方审计](../../runs/context-optimization-20260914/official-audit.json)。
- **原55轮回放：**结算世界、行动、候选顺序及领域事件等价；仅14个`decision_context.observation_sha256`因合法版本修正而改变。完整原证据不改。
- **输入复核：**224份每轮首请求离线重建，最大57,482字节；原413请求由269,795变为57,123字节。追加60轮重复拟案后，四主体当前工作均小于40,000字节；部门3全部收件正文可经19页精确还原。[回放与压力结果](../../runs/context-optimization-20260914/history-validation.json)、[复现脚本](../../runs/context-optimization-20260914/validate_history.py)。这些是字节测量，不是实测token节省。

原模型/请求参数、政策与结算规则不变。历史查询走官方ask_env只读通道，返回原文；官方10次循环、即时一次解析修正、8条工具观察及Memory保持。没有自动wait、强制approve、自动撤项、开放新工程能力或调整代理上限。

**attempt-0053于北京时间08:56从初始状态启动，08:58按用户“类似问题主动终止”的授权发送停止信号。** 完成5轮、解决2/12，工程建成/物理生效/验收均0。98笔上游请求全部HTTP200，共561,913 token：主体531,923、记忆29,990，A/C为0；在途与未知用量均0。原账本8931条基线保留，结束为9029条。控制器和Ray已退出，每5分钟监控已暂停，不自动恢复，其他七组未启动。[最终结果](../../runs/context-optimization-20260914-preflight/monitor/final-result.json)、[启动记录](../../runs/context-optimization-20260914-preflight/launch.json)。

当时主动停止依据主体3第0轮连续3次读取`/inbox`同一页，三次均返回`[]`、`round_advanced=false`。原始事实保留，但停机判断由页首复核更正为过于敏感；该主体随后正常完成，后续轮次也在推进。[逐请求证明](../../runs/context-optimization-20260914-preflight/monitor/repetition-proof.json)、[停止现场](../../runs/context-optimization-20260914-preflight/monitor/stop-evidence.json)。

本次最大实际请求48,125字节，没有再出现413或正文丢失；这些结果仅覆盖短运行，不能证明完整实验的token效率。已提交5轮的20个主体轮次、48条finish记忆及90笔请求对账通过，合计498,385 token；其他63,528 token属于中断轮，照常计入系统总量。[完整轮次前缀审计](../../runs/context-optimization-20260914-preflight/monitor/committed-prefix-audit.json)。整场[审计拒绝未完成现场](../../runs/context-optimization-20260914-preflight/monitor/final-audit.json)，不是基准成功。控制器的unclassified_failure由主动SIGINT终止产生，不应解释为另一次上游故障。运行源码及模型参数未改。

### 上一真实000：保留的失败证据

attempt-0052完成55轮、解决9/12，施工/物理生效/验收均0。第56轮主体3请求269,795字节超过原262,144上限，本地413后暂停。792笔上游请求均HTTP200，共12,192,659 token：主体11,811,455、记忆381,204、A/C为0。另2条请求本地拒绝，补充对账确认未转发；原通用缺失用量记录不改。原账本8139条前缀保留，监控暂停，其他七组未启动。[最终结果](../../runs/repetition-fix-20260914/monitor/final-result.json)、[失败审计](../../runs/repetition-fix-20260914/monitor/final-audit.json)、[运行状态](../../runs/repetition-fix-20260914-real-000/batch_status.json)。

当时失败输入77条消息中202次记录正文只有31份不同记录；收发箱与项目历史都无限增长。模型还把等待评审理由当成办理条件，但reason并不送达，重复方案也没有实质编辑能力。这些发现来自[输入与通信诊断](../../runs/repetition-fix-20260914/context-growth-investigation/findings.json)及[架构复核](../../runs/repetition-fix-20260914/architecture-recheck/findings.json)。历史脚本与行号对应当时[冻结源码包](../../runs/repetition-fix-20260914/source-review.zip)，不能直接按当前接口运行。
<!-- /repetition-fix-current -->

<!-- official-refactor-current -->
## 上一冻结版本：真实000在第8轮暂停（2026-09-13）

该历史版本执行架构为`policy_sim` / `official-finite-1`：复用官方一次ReAct循环、最近8条工具观察和Memory，业务工具仅ask_env/finish，缺有效提交或收尾即暂停。四主体、有限任务、ABC、合法候选及结算规则保持不变。[架构与定制依据](../../ARCHITECTURE.md)、[HTML验收结果](token-diagnosis.html#refactor)。

**离线验收：58项测试全部通过。** 八组合使用相同材料查询与行动回放，观察/候选/事件/结算/指标等价。实际官方AgentSociety/Ray先运行3轮，保存退出再恢复至51轮完成；204个主体轮次通过独立审计，源码一致，Ray已退出。脚本响应不证明真实模型行为。[验收摘要](../../runs/official-refactor-20260913/offline-acceptance.json)、[测试日志](../../runs/official-refactor-20260913/offline-tests-passed.log)、[官方链路审计](../../runs/official-refactor-20260913/offline-ray-final-audit.json)、[八组合等价](../../runs/official-refactor-20260913/domain-equivalence.json)。

**真实000：完成7个结算轮次，初始问题解决2/12；第8轮主体4耗尽10次官方迭代，未提交也未finish，自动暂停。** 原账本第7949条之前的前缀完整保留，本次追加190条、全部HTTP200、全部用量已知、在途为0；控制器和Ray已退出。主体决策159次、1,615,776 token；记忆31次、119,286 token；A/C均0次。系统累计输入1,661,088、输出73,974，合计 **1,735,062 token**，是未完成运行的累计用量。按原费率上界估计3.913968元，不是实际账单。[结果及用量](../../runs/official-refactor-20260913/real-000-result.json)、[完整运行审计](../../runs/official-refactor-20260913/real-000-audit.json)、[最终状态](../../runs/official-refactor-20260913-real-000/batch_status.json)。

最后主体轮次的10笔请求都用于读取材料，其中相同三份材料连续读取9次；成功回执正文完整进入下一次官方输入，没有缺失、引用悬空或解析失败。该轮消耗175,112 token，没有提交或finish。全部32个主体轮次（含未结算轮次）的决策请求中位数4、P95为10、最大10；全运行识别40次同一主体轮次内相同材料集合的额外成功回读，不把所有回读都断言为可避免。实际最大请求数恰为10，不把这一观测当成API硬上限；官方解析修正与记忆另计。[重复轨迹与完整回执可见性核查](../../runs/official-refactor-20260913/real-000-failure-analysis.json)。

前7轮不可变检查点文件哈希、28个主体轮次和独立物理重放通过；第8轮部分结果保留，未结算、未删除、未重试。完整运行审计拒绝未完成现场，是预期失败边界，不代表完整基准通过。此次证明了官方循环边界、暂停、证据和计量机制；**未证明重复查询行为已解决，也不报告token节省比例，其他七组继续关闭。** 000不启用A/C，其真实服务效果仍待后续相应政策组验证。

真实版本为attempt-0051、源码`ef82b926ff29c60ff3f22b49fb0e32632e24592eb0119c4e94de49b189736498`，AgentSociety2 2.8.7、deepseek-flash、thinking关闭、temperature0.2、max_tokens16384、原账本/代理与传输语义。[冻结及授权](../../runs/official-refactor-20260913-preflight/authorization.json)、[交付记录](../../runs/official-refactor-20260913/delivery.json)。旧执行包和重复入口已退役，重构前未提交工作树和历史说明已冻结；原始实验/账本/诊断保持原身份。[源码指纹](../../runs/official-refactor-20260913/before-source-manifest.json)、[退役及替代覆盖](../../runs/official-refactor-20260913/migration.json)。
<!-- /official-refactor-current -->
<a id="repetition-investigation"></a>
## 2026-09-13调查记录：缺陷已在顶部新版本修正，模型效果待实测

**不能仅把失败概括为“模型仍在重复”。当前适配确有问题，之前“只替换冲突提示”的实现说明不准确，已更正。** 本次只读取失败现场、对照安装的官方2.8.7源码，并在离线副本上做单变量探针；没有新增收费请求、修改冻结运行代码或重启实验。[HTML调查](token-diagnosis.html#repetition)、[结构化结论](../../runs/official-refactor-20260913/repetition-investigation/findings.json)。

1. **直接失败过程：模型用静态档案查询来等待最新评审。** 第8轮主体4反复要求核实部门2/3的评审状态，却读取主责确认、现场诊断和拟案三份记录。这些正文在首个输入的`projects.received_records`中已完整提供，10次读取的版本没有变化。材料查询不会推进世界或产生下一轮回信。可见规则本已有“消息结算后在下一轮送达”，但查询反馈没有直接指出“本次无新信息；这三份记录不能回答当前评审是否完成”。离线复制第7轮检查点，补入主体4的`query_status`或`wait`，均可合法结算；不是没有可执行行动。查询状态也不保证对方立即回复或评审。[领域证据及结算副本](../../runs/official-refactor-20260913/repetition-investigation/domain-findings.json)。
2. **提示适配删掉了有用的官方行为约束。** [当时的prompt.py](../../runs/repetition-fix-20260914/before-source/policy_sim/prompt.py)第72行整段替换官方system提示，保留了动态消息块，却丢掉了有限轮次内优先行动、每次推进任务，以及不把临时行动当成稳定事实等说明。官方禁止通用wait的文字确需适配，但这些不冲突的原则应保留。此处是本次实现遗漏；不能把它描述成完全按计划复用了官方提示。[官方实装差异探针](../../runs/official-refactor-20260913/repetition-investigation/mechanism-probes.json)。
3. **无信息增量也刷新全部候选ID。** `apply_read`增加`reads_used`，而`decorate_observation`把含该计数的整份观察纳入候选ID哈希。同一份已送达材料再读一次，12个候选的编号全变，业务含义不变。只还原读取计数，原候选编号即全部恢复。这个因果关系已由单变量离线探针证实；是否因此诱发模型再次读取仍未证实。
4. **错误行动记忆被保存并带入下一轮。** 主体4在零基round 6实际提交的是向部门3`request_review`，结算为`project_task_request_sent`；其finish却把该轮记成了wait。错误已存在于原始finish输出，随后写入episode和下一轮摘要，并非首先由官方整理算法产生。现有提示虽说记忆不证明执行，schema/阶段校验也都通过，仍未发现这条事实冲突。[原始finish响应](../../runs/official-refactor-20260913-real-000/finite-000-s3001-deepseek_official/model_payloads/9c5186b1-39e3-4caa-a9a5-9316fd3e345a.response.json)、[核对探针](../../runs/official-refactor-20260913/repetition-investigation/mechanism-probes.json)。

**消耗为何仍大：** 官方8条窗口有界，但重复正文仍占满窗口。失败主体轮的近期观察从123增至16,626字符；另有每次固定的9,148字符记忆和32,297字符主体信息块。首末请求的user内容从41,669增至58,172字符，业务事实未变化。字符数不是分段token计量；该轮实际10笔请求共175,112 token。[实际输入结构](../../runs/official-refactor-20260913/repetition-investigation/input-structure.json)。

**已排除与仍未知：** 最后10笔没有网络重试、截断、解析纠错或回执正文缺失；没有候选死锁。原始回复回放可重复检出“10次全读、零提交”，这只是已捕获故障的再现，不是修复验证。官方当前消息构建把工具结果放进文本块；这与[DeepSeek工具调用示例](https://api-docs.deepseek.com/guides/tool_calls/)保留assistant/tool消息的组织不同，但差异本身不是接口不兼容或重复根因的证明，旧对话版也发生过重复。各项提示、编号和记忆问题对模型选择的贡献，尚无固定输入的真实对照证据。

**修正优先顺序（本次未执行）：** 首先恢复不冲突的官方行为说明，并把材料版本、是否新增信息、消息何时可能变化放在直接反馈中；然后让候选编号脱离纯读取计数，将本轮候选ID和可核验的提交事实与长期主观记忆区分；最后在保持合法信息和原文可重新查询的前提下收窄重复上下文。先用离线探针核对这些确定性契约，再以固定配置、同一失败输入的单项对照检验模型行为，不能用脚本模型通过来声称重复已解决。现有10次迭代暂停边界继续保留，不自动wait，不因回读强迫选择某项业务行动。

## 以下为历史运行与设计记录

以下“当前”“准备”“建议”均指各节记录时的版本；旧执行入口已退役，旧源码见`runs/official-refactor-20260913/before-source`。历史诊断建议由上方已批准的官方优先架构取代，原始事实和实验输出不改写。

## 当前协议：AgentSociety2 2.8.7 与无政策基准（2026-09-13）

本次同时修订实验协议与执行接口。目标是比较**完成同一批有限任务所需的全部实际模型 token**，不是比较固定时长内的解决率，也不要求主体主动节省 token。旧版资源稀缺、持续复发和固定 60 轮实验的结果不并入本次比较。

现有 Conda `agentsociety` 已升级至 **AgentSociety2 2.8.7**，保留 Ray 2.55.1、MCP 1.30.0 与 `mcp<2` 约束。`pip check` 通过；只升级目标包，未改预装框架源码。见 [环境实测](../../runs/finite-v36-20260913-continuous-preflight/environment-verification.json)。**真实 `000` 于 2026-09-13 16:42 启动，17:53 按用户要求停止，未完成。接口修复已实施，离线验收结果见下节；随后启动的 DeepSeek 官方 `000` 也因输出截断停止；两次运行独立保存。该截断处理的修复与离线验收完成后，修复版真实实验已于 19:15 另行启动，见下一节。** 见[当前运行状态](../../runs/finite-v36-20260913-real-000/batch_status.json)与[启动记录](../../runs/finite-v36-20260913-continuous-preflight/launch.json)。本节下方零 API 的数字属于启动前离线验收。

### 最新运行：对话接口版 000 已因重复读取停止（2026-09-13 21:53）

深入复核见 [Token 异常消耗诊断（交互 HTML）](token-diagnosis.html)：重新对账 456 次请求，逐步回放异常轮的 96 次调用，定位无提交无限续行、旧操作索引持续增长、间接回执与工具契约不一致；对照官方 API 子页及本机 2.8.7 源码，分别标明已证实机制和待验证的行为因果。诊断脚本与数据集中于 [离线证据目录](../../runs/token-diagnosis-20260913/)，本次未修改仿真实现或新增收费调用。

**当前已停止，监控已暂停，未自动重跑。** 本次五分钟检查确认 actor 3 在零基第 6 轮成功读取相同 `MEMORY.md` **92 次**，该轮共 **96 次模型请求、9 次无提交续行**，最后才提交 wait。按用户“异常时中断分析”的授权，暂停本次两个 Ray 决策 worker，等待全部在途结清，正常中断驱动并确认控制器/worker退出。停止时已结算 **10 轮，解决 2/12**，工程尚未施工、物理生效或验收。共 **456 次请求全部 HTTP200，输入 4,736,691、输出 109,703，合计 4,846,394 token**。最后两笔由代理结清、worker未写回结束事件，已知用量仍完整计入；原始 partial_failure 保留。不是网络故障或费用阈值停机。

**本次真实结果说明：对话配对与去重修改没有解决重复读取。** 491 项离线通过只证明被检查的结构、回执、权限与结算行为，不能证明真实模型不重复。本轮仅有 wait 业务候选，内存原文已可见；在第20/60/90次请求，最近 tool 消息仍只是 `result_ref=R1` 和“内容未变”标记，正文位于用户消息中的结果表。优先假设是这种间接回执与重复对话模式没有给模型有效的新反馈；另需区分“仅有合法等待”的状态影响及外层持续续行的放大作用。这些是待对照验证的机制，不能把引用设计直接宣布为唯一原因。

下一步应先在离线轨迹中改为可直接阅读的工具结果，并保留已执行操作的清楚记录；验证不同状态的结果变化、记忆与行动结算边界。真实模型是否减少重复需要小量配对用例确认，不能再由假模型测试直接推断。此监控回合未改运行代码、未发收费诊断或重新启动。[本次异常与停止证据](../../runs/finite-deepseek-dialogue-20260913-preflight/monitor/repetition-anomaly.json)。

已按用户“修改吧”“修复完成后启动实验000”的指令完成接口修复，并于 **21:38:07** 从初始状态启动一次真实 `000`，attempt-0050。最终完整离线 **491 项通过（70.682 秒）**，没有另行收费探针或问答矩阵。新源码 `00085912fa41fece73c54ffd352d520bcca22ba0717f33ab241229196a9431be`，冻结接口 `continuous-tool-dialogue-1`、提示 `business-dialogue-3`；DeepSeek 官方直连、`deepseek-flash`、关闭思考及原有连接重试设置保持。沿用原账本，从第 **7,493** 条之后单独核算此次授权，旧实验记录不并入新基准。五分钟监控已恢复。

修改集中在官方 `build_react_messages`、调用审计和工具回执边界：连续消息保留真实 assistant 工具调用及对应 tool_call_id；同一返回正文只保存一次，和当前记忆重叠的部分引用已有内容。最近 8 批保留完整工具对话，较早操作按顺序保留在 `earlier_operations`，所有不同结果仍在 `retrieved_results` 可见；窗口不是查询次数限制。引用每次按当前上下文重新建立，变化后的文件正常重读，原文件文本不被改写。提交成功后切换到 `record_result`，仅请求官方 `finish(memories=...)` 记录主体自己写的记忆，不替主体写理由或选择业务行动。官方循环、Memory、TODO、Skill、Ray 及研究物理机制保留；无新增费用/轮数/耗时中断阈值。

离线检查覆盖真实官方循环中的配对、重复读取、内容变化、跨主体/轮次隔离、只读问答、截断前后续行、四主体结算屏障、旧配置兼容，并验证独立审计会拒绝工具 ID 或结果正文被改写。历史 actor4/round9 的 28 次调用在相同轨迹下重新呈现，消息字节量减少约 **8.9%**；这是固定旧轨迹的字节比较，不是新请求 token 节省或政策效果，真实重复行为仍在本次运行中观察。

截至 21:42:28，已结算 **4 轮、解决 2/12**，175 次请求成功、2 次在途。启动审计发现一个既有的 `notes` 目录规范化误报：执行器允许 `list/grep notes`，审计器将 `notes/` 规范化后只匹配 `notes/` 前缀而拒绝 `notes`。已定位为审计路径判断差异，并通过只读修正核验前 4 轮、16 个主体轮次；**原版审计没有被表述为通过**。修正入口只增加 `list/grep` 对本人确切 `notes` 目录的承认，其余调用、参数、权限和回执检查保留。正在运行的冻结代码未修改；该审计更正必须在最终整场核验中继续明确处理，不能忽略其他越权报错。

证据：[启动记录](../../runs/finite-deepseek-dialogue-20260913-preflight/launch.json)、[当前批次](../../runs/finite-deepseek-dialogue-20260913-real-000/batch_status.json)、[四角色完整提示与 Skill](../../runs/finite-deepseek-dialogue-20260913-preflight/actor-prompts.md)、[离线日志](../../runs/native-context-repair-20260913/offline-tests-release.log)、[历史呈现回放](../../runs/native-context-repair-20260913/presentation-replay.json)、[启动核验](../../runs/finite-deepseek-dialogue-20260913-preflight/startup-verification.json)、[目录审计更正入口](../../runs/native-context-repair-20260913/verify_dialogue_prefix.py)。官方接口依据：[Agent API](https://agentsociety2.readthedocs.io/en/latest/api/agent.html)、[Using Agents](https://agentsociety2.readthedocs.io/en/latest/agents.html)，并以安装的 2.8.7 源码实际契约核对。

### 前次运行：暂停 000 并分析重复读取（2026-09-13 21:13）

用户要求先暂停并分析 token 开销。本次两个 Ray 决策 worker 已暂停，代理全部在途请求排空后，对已核实参数的 `v3_driver.py` 正常中断；所属驱动、控制器及 worker 均退出，五分钟监控已暂停，没有重新启动实验。实时已结算 **31 轮，初始问题解决 5/12**，全任务尚未完成。原始控制器将中断写为 `technical_failure`，并有 `partial_failure.json`；保留该原始回执，另以[用户停止说明](../../runs/finite-deepseek-resilient-20260913-preflight/monitor/user-pause-20260913.json)标明原因，不能视为干净恢复点或成功实验。

最终 **1,416 次上游请求全部 HTTP 200，输入 26,326,299、输出 430,424，合计 26,756,723 token**。其中主体决策 1,334 次、26,287,755 token；记忆整理 82 次、468,968 token（约 1.75%）。暂停后排空的最后两笔已由原代理结算，但 worker 未写回 `request_finished`，所以主体审计事件为 1,414 笔；这两笔已知用量仍计入总额，不记为零、不重复计算，也不声称其主体动作已执行。[最终账本对账](../../runs/native-context-diagnosis-20260913/final-usage.json)。

**已确认的机制和边界：**

- 成功结果没有普遍丢失。最小历史回放：actor 4、零基 round 9 对 `notes/analysis.md` 在 23 次不同模型调用中读取 23 次，均成功且正文唯一；前一次结果和相同结果引用已经出现在下一次输入中。模型仍反复输出相同的“先检查当前状态”及读取操作。这是重复决策的实证，不是网络重发或账本重复收费。[回放脚本](../../runs/native-context-diagnosis-20260913/replay_repeated_read.py)执行时有意断言失败，以标记这段历史异常；它不是修复通过的回归测试，也不证明新提示下的模型行为。
- `NativePolicyOfficer.build_react_messages` 每次生成 system + user 两条消息，把当前业务、记忆、TODO、Skill 和本轮全部工具回执放进 JSON。没有保留真实 assistant/tool 对话配对；这与已安装官方默认的观察列表方式相近，不属于 HTTP 工具参数错误。DeepSeek 在这种呈现下重复选择读取已确认，但“改用原生对话后会消失”尚未真实验证。
- 自定义 `compact_tool_receipts` 只把完全相同的回执正文改为引用，仍保留每次重复操作，也不跨 memory、TODO 和读取结果去重。代表轮最后输入有 52 条回执，其中 44 条为重复引用。1,333 个已写完审计的决策请求中，703 个携带超过 8 条回执。官方 `person_prompt.build_react_messages` 默认使用 `observations[-8:]`；当前自定义组装没有沿用此窗口。不能直接裁掉前面的材料：旧回执原文、已读状态和合法可检索性仍须保留。
- 在上述 1,333 个决策请求里，业务段、工具回执、记忆分别约占序列化上下文字符的 50.4%、26.0%、19.4%。这些是**字符构成，不是各段实测 token 归因**。因此只缩短工具描述或停止记忆整理不能解决主要开销。
- 官方 `memory_context_max_chars=4000` 只限制 `MEMORY.md`，`recent_memory_limit=8` 的近期事件另行加入；不是“整个上下文限制 4,000 字符”。再次调用 `memory_recent` 或整文件 `read` 又会携带相同经历。
- 当前外层 `run_react_loop` 在官方 10 次迭代结束而无提交时，同轮继续调用官方循环，保留同一观察列表。共记录 42 次无提交续行和 3 次截断纠正。该设计满足“不因迭代次数推进或终止世界”，但没有改变重复探索路径，因而可放大重复消耗。它不是官方自动做出的无限续行。
- 有 298 个已审计决策请求发生在业务提交之后，消耗 6,226,035 token；包括必要的 finish、有效记忆整理前的记录以及可能冗余的读取，**不能把全部算成可节省开销**。

在线[Using Agents](https://agentsociety2.readthedocs.io/en/latest/agents.html)提到 Thread 自动压缩与 `handoff_to_memory()`，但当前已安装 2.8.7 的这条 `PersonAgent → AgentBase.run_react_loop → build_react_messages` 路径没有该压缩步骤或对应接口；实际以观察列表和 `PersonMemoryRuntime.build_context()` 构造输入。API 概览不足以推断这些功能已启用。核对源码：`agent/base/agent.py:1574–1778`、`agent/person_prompt.py:286–385`、`agent/memory_runtime.py:212–234`。官方默认提示也包含不能照搬的模拟身份、时间与 wait 说明；当前研究边界仍优先。

**建议实施范围（本次仅诊断，未修改运行代码或收费复验）：**

1. 在官方公开的 `build_react_messages` 扩展点恢复真实的“assistant 工具调用 → tool 对应回执”短期对话，保留工具调用 ID 和原参数。不复制官方循环；`dispatch_react_tool` 继续做身份、材料权限及业务提交校验。截断中未执行的工具不能伪造成功回执，finish 与混合工具批次按实际执行记录配对。
2. 用一份事实材料区加短操作记录组织上下文。同一条已读材料/个人记忆只保留一份正文，重复读取明确返回“内容未变”并指向仍可见原文；状态或文件内容变化必须失效重读。近期操作用窗口呈现，但窗口外原文不能直接丢弃，须能按稳定编号回查。保留候选集合与材料权限，不把摘要或缓存当成政策 A/C 服务。
3. 将官方 Skill 的工作说明与实际输入字段一致化，明确本轮已执行的操作、已有信息和真正缺口；已有 Skill 已写过“同一内容已成功返回时先据此判断”，所以不再把单加一句“不要重复”当作解决方案。业务提交成功后切到记录与结束阶段，减少重复发送全部候选和办件档案；官方 Memory/TODO 继续保留，finish 不代表业务结算成功。
4. 同轮续行沿用官方循环，但携带明确的已完成操作与未解问题，而不是重新开始探索；不加费用、轮数、查询次数或 wall-clock 强制终止，不替模型派单、选择 wait 或省略必要调查。原版与新呈现是整体接口修订，不能把变化解释为政策效果。

验证先用零收费回放检查：重复结果是否仍可定位、变化后的材料是否及时更新、工具调用与回执是否严格配对、提交与记忆是否分离、权限与统一结算是否保持。再用小量真实官方链路比较同一状态下的重复读取次数、提交前后请求数与输入输出 token；模型是否停止重复只能由真实调用验证。本次不自动开始复验，也不在修改后拼接旧 000 为新版本基准。

[完整上下文统计](../../runs/native-context-diagnosis-20260913/context-findings.json)、[统计脚本](../../runs/native-context-diagnosis-20260913/analyze_context.py)。本次仅更新研究说明与离线诊断工件，原始实验及冻结执行代码不变。

### 官方重试核查与连接重试修复（2026-09-13）

**本次已按用户要求停止，详见下方重复读取诊断。** 连接重试版 `000` 于 20:34:06 启动，attempt-0049；启动前完整离线套件 **486 项通过**。首批真实请求已成功返回，逐次阶段记录可查。[启动核验](../../runs/finite-deepseek-resilient-20260913-preflight/startup-verification.json)、[实时状态](../../runs/finite-deepseek-resilient-20260913-real-000/batch_status.json)、[离线日志](../../runs/deepseek-retry-20260913/offline-tests-final.log)。

核对本机 AgentSociety2 2.8.7 `config/llm_dispatcher.py:459-539`：`LLMClient.call(max_retries=3)` 默认最多 4 次尝试，限流指数退避，其他异常立即重试，内部 LiteLLM Router 自身重试关闭。项目显式传入 `max_retries=1`，即最多两次本地交付；原本地代理首次传输失败就置 fatal 并缓存错误，同 UUID 的官方重试只返回旧错误，不再次请求上游。这是实际重试未解决网络故障的原因，不能将日志里的 Retrying 等同于重连 DeepSeek。官方分层见[框架文档](https://agentsociety2.readthedocs.io/en/latest/architecture.html)。

已新增 `direct-connect-retry-1`，在保留 DeepSeek 直连的 HTTPS 连接层工作。只有 HTTP 内容尚未发送的临时连接故障才重试：最多 3 次、每次连接超时 10 秒、间隔 1/2 秒；成功后恢复 600 秒读写等待，官方客户端仍为 660 秒。DNS 和系统调度耗时不能由 socket 参数完全保证。证书错误不重试，HTTP 已开始发送后的读写失败保留未知用量并停止，重连耗尽也明确停止；本次没有实现任意故障都无限续行或从旧 partial_failure 恢复。

重连保留同一官方模型调用、主体轮次、UUID 和账本行；其他主体的有效提交继续等待，不重做决策、不重复行动、不提前推进世界。连接失败未发出模型正文，不增加模型 token。账本新 `transport_events` 记录连接开始/失败/成功、HTTP 发送、响应头和脱敏异常类型/errno，随运行回执导出；不记录可能含密钥的原始异常字符串。发送后未知请求及历史未知用量不能记为零。[实现与验收说明](../../runs/deepseek-retry-20260913/verification.json)。

20:29 的启动器还发现旧注册器把同名运行在不同授权下累计为全局技术重试，达到历史 8 次上限后阻止新授权；该次在创建实际实验尝试前失败，API 增量为 0。已对当前有限任务按授权隔离尝试核算，保留每次授权的启动次数检查和全部原始哈希链；未删除或重置原注册器。[原记录副本回放](../../runs/deepseek-retry-20260913/registry-replay.json)验证新授权可以进入、原记录未改，同一授权重复启动仍会拒绝。旧模式继续按旧限制解释。

此前比赛平台 1,054 笔与首次官方 DeepSeek 411 笔均无传输失败，后两次分别 1/361 和 2/371 笔失败；这些样本不证明网络以前恒定可靠，也不支持把偶发连接错误归于模型协作能力。用户已授权修复后直接运行；本次最终冻结源码为 `f1e9455224112bf8d73e956db580fd2ef1e94160991efc850ea0c544bb79c1e3`，新准备目录为 [finite-deepseek-resilient-20260913-preflight](../../runs/finite-deepseek-resilient-20260913-preflight/authorization.json)，接续账本第 6,077 条之后，不迁移旧失败状态。

### DeepSeek 官方出站直连（2026-09-13）

**当前已停止：直连版真实 `000` 于北京时间 20:13:58 启动，20:20:35 因传输故障停止。** 完整离线套件 481 项通过；20:14:36 启动快照已成功返回 30 次、在途 2 次、请求失败 0。每 5 分钟监控已恢复，异常时停止分析。[启动记录](../../runs/finite-deepseek-direct-20260913-preflight/launch.json)、[启动核验](../../runs/finite-deepseek-direct-20260913-preflight/startup-verification.json)、[实时状态](../../runs/finite-deepseek-direct-20260913-real-000/batch_status.json)、[离线测试日志](../../runs/deepseek-direct-20260913/offline-tests-full.log)。这些数字是启动快照，不代表任务完成。


20:20 五分钟检查发现两个并发出站请求发生传输失败，控制器自动排空并退出；监控已暂停，没有人为再次发送停止信号或重启。终点已结算 **8 轮、解决 2/12**，工程物理生效与验收均为 0。371 次请求中 369 次成功、2 次失败用量未知、在途为 0；已知输入 4,442,025、输出 73,950，合计 **4,515,975 token**，不是完整 T_system。[停止及证据核验](../../runs/finite-deepseek-direct-20260913-preflight/monitor/20260913T1220-stopped.json)。

冻结源码未漂移，没有输出截断；两笔失败持续约 18.15 秒与 26.97 秒，未耗尽 600 秒等待。失败时段可用 Clash 日志中没有 DeepSeek 连接记录，检查时 TUN 为关闭；停止后无密钥直连 `/models` 约 0.19 秒返回 401。该结果支持间歇性传输故障的解释，不能定位是网络路径、TLS 还是提供方连接异常。底层异常未持久化的已知信息缺口仍存在，本次没有修复或伪造该缺失证据。直连配置已经实施，但不能据此保证稳定，也不能把本次合成 502 归为上游 HTTP 502。

用户要求 DeepSeek 请求不经过本机代理，并授权修改完成后直接开始一次新的真实 `000`。`BudgetProxy` 对已校验的 `deepseek_official` 路由使用独立 `build_opener(ProxyHandler({}))`，明确绕过环境变量与 macOS 自动检测的 HTTP 代理；模型请求仍经过项目本地记账服务，原账本、UUID 去重、请求和用量证据均保留。没有修改全局网络环境、Clash 配置或比赛平台路由，也没有关闭 TLS 证书验证。依据 [Python 官方 ProxyHandler 文档](https://docs.python.org/3/library/urllib.request.html#urllib.request.ProxyHandler)。

本次只调整出站连接方式；仍采用原来的传输故障停止策略，不把直连解释为已完成网络重试与状态恢复重构。检查覆盖存在环境/系统代理时实际 HTTPS 连接目标仍为 `api.deepseek.com`、没有代理隧道、全局 opener 与环境变量不被修改，以及比赛路由兼容。另以无密钥 GET `/models` 得到 HTTP 401，确认直连与 TLS 可达，模型生成请求为 0；[连接证据](../../runs/deepseek-direct-20260913/direct-connectivity.json)。

本次新运行使用源码 `6f1558a288ac33f28505f69ff6de0218c48dea734805119e78bc588d820b59f6`，账本从第 5,706 条之后追加，保留历史那一笔未知用量原状。只启动 `000`、种子 3001、四主体、12 个固定问题、`deepseek-flash`，每 5 分钟监控，异常时停止分析，不自动故障恢复；费用继续只记录。[冻结及授权](../../runs/finite-deepseek-direct-20260913-preflight/authorization.json)。

### 当前状态：修复版真实 000 已停止（2026-09-13 19:22）

用户在修复验收后明确授权开始一次新真实 `000`，并要求定时检查、发现异常时中断分析。已于北京时间 **19:15:25** 从初始状态启动，使用 `deepseek-flash`、修复版 `corrective-feedback-1`、四主体、12 个问题、种子 3001；源码与上一节验收版本一致。原账本从第 5,345 条之后追加，授权 `finite-baseline-deepseek-corrected-20260913`，仅一次实验尝试，不自动恢复失败运行。费用和累计请求仍只记录，不设停止阈值。

每 5 分钟监控并汇报，检查真实结算、材料交接、重复操作、截断纠正及技术与证据异常。确认异常后按本次授权停止并保留证据分析；正常等待、单次成功纠正或正常分段接续不作为异常。该监控属于外部运行检查，不进入主体提示。若因行为异常中断，结果标记为未完成，不能报告 token 效率结论。

[新启动记录](../../runs/finite-deepseek-corrected-20260913-preflight/launch.json)、[启动核验](../../runs/finite-deepseek-corrected-20260913-preflight/startup-verification.json)、[运行状态](../../runs/finite-deepseek-corrected-20260913-real-000/batch_status.json)、[冻结授权](../../runs/finite-deepseek-corrected-20260913-preflight/authorization.json)。历史两次停止运行及下面的修复验收保留各自阶段身份，不拼接进本次结果。

本次运行在 **19:22:16** 因传输故障自行停止；五分钟监控已确认控制器和 Ray 全部退出、在途为 0，随后暂停监控，没有重启。实际已结算 **7 轮、解决 2/12**，工程物理生效和验收均为 0；第 8 轮已有三个主体提交但未统一结算。控制器 committed_steps=0 是尚未完成首个 20 轮分段，不代表没有执行；partial_failure 保存状态不据此认定可安全恢复。

[本次停止与诊断](../../runs/finite-deepseek-corrected-20260913-preflight/monitor/20260913T1122-stopped.json)：361 次请求中 360 次 HTTP 成功，1 次传输失败且用量未知；已知输入 4,489,476、输出 73,783，已知合计 **4,563,259 token**，完整 T_system 仍未知。未出现 length 截断，费用与请求数上限均未触发。失败发生于 actor 4、零起算 round 7，请求用时约 5.12 秒，未耗尽 600 秒配置等待。

失败的 502 是本地代理对 URLError/TimeoutError/ConnectionError 统一生成，并非上游实际 HTTP 502 的证据。代理没有持久化具体底层异常及 reason，因此不能在现存证据中定位是本机网络、中间链路还是提供方故障。[零收费故障注入](../../runs/finite-deepseek-corrected-20260913-preflight/monitor/transport-probe.json)确认连接与超时产生相同记录，JSON 解析失败则属于另一分类；参照 [Python 官方异常说明](https://docs.python.org/3/library/urllib.error.html)。这是已确定的诊断信息缺口，不能凭当前证据宣称某一方网络有故障。主体仍有重复读取现象，但本次直接停止原因是传输失败；未修改冻结代码、未自动恢复或重发未知请求。

后续只读调查从 Clash/mihomo 原日志补出了故障阶段：[网络追查](../../runs/finite-deepseek-corrected-20260913-preflight/monitor/network-followup.json)与[限定 DeepSeek 的日志摘录](../../runs/finite-deepseek-corrected-20260913-preflight/monitor/deepseek-network-excerpt.json)。19:22:13.633187，python3.12 经本机代理按 DIRECT 规则连接 `api.deepseek.com:443` 时，两个解析地址均报 TCP `i/o timeout`；账本该失败请求结束于同秒 .633628，时间差不足 1 毫秒。并行另一请求在此期间成功，因此不支持“整个 DeepSeek 服务或网络全面不可用”的判断。实际链路经过继承的本机 HTTP 代理，DIRECT 表示该代理直接连接目标，并不表示 Python 绕过代理。该连接约 5 秒就失败，不受模型层 600 秒等待设置保证。

这补强了先前因项目异常日志不足而无法确认的原因：触发点是出站连接建立失败；全实验停止则由项目对传输异常的全局 fatal 策略决定。不能把本次停止归因于模型协作失败或截断修复失效，也不能把 IP 连接失败直接等同于 Clash 软件自身有 bug。项目仍需记录脱敏后的底层异常和连接阶段，并区分发送前失败与发送后状态不明，才能合理设计同轮重试/续行；本次调查未修改代码、网络配置或原账本，没有重启或收费调用。

### DeepSeek 官方路由与新基准（2026-09-13）

用户因比赛网关响应慢，授权使用本人的 DeepSeek 官方账户启动一次新的真实 `000`，并明确模型名为 **`deepseek-flash`**。公开路由为 `https://api.deepseek.com/v1`（与官方 base URL `https://api.deepseek.com` 等价的 OpenAI 兼容前缀）；当前官方文档将该模型名对应至 DeepSeek-V4.1-Flash。固定思考关闭、输出上限 16384、上游 600 秒、客户端 660 秒。四主体、12 个问题、种子 3001、业务提示、规则和上一节接口修复均沿用；本次不同时运行其他政策组。

`provider_route` 与模型名一起绑定请求配置、运行清单、授权和原账本。官方 `LLMClient` 仍经原本地代理，代理只向所选上游转发；不自动切回比赛平台，不重新选择主体行动。旧版本未指定 provider 的清单继续按原比赛路由解释。切换提供方及模型标识改变了实验配置，不能把已停止旧运行拼接为新基准或把后续差异只归因于接口修复。

密钥保存在独立本地 `.env.deepseek`，权限 `0600`，不写入研究文档、主体输入或审计。Git 忽略秘密文件；源码冻结和同步选择同时排除 `.env*`、私钥文件及符号链接。源码 ZIP 以清单生成，已对实际密钥做仅输出通过/失败的内容检查。依据官方 [模型与价格说明](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)及用户截图冻结模型名；保留官方 AgentSociety2 2.8.7 客户端和执行接口。

费用继续**只记录，不按金额或请求数中断**。原账本从第 4,934 条之后追加，未重置历史。账本采用高峰未缓存输入 2 元/百万、输出 8 元/百万作统一上界估算，明确没有扣除缓存及空闲时段折扣，不能当作实际扣费；原始回复 `usage` 保留缓存数据，真实费用须用适用时段和缓存分类复核或核对平台账单。研究指标仍为全部输入加输出 token，缓存输入不扣除。

[新路由冻结与授权](../../runs/finite-deepseek-20260913-preflight/manifest.json)、[隐私与路由检查](../../runs/finite-deepseek-20260913-preflight/privacy-and-route-check.json)、[离线验证目录](../../runs/finite-deepseek-20260913-route-checks/)。当前状态：真实 `000` 于 **18:19** 启动、**18:26 因输出截断停止，未完成**；实际请求及响应模型均为 `deepseek-flash`。启动前最终离线套件 **473 项通过**。18:20:33 快照已有 91 次成功返回、2 次在途、0 次接口失败，已返回请求耗时中位数约 1.02 秒；这是启动样本，不代表完整运行速度或业务效果。主体随后进入第 1 轮（零起算）；完整任务尚未完成。[启动核验](../../runs/finite-deepseek-20260913-preflight/startup-verification.json)与[实时批次状态](../../runs/finite-deepseek-20260913-real-000/batch_status.json)。原五分钟监控切到本次运行后，于确认实验停止且请求排空时再次暂停。启动最初被自动审批以外发敏感数据疑虑拦截；补充[虚构材料来源及输入边界证据](../../runs/finite-deepseek-20260913-preflight/egress-review.json)后，同一命令复审通过，首次拒绝没有产生请求或实验尝试。

### 官方 DeepSeek 运行中断诊断（2026-09-13）

本节为用户要求的**离线分析**，不修改冻结运行代码、不重启或恢复、不新增收费请求。基准已结算 5 轮，完成 2/12 个局部问题；专项 P:1 已调查、拟案、发出评审请求，根因修复、工程和验收均未完成。411 笔请求均收到 HTTP 200，一笔模型输出被截断；输入 7,092,392、输出 81,888，T_system 为 7,174,280。缓存命中输入 6,337,408、未命中 754,984，全部调用在周日空闲时段，按截图费率计算约 1.20928416 元（非账单）；账本原上界估算 14.839888 元不回写。无在途、无未知用量。包含 partial_failure 的保存状态不视为可直接恢复的干净检查点。

[诊断证据与假设判读](../../runs/finite-deepseek-20260913-diagnosis/diagnosis.json)及[离线回放程序](../../runs/finite-deepseek-20260913-diagnosis/replay_failure.py)：

- **已证实的直接中断链**：设施部门（actor 3）零起算 round 5 的请求返回 `finish_reason=length`，输入 24,744 token，输出恰为 16,384 token，没有原生工具调用。`NativeClient._call` 将其提升为永久共享 fatal_error，主体的连续执行机制无法再继续；驱动层随后结束本次运行。真实回复回放两次稳定复现；删减成一个字符仍复现，仅将结束标记改为 stop 的对照不触发永久失败。这复现的是截断后的程序处理，不是离线重新生成模型回复。
- **已证实的重复现象**：失败轮中 MEMORY.md 被重复读取 8 次，返回内容完全相同，全部回执仍在最终输入；8 次全文与其他回执合计约 30,848 字符。最后一条回复在评审与接受协作两个候选之间反复犹豫，出现至少 9,301 字符的逐字重复片段。不是一份有效长方案自然写满，也不是一直等网络。单纯加大输出上限可能延长重复，尚不能证明能解决问题。
- **排除的解释**：当前回执没有再次被丢弃；401 次主体调用在各主体各轮中均有不同输入哈希。411 次实际代理正文哈希均可由冻结消息、工具和参数准确重建，thinking=disabled、max_tokens=16384 确已发出。接口不暴露服务端内部计算，不能据此推断服务端隐藏实现；英文分析文本出现在普通 content 中，不构成思考模式开启的证据。
- **错误报告缺陷**：`tools/v3_driver.py:failure_details` 未覆盖 NativeClientError，直接传入已知截断异常也返回 None；Ray 结果又被转成通用 RuntimeError。由此最终控制器报告 unclassified_failure，掩盖了原请求中已经明确记录的截断类型。

对照[官方文档](https://agentsociety2.readthedocs.io/en/latest/agents.html)和安装源码 `agent/base/agent.py`、`agent/person_prompt.py`：官方默认也使用重新组装的 system/user 消息；不能将没有标准 assistant/tool 历史单独判为框架误用。官方 Person 提示展示最近 8 条观察，并包含工具输出和推进说明；本项目为排除研究元信息、保持 wait 合法而整体替换了提示，当前把全部工具回执全文加入 context。该差异及重复记忆全文明确增加输入负担，但它们对模型循环的因果贡献尚未通过真实对照确认。也没有找到要求重复读取同一文件的指令。

后续修复优先级应为：区分已返回截断与未知网络结果，在不执行残缺行动、不推进本轮、不补造选择的前提下设计同轮纠正；完整保留错误类型；整理重复回执呈现并保留原审计及材料访问；最后用最小真实链路验证行为。不得以放松字段校验、自动替模型选择或只抬高 token 上限当作已经修复。473 项离线通过证明已有程序检查通过，不能证明真实模型不重复或必能完成；这次回放补出了原来未处理好的真实响应模式。以上为修复前的诊断结论；用户随后授权依据官方文档修复，实施及验收见下一节。

### 官方 DeepSeek 截断处理修复与离线验收（2026-09-13）

已按用户要求完成本地修复。依据 [AgentSociety2 Agent API](https://agentsociety2.readthedocs.io/en/latest/api/agent.html)、[主体扩展文档](https://agentsociety2.readthedocs.io/en/latest/agents.html)及本机 2.8.7 源码，继续通过公开消息组装钩子、官方 Skill 和官方 ReAct 执行；没有修改预装框架或复制执行循环。[DeepSeek 请求接口](https://api-docs.deepseek.com/api/create-chat-completion/)将 `length` 定义为达到生成或上下文限制，不能把这种残缺回复当作有效完整行动。**本次修复解决已证实的程序中断链；是否消除真实模型的重复生成仍未验证。**

- **同轮纠正代替永久客户端失效**：新配置 `interaction_policy="corrective-feedback-1"` 下，已返回的主体截断回复完整存证及计量，整条回复均不执行；向该主体反馈当前真实提交状态，再进入官方循环继续本轮。原 UUID 不重发，新纠正调用另有 UUID。提交前和提交后发生截断都已覆盖，不会重复提交、丢失既有提交或提前推进世界。未知网络结果、存储及证据故障仍单独处理，不能等同于已经收到的截断回复。
- **重复正文只呈现一次**：完全相同的工具回执以 `same_result_as` 指向本轮首次完整正文，保留每次操作、参数、成功状态和顺序；发生变化的结果仍完整展示。原始审计不删减，合法材料保持可查。Skill 说明已给出的记忆和回执可直接使用，按需要查询缺失或变化的信息，并通过完整工具调用表达选择；不强制派单，也不要求主体节省 token。
- **错误及计量保留事实**：NativeClientError 的类型穿过驱动和 Ray 失败封装。截断虽未执行，实际输入与输出仍计入 T_system，并与原账本和官方计数核对。独立审计要求截断原回复、纠正边界和无执行记录相互匹配；缺记录或篡改标记均拒绝。

冻结源码 SHA-256：`4f56dfadfd576edd663fec744de14145d418215cae768fe4eec089fc8ef9fe4d`。新标识绑定本次请求及呈现策略；历史清单仍按原标识核验，旧运行不拼入新版本。模型仍为 `deepseek-flash`，关闭思考、输出上限 16384，不新增费用、请求数、纠正次数或业务轮数硬停。

[修复验收汇总](../../runs/finite-deepseek-20260913-fix/verification.json)、[修改差异](../../runs/finite-deepseek-20260913-fix/implementation.diff)与[冻结清单](../../runs/finite-deepseek-20260913-fix/manifest.json)：

- 原失败回复离线回放：保留 `length` 标记仍会拒绝该残缺响应，但不再造成永久客户端失效；不是重新生成模型内容。
- 新增 6 项回归检查通过，包含官方 PersonAgent 循环中提交前后截断、残缺工具不执行、四主体结算屏障、历史兼容、错误分类、重复回执引用，以及用量和证据缺失反例。[完整离线套件](../../runs/finite-deepseek-20260913-fix/offline-tests-full.log) **479 项通过**。
- 原轨迹的 20 条工具回执全部保留，16 条重复正文改为引用，序列化回执区由 30,741 字符降至 10,972 字符；这是这一片段的字符数，不是实测 token 节省率。
- [官方 Ray 固定行动验证](../../runs/finite-deepseek-20260913-fix/offline-ray/finite-000-s3001-deepseek_official/verification.json)在第 **51 轮**完成：12/12 初始问题解决、2 项根因工程物理生效且行政验收完成，20/40 轮正常检查点接续通过。该序列用于证明程序存在合法完成路径，不代表真实模型自主完成。

本次新增收费请求 **0**；原账本仍为 5,345 条，原失败运行的请求、驱动及控制器证据哈希未变。原真实 `000` 仍为未完成，未恢复其 partial_failure 状态，也未重新启动收费实验。下方较早接口修复的验收数字保留其历史身份。

### 本次停止与接口修复（2026-09-13）

设施部门在零起算第 10 轮反复查询同三份材料、读取 `notes/` 目录。该轮留下 278 次已返回决策记录，没有记忆整理调用。诊断和方案原文确已进入下一次输入；不是上下文超限，也不是一直在压缩记忆。问题在于项目上下文适配层过滤了成功的环境操作回执、未保留工具请求参数；同时官方 `read` 对目录返回空字符串成功，项目接口没有给出目录与文件的纠正反馈。它们是可复现的接口缺陷，但不能仅凭离线结果断言已解释真实模型全部循环行为。

用户要求终止后，先暂停该实验的决策工作进程以阻止新增请求，待原代理排空，再向所属驱动发送中断。控制器和 Ray 已退出，五分钟监控已暂停。控制器原件将 SIGINT 记为 technical_failure；[用户停止记录](../../runs/finite-v36-20260913-continuous-preflight/user-stop.json)明确其人为终止性质，没有将原始失败记录改成完成。终点为已结算 10 轮、局部问题解决 3/12、共同根因修复和工程验收未完成，未达到首个完整 20 轮分段检查点；不得把部分工作区当作完整可恢复检查点。

[停止核算](../../runs/finite-v36-context-fix-20260913/stopped-run.json)：本次 1,054 次请求，输入 16,634,834 token、输出 430,737 token，合计 **17,065,571 token**；在途及已结束未知用量均为 0，原账本前 3,880 条未变。按原固定费率、不扣缓存折扣的估算为 **20.9955696 元**，不是平台实际扣费。缓存输入仍计入研究 token 指标。原运行 128 个文件的[封存哈希](../../runs/finite-v36-context-fix-20260913/stopped-evidence-hashes.json)与受影响文件的修复前源码均已保留。

修复限定在主体接口：通过官方 ReactToolResult.data 传递已经校验的主体请求参数，并在下一次官方循环输入保留成功和失败的操作记录；成功材料查询列明已返回材料编号，原文仍只在合法材料区展示一份，不重复候选集合。读取目录时提示使用 list 后读取具体文件；不存在的文件明确报错，真实空文件仍可合法读取。官方循环、业务选择、权限、材料送达、每轮结算和 token 口径不变；不增加次数硬停或强制行动。

[修复前失败用例](../../runs/finite-v36-context-fix-20260913/red-tests.log)与[修复后通过用例](../../runs/finite-v36-context-fix-20260913/green-tests.log)经过实际官方工具派发和 ReAct 输入链路；[原始轨迹回放](../../runs/finite-v36-context-fix-20260913/real-trace-replay.json)确认成功查询记录重新进入上下文。历史回执不补写新字段；新参数传递由新链路回归检查验证。该修复改变了主体实际输入，停止前后不能拼成同一冻结版本的正式基准。真实模型修复后的自主行为尚未收费验证。 修复版完整官方 Ray 假模型轨迹在第 **51 轮**完成，20/40 轮保存与正常续行及独立核验通过；[修复验收汇总](../../runs/finite-v36-context-fix-20260913/verification.json)。本次修复没有新增收费请求，原运行封存哈希和账本均保持不变。完整离线套件 **469 项通过**（[日志](../../runs/finite-v36-context-fix-20260913/offline-tests-full.log)）；其中新增 2 项针对本次缺陷，已有提交后回执测试改为同时检查成功回执与两条失败回执，不放松一次有效提交约束。

### 本次控制修订：费用只记账，ReAct 分段后继续

用户明确要求费用只记录、不按额度强制中断后，执行策略新增独立冻结标识 `execution_policy="continuous-finite-1"`。原 `native-request-profile-2` 及未批准的 2000 次 / 30 元草案保留历史身份；新的执行清单使用同一业务协议与模型请求参数，但不再受这两个费用阈值约束。

- **费用记录**：原账本逐请求记录 UUID、输入/输出 token、估算费用与未知用量。`cost_control_mode="record_only"`，请求数与金额上限均为 `null`；不把阈值设成一个很大的数字，不通过新账本或零费率变相绕过计量。
- **ReAct 续行**：官方配置仍为每段最多 10 次内部迭代。薄层公开 `run_react_loop` 调用官方实现；一段结束仍未有效提交，就在同一 tick、同一仿真轮、同一主体状态与观察列表上继续下一段。不重启 `PersonAgent.step`，不提前整理阶段性兜底记忆，不替主体选择 `wait`。
- **完整回执与修正**：合法回查材料、TODO、字段错误反馈和原始响应保留。提前 finish 但没有业务提交、或已经返回的 finish 参数格式错误，给予准确反馈后继续；格式有误的原始选择不会被悄悄解析为合法行动。每次段间续行单独留证，独立核验不能只看最终一次提交。
- **停止边界**：不因为花费、请求次数或 ReAct 段数达到阈值而终止。任务完成、用户主动停止，或真实接口/存储/身份与证据完整性故障是不同情况。尤其状态不明的上游请求不能盲目重新付费发送；仍保留 UUID 去重和错误证据，不把技术错误伪装成业务等待。

官方 2.8.7 的 `max_react_turns=10` 是默认配置，不是针对本研究验证过的充分迭代数。依据安装源码 `agent/base/agent.py` 的配置加载和公开 `run_react_loop`、`agent/person.py` 的 step 生命周期核对：官方循环可复用传入观察列表，Memory.after_step 在该调用完成后才执行。该薄层续行属于本项目的研究执行适配，**不声称框架原生提供了无限迭代模式**。框架接口参考 [官方 Agent API](https://agentsociety2.readthedocs.io/en/latest/api/agent.html)。

费用由程序逐笔记录，助手读取记录汇报；没有将“助手必须持续在线盯住金额”作为运行条件，也没有新建定时监控任务。没有证据可把此前所有失败都归因于费用阈值：历史还包含 SDK 参数转发、重复操作处理、输出契约与提示信息边界等问题；这些诊断证据不等于政策效果证据。

### 固定工作量与完成条件

四主体、种子 `3001`、固定 12 个初始问题。`workload_mode="finite"`、`horizon=null`；关闭随机新增、复发与重复投诉，不设有限劳动、资金、施工队配额、材料过期和立项冷却。调查、职责权限、专业评审、施工和投运的技术先后关系，以及材料实际送达顺序保留。已有施工授权手续仍存在，但不再限制可用资金；技术投运时滞保留，不能仅勾选待办或提交动作就声称完成。

完成同时要求：初始个案必要修复和结案、共同根因对应设施修复、承担修复工程的必要行政验收。`completion_status` 只供环境结束控制与外部审计，不把隐藏真实根因或全知答案送给主体。误立项目可以根据调查撤销；重复提出、合并、取消或修订均由主体依据合法材料决定。等待合法，程序没有强制推进、自动遍历或真实模型失败后的脚本兜底。

[当前修复版离线冻结清单](../../runs/finite-deepseek-20260913-fix/manifest.json)只包含 `finite_baseline` 的 `000`。工厂与严格校验位于 [finite_protocol.py](../../runs/official-refactor-20260913/before-source/policy_v3/finite_protocol.py)。下方历史 `design_protocol.json`、`design-8.json` 与 48/96 项诊断安排不再是当前实验协议；它们保留历史身份供旧证据解释。

### 官方组件与必要适配

依据官方 [Agent API](https://agentsociety2.readthedocs.io/en/latest/api/agent.html)、[环境 API](https://agentsociety2.readthedocs.io/en/latest/api/env.html)、[Society API](https://agentsociety2.readthedocs.io/en/latest/api/society.html)，并核对本地 2.8.7 实际源码与调用契约：

| 环节 | 当前实现与职责 |
|---|---|
| 主体与认知 | 薄层 `NativePolicyOfficer(PersonAgent)`，继承官方 step/ReAct；使用官方 Memory、TODO、Skill、追踪及工作区保存，不复制执行循环 |
| 主体输入 | 通过公开 `build_react_messages` 组装完整业务上下文，替换默认人物、世界说明和工作区路径；职责及通用流程由官方 Skill 提供 |
| 路由 | 官方 `RouterBase` 子类，经 `EnvRouterProxy` 确定性调用 `EnvBase` 注册工具；保留 Ray 构造与生命周期转发，不调用模型抄写选择 |
| 调度与结算 | 官方 `AgentSociety` 与 Ray；四主体各有一次有效提交且无技术异常才统一结算，外层检查官方内部捕获的失败 |
| 请求与记忆整理 | 官方 `LLMClient` 的薄层用途/配置/审计适配；记忆整理保留官方 Markdown 格式、选取逻辑与持久化，只替换默认模拟人物及虚构身份示例 |
| 预算与证据 | 原账本、原代理、请求 UUID 去重；保存实际消息/工具/原始返回、官方计数差额、提交、送达、结算与检查点；最终独立核验通过才发布完成 |

统一业务工具为观察、回查、提交。初始观察不调用模型；模型通过 `ask_env(instruction, payload)` 明确选择查询或提交，运行时绑定身份、轮次和当前材料。提交必须有 `candidate_id`、非空 `reason`，立项另有 `analysis`；错误返回具体字段回执，程序不补造选择、理由、引用或主题。

每主体每轮最多一次有效业务提交。移除项目额外的两次回查、一次格式修复、必须单独 finish 限制；每段沿用官方最多 10 次 ReAct，仍未提交则在同一主体轮次继续。提交后再操作返回真实“已提交”状态。官方 finish 在循环内部处理，不会产生普通 dispatch 回执；核验按这一实际行为检查，并要求此前已有真实提交。尚无有效提交时继续处理但不推进世界；真实超时、记忆保存异常或其他技术失败不推进世界；合法业务拒绝作为模拟结果结算。

### 完整 prompt 与信息边界

下面四主体链接为本次修复代码在官方 Ray 离线链路中实际组装的完整首轮 messages 与工具定义，不是另外编写的提示摘要。A/C 与个人记忆整理未在本次修改，保留其既有输入示例。后续输入随合法观察、回执、记忆和待办变化；完整逐轮输入保存在各主体 `native_decisions.jsonl`。A/C 是同一固定任务材料的输入示例，000 不调用 A/C。

| 对象 | 信息与职责边界 | 完整输入 |
|---|---|---|
| 受理派单员 | 诉求原文、职责目录与合法送达反馈；受理、派单、跟进 | [完整 prompt](../../runs/finite-deepseek-20260913-fix/prompts/actor-1.md) |
| 供水办理部门 | 本部门分工、调查与交接材料；供水调查、作业、评审及投运 | [完整 prompt](../../runs/finite-deepseek-20260913-fix/prompts/actor-2.md) |
| 基础设施办理部门 | 本部门分工、调查与交接材料；设施调查、作业及专业评审 | [完整 prompt](../../runs/finite-deepseek-20260913-fix/prompts/actor-3.md) |
| 专项负责人 | 合法诉求、本人调查、收到的部门反馈；跨事项调查、修复组织和验收 | [完整 prompt](../../runs/finite-deepseek-20260913-fix/prompts/actor-4.md) |
| A 服务 | 同批合法材料的摘要、部门建议与依据，不决定派单 | [完整示例](../../runs/finite-v36-20260913-continuous-preflight/prompts/service-A.md) |
| C 服务 | 合法材料中的关联假设、证据缺口与调查建议，不读取真实根因 | [完整示例](../../runs/finite-v36-20260913-continuous-preflight/prompts/service-C.md) |
| 个人记忆整理 | 仅整理本人的既有记录，保留事实与判断的区别，不改变环境事实 | [完整 prompt](../../runs/finite-v36-20260913-continuous-preflight/prompts/memory.md) |

主体输入排除研究目的、实验组、政策效果预期、token 价格/预算、模型参数、诊断标签、校准说明、源码哈希及宿主机路径。候选仅一份；当前事项、收到材料、已结算反馈分列。流程说明明确派单启动调查、确认承担分工、诊断后拟案、拟案后评审。当前任务目录持续可查，目录不等于已经阅读原文。

文件工具只可读本人 MEMORY.md、TODO.json、memory/episodes.jsonl 与 notes/；直接写入限 notes/，TODO 经官方工具管理。拒绝绝对路径、上级目录、符号链接越界、AGENT.json、配置、其他主体与审计文件；技能访问仅限已批准内容。测试覆盖实际工具返回和文件边界。材料字段按所属结构过滤，原文或候选参数中同名的合法业务字段不会被递归误删。参见 [实际输入边界核查](../../runs/finite-v36-20260913-continuous-preflight/prompt-boundary-audit.json)；关键词检查只是已知污染回归，不能证明未来模型永远不会编造信息。

### 政策与统计口径

A 比较原文办理与摘要/分办建议辅助；B 比较人工联系、回复、交接与正式联办、自动派发、授权共享；C 比较主体自行分析与跨事项分析辅助。C 的作用通过固定任务中的共同根因调查和修复体现，不靠持续制造新问题。

`T_system = Σ(实际请求 input_tokens + output_tokens)`，从初始化至任务完成，纳入主体决策、记忆整理、A/C 与其他运行调用。缓存输入照计，思考 token 已属输出不重复相加。按请求 UUID、用途、主体和轮次分列，与官方计数及原账本对账；失败的已知用量计入，未知用量保持未知。确定性路由不调用模型，其实际 token 为零。

只有完整完成、证据通过且用量齐全，才计算相对真实 `000` 的 `1 - T_system_policy / T_system_000`。未完成运行报告剩余任务与累计消耗，不判断高效。比较必须同一代码、业务提示、任务、模型、记忆参数和完成条件；修改共用机制或提示后须重新建立基准。单种子只作描述性比较。

当前 `native-request-profile-2` 统一关闭思考、`max_tokens=16384`、temperature=0.2，上游 600 秒、客户端 660 秒；不再做思考配置矩阵。配置、工具与源码冻结只留在运行控制和审计层。历史 profile-1 继续按原配置核验，旧检查点不得恢复为新运行。

### 停止前版本的离线验收与未验证边界

[控制修订核验](../../runs/finite-v36-20260913-continuous-preflight/control-change-verification.json)覆盖超过旧费用/请求阈值仍可继续、官方主体跨 10 次边界后在第 13 次调用提交、同轮材料和 TODO 保留、格式纠错与异常分类。当前冻结源码为 `9b7b382f0096e83c54fc4b9ec12ff06943d90b595b01059995da31c1ef516c3f`；[记录模式运行准备](../../runs/finite-v36-20260913-continuous-preflight/authorization-proposal.json)请求及费用上限均为 null，不是新收费运行的开始回执。

**最终冻结版本：467 项完整离线检查通过；完整官方 Ray 演练在第 51 轮结束，204 个主体轮次、独立结算重放及完成核验通过。** 20、40 轮的干净检查点均成功恢复，最后一段提前在 51 轮完成。408 次主体假模型响应、4 次记忆假模型响应均有完整输入记录；实际 API 请求 0 次，原账本 3880 条保持不变。

| 离线存在性见证结果 | 数值 |
|---|---:|
| 初始问题已解决 / 初始问题 | 12 / 12 |
| 终点未解决问题 | 0 |
| 新增 / 复发 / 重复投诉 | 0 / 0 / 0 |
| 累计未解决负担（问题轮） | 322 |
| 立项 / 依据调查撤销 | 4 / 2 |
| 建成 / 成功投运 / 物理生效 / 行政验收 | 2 / 2 / 2 / 2 |
| 共同根因对应设施完成修复 | 6 |

这些数值来自 [离线指标](../../runs/finite-v36-20260913-continuous-offline/finite-000-s3001/metrics.json)，没有政策效果含义。实际 token 为零只表示未调用 API，不是“零 token 完成”的效率结果。

最终验收状态见 [离线汇总](../../runs/finite-v36-20260913-continuous-preflight/offline-verification.json)与 [完整独立核验](../../runs/finite-v36-20260913-continuous-offline/finite-000-s3001/verification.json)。官方 Ray 链路用固定合法动作作为存在性见证；真实执行路径完全不调用这个脚本。见证只回答“任务可合法完成”和“执行/保存/审计链路能完成”，不能回答真实模型会不会完成。

已有检查覆盖超过 60 轮继续等待、专项调查延迟至 90 轮后仍可完成、全部个案关闭仍未修复共同根因、物理生效但尚未验收、越权/伪造身份、重复提交、延迟/异常屏障、历史错误输出拒绝、记忆与 TODO 隔离及恢复、官方客户端本地 HTTP、预算重试去重、失败/未知用量、原账本绑定与独立重算。完整测试命令为 `python -B -m unittest discover -s tests -v`；本地假服务需要允许 loopback。

本轮验收修正了两处证据边界：官方 finish 不走普通 dispatch，核验器不得要求不存在的执行回执；记忆整理默认提示中的虚构人物示例可能回流到主体，已在消息适配层替换。中间证据 [首次演练](../../runs/finite-v36-20260913-offline/batch_status.json)与 [记忆模板修订前的演练](../../runs/finite-v36-20260913-final-offline/batch_status.json)保持原样，按原源码身份解释，不修改为最新版本证据。首次演练在最终审计阶段停止；其中旧版行级 complete 不代表独立核验通过，此发布顺序现已修正并有回归检查。

尚未验证真实模型的全任务完成能力、真实调用数/费用、长期记忆质量及政策 token 节省。全部局部维修、共同根因物理生效、行政验收与最终完成分别报告；真实模型持续等待时保留轨迹、调查原因，不加强制行动指令。

### 已停止的真实 000 与后续边界

用户已指定费用只记录，不再设置 2000 次请求或 30 元的中断上限；此前额度草案未执行，已由记录模式取代。用户随后明确要求“开始一次真实000实验吧”，已据此记录[本次授权](../../runs/finite-v36-20260913-continuous-preflight/authorization.json)，启动一条真实 `000` 基准，从相同初始状态到完成，不自动启动其他政策组，也不因一次失败重建整场实验。

同一批次控制器每 20 轮保存干净检查点，分段保存和正常续行不是研究终点。发生真实技术故障时保留当前完整日志、部分失败状态和上一个干净检查点；部分工作区不能被误标为可直接恢复的完整状态。真实 API 的上下文、输出容量和网络故障并不会因为取消费用限制而消失，不能承诺任何错误下都无限执行。

启动前源码与冻结版本一致，原账本 3,880 条历史记录及前缀核验通过，没有未结算请求或本阶段既有尝试。该次运行已按用户要求停止，终点和接口修复见本文顶部。运行期间使用独立后台控制器与防空闲睡眠；费用只记录，单条实验尝试，不设置费用、请求数或总轮数终点。真实 `000` 完成且证据通过后，才按对应授权进入其他七组。

---

## 历史：2.8.4 原生迁移及旧实验记录

以下内容保留当时版本、收费情况与发现；其中“当前”“最新”等表述仅指各历史阶段，不覆盖上面的 2.8.7 有限任务协议。

### 历史实现：官方 AgentSociety2 原生迁移（2026-09-13）

本次按已批准计划迁移执行与认知接口，使用当前安装的 **AgentSociety2 2.8.4**。主体调用官方 `PersonAgent.step` 和 ReAct 循环，启用官方记忆、TODO、技能及工作区保存；环境路由调用官方 `ReActRouter`，请求使用官方 `LLMClient`，整轮仍由官方 `AgentSociety` 和 Ray 执行。安装包没有修改。政策、候选、材料权限、行动成本、资源、物理机制和消息顺序沿用迁移前代码；旧模型结果不能并入新架构比较。

**最小网关 4/4 通过；六个原生链路用例完成 2 个，在第 3 个因重复提交停止，后 3 个未启动，最小验证整体未通过。已发现并离线修复提交后反馈自相矛盾的问题，434 项完整离线检查通过；该修复尚未收费复验。48 项诊断、C 服务阶段、真实短轨迹和八组均未启动。** 记忆与执行接口作为整体变动解释，不承诺模型轨迹相同，也不按解决率选择推理配置。

### 补充核查：主体输入混入研究层元信息

用户指出“被仿真的对象不需要知道 meta 级别的信息”后，核对最近最小链路实际发出的全部 17 次主体、5 次路由、1 次记忆请求的 messages 与工具定义。**17/17 次主体请求含有研究层元信息，当前输入边界不合格。** 这补充了此前仅聚焦程序错误和模型行为的说明；不能把所有停滞或重复提交直接归因于该污染，但也不能据已有小样本声称主体在仅知业务情境的条件下理解正确。

确认混入的内容包括：“这是冻结的单主体合法证据接口诊断”“本研究允许较长计算等待”“角色2职责及成本为未校准假设”“普通与强化物理条件相同”，以及带诊断用例和思考条件名称的宿主机工作区路径。提交回执还暴露 `physical_settlement_available=false` 与诊断类型。来源分别为项目诊断世界描述、官方 Agent Skill、共享 public_rules、官方默认身份/工作区上下文及诊断回执；不只是一句孤立提示的问题。

**这批实际主体消息中未发现 token 价格、API 费用、调用额度或原预算账本数据。** `inspect_cost=1.0` 是调查劳动，`decision_cost=0.1` 是执行非等待业务行动时的仿真劳动成本，不按模型 token 或实际思考时间计费；它们的命名与单位仍应明确。请求参数、原始用量与费用虽记录在审计文件中，不等于进入了模型可见 messages。

主体输入应只保留本人职责、合法材料、当前办理规则、业务资源，以及必要的操作接口说明。实验身份、诊断是否结算、研究修订说明、校准状态、组间比较、模型费用/额度和宿主机路径应留在控制与审计层。此项核查只新增证据和文档，尚未清理提示或启动收费验证。详见 [逐请求边界核查](../../runs/native-v35-chain-20260913-review/prompt-boundary-audit.json)及 [实际完整主体输入样本](../../runs/native-v35-chain-20260913-review/actual-agent-prompt.md)。

### 最新进展：网关通过，原生链路在第 3 个用例停止

用户追加“同意”后，执行 [已批准额度](../../runs/native-v35-sdk-fix-20260913-preflight/user-approval.json)：修复版网关最多 4 次请求 / 0.255591 元 / 1 次尝试 / 0 次恢复，网关通过后继续原定六个链路用例（最多 90 次请求 / 14.598144 元 / 1 次尝试 / 0 次恢复）。收费源码固定为 `0ce9ce7a8b4a1691f9f1ec75405aa9ac715e0287918058e9e8ecb46b5a3e8f6e`。

**网关 4 项均通过。** 两份固定工具输入分别使用关闭思考与开启思考/high；完整工具参数、实际上游请求体哈希、返回及用量逐笔一致。两项开启档均有思考内容，上游接受请求；服务端对 high 的内部实现仍不能独立观测。这只验证请求与工具转录，不能代替流程理解。见 [网关核验](../../runs/native-v35-sdk-fix-20260913-preflight/gateway-verification.json)。

| 原生链路用例 | 实际选择与流程理解 | 结构与结束状态 |
|---|---|---|
| 派单后未调查／关闭思考 | 选择调查，认识到本人已是主办；没有继续等待再次派单 | 无格式修复，明确结束 |
| 派单后未调查／开启思考 | 选择调查，认识到调查启动后续流程 | 提交后又请求回查，被拒；一次修复后明确结束 |
| 接受分工但尚未完成／关闭思考 | 选择向部门 3 报告状态；正确区分接受分工与实际完成，理由与该选择一致 | 提交后又两次尝试查询状态，均在路由前被拒；缺少明确结束，技术失败 |
| 接受分工但尚未完成／开启思考，以及拟案后评审／两档 | 未运行 | 前项失败后停止 |

这些用例经过官方 PersonAgent、ReActRouter 与 EnvBase，使用相互隔离的冻结业务状态。三个已启动用例各只有一次行动进入结算队列；冻结诊断不执行物理结算。两个完成的主体轮次、三个排队回执，都不能表述为实际调查、交接或问题解决。该阶段没有启动新的多轮 AgentSociety/Ray 轨迹。

**发现一个确定的程序错误：首次结构修复无条件附加“尚未提交”。** 第三个用例第一次重复提交被拒后，实际发送给模型的反馈是“Actor already submitted; record memory and finish；尚未提交。修正字段，不补造候选、理由或材料。” 提交状态没有丢失，官方循环保留了原反馈，矛盾来自本项目 `_schema_error` 的固定后缀。第一次重复提交发生在该提示之前，所以不能把所有重复操作都归因于它。

现已按未提交、已提交和只读问答分别生成真实状态说明。已提交后说明不能再回查或提交，可记录个人记忆或待办后调用 finish；仍保留一次共享修复，第二次违规仍停止。未改变候选、业务机制或自动补造行动。回归先在官方循环内复现两种提交后违规及只读错误，共 2 个测试 / 3 处失败，再修复并通过；受影响 9 项与完整 **434 项离线检查通过**。首次完整套件因沙箱禁止本机假服务监听受阻，允许 loopback 后同一套件通过，无收费调用。日志、对账脚本及修复记录集中在 [最小验证核验目录](../../runs/native-v35-chain-20260913-review/)，详见 [修复验收](../../runs/native-v35-chain-20260913-review/offline-fix-verification.json)。

修复后源码为 `18bb3cf5797ffa0364eb7588e1f824e6768c2607a295d723764083313977730b`，相对本次收费冻结仅生产文件 `native_officer.py` 改变；另新增上述回归检查。旧收费证据保留旧源码身份，不能把这次离线通过改标为真实模型修复成功。

**仍未解决：** 两个调查用例都把 `inspect_cost=1.0` 说成资本，实际业务代码扣除劳动；`decision_cost=0.1` 也是劳动。当前公开成本表未为 `inspect_cost` 明示资源单位，这一呈现缺口应在扩跑前处理。真实模型能否在正确反馈下稳定结束、另三项能否通过，以及错误等待是否在其他状态反复出现，尚未验证。两个已完成用例不够选择思考配置，也不能作为政策效果证据。见 [逐例行为复核](../../runs/native-v35-chain-20260913-review/behavior-review.json)。

| 本次授权实际消耗 | API 请求 | 输入 token | 输出 token | 估算费用／元 |
|---|---:|---:|---:|---:|
| 修复版网关 | 4 | 1,644 | 497 | 0.0031656 |
| 链路主体决策 | 17 | 242,628 | 21,708 | 0.3432528 |
| 链路环境路由 | 5 | 3,085 | 850 | 0.0057420 |
| 链路官方记忆整理 | 1 | 1,169 | 122 | 0.0016956 |
| 合计 | **27** | **248,526** | **23,177** | **0.3538560** |

费用按冻结输入 1.2、输出 2.4 元／百万 token 计算，非平台账单；同一请求的官方日志与账本只算一次。原账本由 3853 增至 3880 条，旧前缀未改，无新增未知用量或在途请求；共 2 次阶段尝试、0 次恢复。加上前一次 SDK 失败阶段已发生的 1 次网关请求，原生最小验证累计 28 次请求、0.3544368 元、3 次阶段尝试。见 [逐笔独立核验](../../runs/native-v35-chain-20260913-review/paid-evidence-verification.json)及 [100 个收费工件哈希](../../runs/native-v35-chain-20260913-review/closed-paid-hashes.json)。

本次额度的两次阶段尝试已用完。剩余请求数与金额不自动增加尝试次数；修复后没有再发起收费请求，未恢复失败用例或扩跑后续阶段。

### 前次记录：最小网关因 SDK 参数兼容停止，随后离线修复

以下记录对应追加授权之前的交付时点；其中“尚未验证”“未批准”均指当时状态，后续实际执行以上节为准。

用户“同意最小验证”后，按原方案授权 94 次请求 / 14.853735 元 / 2 次阶段尝试 / 0 次恢复。网关首项（关闭思考的 submit 工具转录）成功，工具名、参数、完整回答与用量均核对一致。第二项开启思考时，AgentSociety 官方客户端所用的 **LiteLLM 1.100.1 在本地拒绝 `reasoning_effort`**；尚未到预算代理或上游，控制器按规则停止。其余两份网关输入及全部六个办理链路用例未启动，因此还不能评价主体是否理解流程。

本次实际 **1 次上游请求、1 次阶段尝试、0 次恢复**，输入 336 token、输出 74 token，按冻结费率估算 **0.0005808 元**（非平台账单）。账本从 3852 到 3853 条，原前缀不变，无新增未知用量或在途请求。SDK 对本地异常的内部两次尝试均未转发第二个请求，不是两次收费。见 [独立核验](../../runs/native-v35-preflight-20260913-verified/gateway-failure-review.json)、[原始结果](../../runs/native-v35-gateway-20260913/report.json)及 [9 个工件哈希](../../runs/native-v35-preflight-20260913-verified/closed-gateway-hashes.json)。

离线复现确认：LiteLLM 按其模型能力表校验 OpenAI 兼容参数，当前模型名未识别 `reasoning_effort`；官方 LLMClient 仍转发 kwargs，预算代理未拒绝该次请求。[LiteLLM 参数说明](https://docs.litellm.ai/docs/completion/input)解释了默认的未支持参数异常；安装源码 `utils.py` 提供单次 `allowed_openai_params`。本次仅在原生适配器为现有 `reasoning_effort` 指定这一允许项，保留 `thinking=enabled`、`reasoning_effort=high`、输出上限和请求体，不使用全局 `drop_params`，不修改预装框架或研究规则。

此前测试缺口是：思考开启配置曾通过结构/假客户端检查，但真正通过官方 SDK 和本地 HTTP 的测试只覆盖关闭思考。已新增开启档的实际 SDK 回归，先复现相同异常，再验证修复后请求体含完整参数、SDK 允许列表本身不外发、重复 HTTP 不重复上游计费。**432 项完整离线测试通过**；修复后没有新收费请求，也未将上一步旧源码的 Ray 结果改标为本次 SDK 修正的实测。

新源码 `0ce9ce7a8b4a1691f9f1ec75405aa9ac715e0287918058e9e8ecb46b5a3e8f6e` 及相同输入、模型配置、费率已 [重新冻结](../../runs/native-v35-sdk-fix-20260913-preflight/preparation.json)，[修复验收](../../runs/native-v35-sdk-fix-20260913-preflight/offline-fix-verification.json)保留复现命令和日志。唯一生产代码差异在 `native_client.py`。上游对开启思考工具调用的实际支持仍未验证，不能因本地透传成功判为整个网关通过。

网关唯一授权尝试已消耗；剩余金额不增加尝试次数。下一步 [追加提案](../../runs/native-v35-sdk-fix-20260913-preflight/retry-proposal.json)为新增一次网关尝试，最多 4 次请求 / 0.255591 元 / 0 次恢复，绑定修正后的源码；通过后才继续原定六个用例及其原请求/金额上限。草案未批准，无新收费执行。以下组件说明仍适用；下文首次离线验收数字与零费用对应重构交付时点。

### 官方组件与项目边界

| 环节 | 当前入口与实现 |
|---|---|
| 主体 | [native_officer.py](../../runs/official-refactor-20260913/before-source/policy_v3/native_officer.py)：薄层 PersonAgent，复用官方循环；原旧实现保留为 LegacyPolicyV3Officer，供 MVE 共享依赖与历史兼容 |
| 职责与流程 | [policy-workflow/SKILL.md](../../custom/skills/policy-workflow/SKILL.md)：官方 Agent Skill；角色公开规则说明、调查/确认/拟案/评审先后、排队与实际执行区别 |
| 路由 | [native_router.py](../../runs/official-refactor-20260913/before-source/policy_v3/native_router.py)：官方 ReActRouter 的 Ray 构造适配及 EnvBase 工具门面；替代 2.8.4 工厂固定生成的 CodeGenRouter，不复制官方循环 |
| 业务 | 保留 PolicyWorld、材料服务及资源机制；路由仅执行主体明确给出的操作和参数，工具回执直接返回 |
| 请求与预算 | [native_client.py](../../runs/official-refactor-20260913/before-source/policy_v3/native_client.py)、[native_profiles.py](../../runs/official-refactor-20260913/before-source/policy_v3/native_profiles.py) 绑定官方客户端；原账本代理按 UUID 去重 SDK 重试，状态未知时停，不重新转发 |
| 持久化与核验 | 完整官方工作区、Memory、TODO、追踪、轮次提交及环境共同提交；[native_audit.py](../../runs/official-refactor-20260913/before-source/policy_v3/native_audit.py) 独立重建工具选择、实际请求体、费用与业务状态 |

身份与轮次由运行时注入。初始观察直接读取合法环境，不调用路由模型；回查及提交每次只处理一个操作，路由 `max_steps=1`。每主体每轮最多两次原文回查、一次业务提交、一次共享格式修复；官方循环最多 10 次迭代。`candidate_id` 与 `reason` 必填，立项额外提供 `analysis`，程序不补造选择、理由或合并主题。等待仍合法。

稳定 `submission_id` 对应排队、实际执行或业务拒绝；下一轮观察提供已结算反馈。记忆和 TODO 是主体记录，不修改业务事实。四主体必须全部明确结束且提交齐全，才推进一轮；观察失败、预算不足、超时、内部被捕获的异常、循环耗尽或缺少明确结束都停止当前运行。合法行动被业务规则拒绝可以结算。检查点缺失、内容改变或不完整时拒绝恢复，旧检查点不能直接迁入。

执行配置版本为 `native-request-profile-1`，冻结框架版本、模型参数、记忆参数、循环上限、工具与技能源码。主体比较关闭思考与开启思考/high，两者输出上限均 16384；路由、A/C、记忆整理固定关闭。温度在思考模式下不作为有效对照参数。上游 600 秒、客户端 660 秒，导入官方客户端前设置并传给 Ray 工作进程；这是计算等待上限，不是仿真时间。主体、路由、记忆与政策服务全部计费并按用途分列；历史 `T_agent` 仍只计主体决策，新全链路费用比较必须同时检查 `all_requests` 和 `complete_token_comparison`，未知用量不补零。

### 离线证据与复现入口

**最终 431 项完整离线检查通过，官方 Ray 的 10 轮 + 恢复 1 轮通过，44 个主体轮次完成且独立物理重放一致。** 四个主体各实际完成一次官方长期记忆整理，恢复后保留摘要及记忆游标；模拟记忆写入失败被官方捕获后，外层仍拒绝完成本轮。详见 [最终验收汇总](../../runs/native-v35-implementation-20260913/release-summary.json)。该次重构离线验收的真实 API 为 0 次、费用 0 元，账本当时保持 3852 条；V3.3 的 532 个原件、后续 60 个探针工件与 54 个轨迹工件哈希未变，安装包 205 个 Python 文件与 RECORD 一致。

最终验收证据集中在 [本次实现核验目录](../../runs/native-v35-implementation-20260913/) 与 [官方 Ray 最终运行](../../runs/native-v35-ray-verified-20260913/)。包含完整离线套件、严格历史坏回复与材料权限、路由改写拒绝、延迟/异常屏障、SDK 重试去重、工作区检查点及独立物理重放。Ray 假模型运行 10 轮后从官方检查点恢复，再运行 1 轮；记忆整理在该过程中实际触发。脚本动作仅用于程序验证，不代表真实模型理解正确或政策有效。

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True python -B -m unittest discover -s tests -v
# 下列命令必须使用一个尚不存在的新输出目录；仅假模型、零收费调用。
LITELLM_LOCAL_MODEL_COST_MAP=True python -B tools/check_native_runtime.py --output runs/<new-offline-check> --steps 10
```

正式结果仍分别计算初始问题解决、复发、未解决负担、工程建成、投运、物理生效和行政验收。云端尚未同步或重跑；本地包版本、离线链路、真实 API 和模型行为分别核验。同步清单含新增模块与技能；原始预算账本与历史证据保留，失败离线试验亦不覆盖。

### 冻结诊断与下一步预算

[冻结准备清单](../../runs/native-v35-preflight-20260913-verified/preparation.json) 与 [文件哈希](../../runs/native-v35-preflight-20260913-verified/freeze.json) 包含两份网关输入、三份历史失败状态、六类诊断情景、C 服务历史/留出材料和四条轨迹初态。问答与自主决策使用独立主体工作区，答案不进入决策上下文。短用例调用官方主体、路由和环境；其冻结环境只验证决策与排队回执，不冒充真实多轮物理结算。

| 阶段 | 实验任务 | API 请求硬上限 | 金额上界/元 | 进入条件 |
|---|---:|---:|---:|---|
| 网关 | 4 | 4 | 0.255591 | 新授权并确认价格；关闭/开启思考分别测试两份输入 |
| 最小官方链路 | 6 | 90 | 14.598144 | 网关技术核验通过；三种失败状态各两种思考配置 |
| 理解/自主诊断 | 48 | 600 | 97.320960 | 最小链路技术及行为复核通过 |
| C 服务 | 8 | 16 | 2.595226 | 上阶段通过；原版/修订各两次，历史坏回复另作零 API 回放 |
| 短轨迹 | 4 × 最多 20 轮 | 4,800 | 6,252.134400 | 理解与结构门槛通过，再按实测费用选择配置 |
| 八组合 | 8 × 60 轮 | 204,960 | 266,966.138880 | 短轨迹通过，同版本种子 3001；先 000/111 再其余六组 |

表中金额是**请求体字节上限折算 token、每次满输出、服务不命中缓存的极端预算上界，不是预计花费，更不是当前授权或平台账单**。远期两阶段按 1 MiB 输入上限和 A 服务最坏请求数计算，显著宽于典型调用；必须依据最小阶段的实际请求与用量重新报价，不能按该表直接启动。输入超过冻结上限时停止并重新冻结，不截断历史以迁就预算。价格暂依据原 2026-09-10 截图（输入 1.2、输出 2.4 元/百万 token），收费前需重新确认；改变费率或输出上限时重新冻结，不混合比较。

首次重构交付时提出**网关 + 最小链路**：10 个任务、最多 **94 次请求 / 14.853735 元 / 2 次阶段尝试 / 0 次恢复**。分别绑定原账本和同一源码，每阶段仅一次控制器尝试；网关失败不会启动后六项，任何技术失败立即停止，行为复核不自动标为通过。实际费用按原账本逐笔记账，未用额度不自动增加尝试次数。后续阶段另行授权。

准备入口为 [tools/prepare_native.py](../../runs/official-refactor-20260913/before-source/tools/prepare_native.py)；首四阶段执行入口为 [tools/run_native_diagnostics.py](../../runs/official-refactor-20260913/before-source/tools/run_native_diagnostics.py)，默认只读预检，只有匹配的新授权加 `--execute` 才执行。短轨迹/八组清单目前是输入与费用冻结模板，进入阶段时须结合已选择配置生成 driver 清单并核验，不能传给诊断控制器绕过闸门。首次提案与当时的未批准草案见 [最小收费提案](../../runs/native-v35-preflight-20260913-verified/minimal-paid-proposal.json)。

## 迁移前历史：最小复验完成，行为门槛未通过

以下“当前”及核验数字均指各段记录当时的实现，不代表上述原生迁移。原始证据保持原样，不将历史技术通过改作新架构模型行为通过。

### 2026-09-13官方框架与项目实现核对（迁移前）

用户要求按AgentSociety2官方环境重新检查实现。结论是：**真实轨迹确实运行在官方框架上，但办理决策、供水世界、消息交接和业务历史是本项目自定义的，未使用官方默认主体决策循环。** 当前未发现足以解释错误等待的调度或生命周期不兼容；不能因此推断自定义认知接口合理，也不能把自定义机制说成官方环境的规定。

本地distribution为AgentSociety2 **2.8.4**，包内`__version__`常量仍为2.8.3，实际Ray为2.55.1；可访问的[官方latest API索引](https://agentsociety2.readthedocs.io/en/latest/api/index.html)显示2.8.7。用户提供的zh-cn地址本次未能由网页工具读取，改查同站en/latest及本地2.8.4源码。精确运行契约以安装源码为准，未升级包，也未重新核验云端安装。

| 层次 | 当前实际实现 | 核对结论 |
|---|---|---|
| 主体调度 | `AgentSociety` + Ray，注册`PolicyV3Officer`，通过官方create/from_workspace与保存钩子运行 | 接入成立；旧20轮真实轨迹含80份官方主体返回、三次恢复 |
| 环境接口 | `PolicyV3Env(EnvBase)`提供observe/submit，`EnvRouterProxy`连接自建router actor | 符合当前所用接口；官方也使用EnvLike协议，不强制所有代理继承RouterBase |
| 轮次推进 | 全部主体完成后再执行env.step；项目另检查四份提交齐全，之后结算动作和交付到期材料 | 没有发现缺少await或按网络耗时提前推进；`tick=60`是仿真时钟增量 |
| 决策与记忆 | 覆盖AgentBase.step；模型选candidate_id，最多两次回查、一次格式修复、一个业务动作；只保存最近三轮历史 | 属于项目设计，未调用官方run_react_loop；内置memory/TODO关闭 |
| 业务与通信 | PolicyWorld自行定义派单、调查、确认、评审、资源与消息延迟 | 官方允许领域环境扩展，但不提供或保证本项目的供水办理流程；逐轮排队结算不是官方统一规定 |
| 运行证据 | 自定义observations/actions/decisions等JSONL及独立审计 | 业务证据存在；官方trace为空，官方replay只有角色资料和schema，尚未接入业务状态回放 |

[官方自定义模块说明](https://agentsociety2.readthedocs.io/en/latest/custom_modules.html)允许扩展AgentBase与EnvBase；[Agent模块说明](https://agentsociety2.readthedocs.io/en/latest/api/agent.html)介绍可复用的技能、工具循环及持久化。未使用PersonAgent、ReAct或内置城市场景本身不构成错误。不过，当前实现承担了本可借助框架组织的决策和反馈工作，其可靠性需要自行证明。

确认了三个值得优先处理的边界：第一，主体在环境结算前保存`queued`回执，下一轮虽获得实际`last_receipt`，历史条目却仍保留旧提交回执和旧理由；这不是官方要求的历史结构，是需要改进的反馈呈现。第二，当前预算客户端在冻结配置下拒绝非空kwargs，而官方ReAct明确传`tools`和`tool_choice`；不能只把类名换成PersonAgent就宣称兼容。第三，自建router未把业务状态接入官方replay/trace，官方可视化不能代替现有业务日志。驱动还覆写了`_await_ref`、访问`_env_router`来检查主体失败及保存失败；这些保护当前有效，但升级框架时必须重新核对私有接口。

当前[17项离线契约检查](../../runs/v34-framework-audit-20260913/offline-contract-tests.json)通过，覆盖真实安装类的创建、恢复、保存、自定义路由、材料边界和延迟返回；未启动新的Ray任务。安装包[205个Python文件与安装RECORD一致](../../runs/v34-framework-audit-20260913/installed-package-integrity.json)，`pip check`无依赖冲突。最近16次固定输入探针直接调用共享决策接口，没有构建完整AgentSociety；不能把探针通过当作整框架通过。此前20轮轨迹属于当时冻结源码，当前离线检查与历史整轨迹证据分别保留。

完整逐项对照见[官方契约复核](../../runs/v34-framework-audit-20260913/official-contract-review.md)与[项目集成审查](../../runs/v34-framework-audit-20260913/project-integration-review.json)。本次源码未变、API请求0，原账本仍3852条。下一步应先把已提交动作与实际结算反馈清楚对应，再在保持领域规则、权限和预算的条件下评估官方工具循环的适配及业务trace/replay接入；不能预先认定换用官方循环会解决停滞，八组继续受原验收门槛约束。

### 2026-09-13三个失败状态的最小复验

用户同意追加最小复验后，在冻结源码`7754694775699c8198480c3c0d21ec83f41d501679979d66f63a74c64a52038c`上顺序完成4次网关检查与12项交接诊断。**技术核验通过，但自主决策仍两次引用虚假的派单前提，行为门槛未通过；已停止扩跑，没有启动新的多轮轨迹或八组合。** 本次没有再改源码、目标、成本、资源或政策规则。

网关覆盖两份固定输入及思考关/开，均完整返回且用量可核算。三个交接状态均使用修订接口、思考关闭；每个状态分别进行2次理解问答和2次自主决策，问答答案不进入决策上下文。12项输出全部首次结构合规，无格式修复、回查或重发；6次理解问答的12个答案全部正确。实际自主决策如下：

| 冻结状态 | 理解任务全部答对 | 两次自主决策及问题 |
|---|---:|---|
| 已派单、尚未调查 | 2/2 | 两次均承认`lead=本人`，却仍声称没有正式派单、直接调查会绕过流程，选择等待；错误前提重复出现 |
| 收到接受回执、前置尚未完成 | 2/2 | 一次正确查询状态；另一次理由正确说明应等待，但编号实际选择`work`，理由与行动不一致 |
| 已拟案、尚未发出普通评审请求 | 2/2 | 两次均识别请求尚未发出并选择`request_review`；但都误称只耗劳动0.1，漏计通信劳动0.2 |

独立核验重建实际请求、候选绑定和用量回执；没有发现未授权材料引用。另以原始世界前缀恢复合法观察，将6次真实选择原样各结算一步、其余主体固定等待：两次评审请求和一次查询成功发送；错误选择的作业因`prerequisites_or_received_handoff_missing`被拒绝，消耗决策劳动0.1。程序没有代改候选或理由。这是零API的单步分支核验，不是新真实轨迹，也不能证明后续材料交接完成。见[复验结果](../../runs/v34-trajectory-repair-20260913-preflight/minimal-retest-results.json)、[原始诊断](../../runs/v34-trajectory-repair-handoff-20260913/report.json)、[行为复核](../../runs/v34-trajectory-repair-20260913-preflight/handoff-behavior-review.json)及[单步行动回放](../../runs/v34-trajectory-repair-20260913-preflight/probe-action-replay.json)。

按原计划转做[目标与成本的离线审查](../../runs/v34-trajectory-repair-20260913-preflight/goal-cost-review.json)：主体知道依法处理问题并考虑成本，但没有量化服务收益、延迟损失或二者的权衡；等待的直接资源成本为0，累计未解决负担虽在仿真中记录，却未作为量化损失进入这三份主体观察。当前资源足以承担调查或通信，候选也确实存在。成本分项公开，但模型需要自行合计；普通查询和评审请求实际均为劳动0.3。上述事实不能证明成本设定导致了错误等待，也不能把明确虚构的派单前提解释为合理节约。待区分的是流程规则套错阶段、目标与成本权衡不明确，以及成本合计或候选编号绑定出错；本次未添加等待惩罚、强制推进或奖励权重。

进一步核对[问答与决策的实际上下文](../../runs/v34-trajectory-repair-20260913-preflight/context-followup-review.json)：两者的观察和历史数据相同，但理解题直接点名`lead`、`tasks`、接受回执和请求字段，自主决策没有这些问题引导。历史中还保留旧候选编号与模型自己的错误理由；前置未完成案例的第2轮历史已经出现“实际作业、理由却说请求协调”的矛盾。三份近期历史回执均为提交时的`accepted_for_settlement`，实际最新结算另在`last_receipt`；不能把历史排队回执当成成功。已派单案例的历史通信成本说法为0.1，最新实际回执却为0.3。这些事实提示应区分直接规则识别、混合上下文中的状态判断及编号绑定，尚不能证明历史内容、提示长度或某句话造成了错误。本轮三个状态只测试思考关闭，也不能断言开启思考能消除这些问题。该追加核查仅读取证据，没有新增收费或源码修改。

**本次实际16次请求、2次阶段尝试、0次恢复，费用估算0.13398元**（网关0.0008472元、交接诊断0.1331328元），输入109,034 token、输出1,308 token；思考token不重复计费。这是按冻结费率及上游用量核算的估算，不是平台账单。原账本由3836条到3852条，新增未知用量和在途请求均0，原前缀未变。授权上限为40次/2元/2次尝试/0次恢复，两次尝试均已完成；没有把剩余金额视为额外尝试授权。见[用户授权](../../runs/v34-trajectory-repair-20260913-preflight/user-approval.json)、[网关逐笔核验](../../runs/v34-trajectory-repair-20260913-preflight/gateway-verification.json)、[诊断技术核验](../../runs/v34-trajectory-repair-20260913-preflight/handoff-technical-verification.json)及[60个结束工件哈希](../../runs/v34-trajectory-repair-20260913-preflight/closed-probe-file-hashes.json)。此前54个短轨迹原件继续保留。

当前源码的383项完整离线检查已通过，本次运行及审查期间源码未变。三状态复验说明部分流程解释可用，但自主决策的一致性仍未解决，不能据此冻结正式实验配置。原104项完整诊断通过结论仅适用于当时源码；当前源码仍须在问题解决后通过完整诊断及4条真实短轨迹，再进入八组。以下保留各阶段当时的输入、授权和结果，旧版本不并入新比较。

### 2026-09-12至13日的初始修订与试跑（历史记录）

2026-09-12按已确认计划完成本地代码修改。物理状态与政策设计仍沿用 `policy-v3-3.3` / `policy-v3-design-3.3`；新配置以 `v34-request-profile-1` 和 `revised_v34` 单独冻结，防止把请求设置不同的结果混在一起。该准备阶段378项完整离线检查通过，4条受控情景分别完成20轮官方框架脚本验证及独立核验，真实API请求为0。**2026-09-13按用户要求缩小为最小真实试跑：4次网关探针与2次业务决策全部通过，用量费用估算0.0320724元；该最小阶段没有启动完整诊断或八组实验。**

### 2026-09-13短轨迹停止与离线修复（历史记录）

修正QA后的104项诊断通过后，按已获授权启动真实短轨迹。**首条`v34_dispatch_B0`干净完成20轮，随后独立核验闸门自动停止批次；其余3条短轨迹和八组均未启动。** 这条轨迹用了75次请求、估算0.8944788元，无格式修复、传输重发、未知用量或恢复。四个5轮分段均等待主体完成后提交，驱动退出及Ray关闭正常，75份回执与原账本逐项一致，账本到3836条。原始[批次状态](../../runs/v34-trajectories-20260913/batch_status.json)、[失败核验](../../runs/v34-qa-repair-20260913-preflight/trajectory-original-verification.json)及[54个原始工件哈希](../../runs/v34-qa-repair-20260913-preflight/closed-trajectory-file-hashes.json)保留。

独立核验失败来自提示序列化缺陷：修订视图的部分字段和嵌套对象依赖内存字典顺序，日志保存时重排键，重建提示因此与实际发送字符串不同。逐项检查75次请求，系统提示、上下文、候选、历史及用户JSON解析后的数据均一致，差异仅为对象键顺序；动作重放复现完整世界哈希，费用和事件核算一致。此判断见[独立差分与逐笔核验](../../runs/v34-qa-repair-20260913-preflight/trajectory-forensic-verification.json)，**不把原失败核验改标通过**。

另有独立的行为问题，见[完整20轮/75份正文复核](../../runs/v34-qa-repair-20260913-preflight/trajectory-behavior-review.json)：

- 部门3共11次把`lead=3`的已派工单解释为“未被指派或确认”，其中第8、10、18、19轮据此等待（轮号从0开始）。
- 部门2第5轮把`ordinary_assignment_reply/accept`当作前置任务完成，作业被业务规则拒绝；随后承认拒绝并等待真实完成记录。
- 负责人第4–19轮只等待或查询评审，未发送`request_review`，却按评审已启动解释`pending`任务或空回复。未再次出现“拟案前必须先评审”，但“任务已生成”和“请求已发出”仍混淆。

该受控轨迹已取得调查记录，事件重算显示3/12初始问题曾解决，2次复发，期末11个问题未解决，累计未解决负担223；工程建成、投运、物理生效和行政验收均0。它不是八组政策比较，且行为门槛没有通过；取得调查反馈不能抵消其他事项持续误解。此次没有通过提高解决率目标、自动补造行动或放松校验让它过关。

离线修复现在冻结为`7754694775699c8198480c3c0d21ec83f41d501679979d66f63a74c64a52038c`：先规范嵌套JSON键及历史对象顺序，再按固定事项优先顺序显示，候选和历史列表顺序保留；严格审计仍拒绝任何被替换的消息字符串。角色流程卡解释`lead`、调查后任务、接受/完成回执，以及评审任务生成、请求、送达、完成的区别；明确普通流程的请求入口与必经联办的自动分派分别适用。物理、政策、资源与候选规则没有修改。

[完整离线套件383项通过](../../runs/v34-trajectory-repair-20260913-preflight/offline-tests.json)。新增回归从真实调用接口接到排序后的持久化证据，先复现失败再通过；[75份原回复的离线回放](../../runs/v34-trajectory-repair-20260913-preflight/offline-response-replay.json)在新呈现下解码为相同动作并通过严格审计。回复是固定历史数据，不是模型看到新提示后的新行为。新增最小交接复验入口的[12次模拟调用与独立报告回放](../../runs/v34-trajectory-repair-20260913-preflight/handoff-runner-offline-check.json)亦通过，不含收费请求。完整修改与边界见[修复核验](../../runs/v34-trajectory-repair-20260913-preflight/repair-verification.json)、[源码冻结](../../runs/v34-trajectory-repair-20260913-preflight/source-freeze.json)。此前源码及原件继续保留。

当时冻结三个新失败状态，准备单独的`handoff_probe`：已派单但未调查、接受回执但前置未完成、拟案后尚未发送普通评审请求。每个状态分别理解问答/自主决策各重复2次，均为修订接口、思考关闭，问答答案不进入决策上下文；理解正确但继续反复不作为时转查目标与成本，不强化推进指令。见[冻结输入](../../runs/v34-trajectory-repair-20260913-preflight/cases.json)、[最小清单](../../runs/v34-trajectory-repair-20260913-preflight/handoff_probe-manifest.json)。此小探针不能替代原104项配置诊断和4条真实轨迹门槛；随后已获授权并完成，结果见顶部。

当时提出的追加授权范围仅为新源码网关4次与最小探针12项：首轮16次，含回查/一次格式修复最多40次请求、2元、2次阶段尝试、0次自动恢复。依据此前用量的首轮规划估算约0.14元，既不是保证费用也不是平台账单。[具体预算提案](../../runs/v34-trajectory-repair-20260913-preflight/minimal-retest-proposal.json)与`approved=false`授权草案保留历史状态；用户随后明确同意，实际授权另存并绑定原账本、源码与清单，执行结果见顶部。

截至此次离线修复、尚未执行上述最小复验时，用户“继续”以来合计**187次请求、估算2.2476元、3次阶段尝试、0次恢复**；加此前首次全量诊断，为294次/3.5833152元。旧未知用量占用保留，该阶段新增未知用量为0；本段金额均按已冻结费率和上游用量估算，不含随后最小复验的16次/0.13398元。八组合仍是未完成工作。

### 2026-09-13修正后的完整诊断（后续短轨迹已停止）

用户“继续”已授权追加2次阶段尝试、最多150次请求/5元。新源码`30f0b9b1bcae0d867154bc8f91ecaf41e59ee1788471e2793e912e3891299406`下的[4次网关](../../runs/v34-qa-repair-20260913-preflight/gateway-verification.json)和[104项诊断](../../runs/v34-qa-repair-diagnostic-20260913/report.json)均完成。诊断108次请求（4次格式修复，均发生于旧版条件），费用估算1.352214元；加网关0.0009072元，本次复测共112次请求、**1.3531212元**，无未知用量或自动恢复。108份诊断回执与原账本逐项一致，账本到3761条，原前缀及V3.3的532个原件哈希未变。见[独立重放与对账](../../runs/v34-qa-repair-20260913-preflight/diagnostic-verification.json)。

| 接口/思考 | 首次格式通过 | 修复后格式通过 | 理解任务全部答对（每项2题） | 用量费用估算/元 |
|---|---:|---:|---:|---:|
| 旧版/关闭 | 21/24 | 22/24 | 12/12 | 0.2931816 |
| 旧版/开启 | 24/24 | 24/24 | 12/12 | 0.3794544 |
| 修订/关闭 | 24/24 | 24/24 | 12/12 | 0.2636016 |
| 修订/开启 | 24/24 | 24/24 | 12/12 | 0.3597816 |

C服务旧版首次3/4、修复后4/4通过；修订版4/4首次通过。旧版关闭思考的两份合法等待回复修复后仍缺少合格结构，失败保留，不放松校验。[24份修订版自主决策的独立复核](../../runs/v34-qa-repair-20260913-preflight/behavior-review.json)未发现明确错误必经前提或未授权来源引用；4份等待均无可用任务，20份采取其他行动，实际回查0次。一份确认理由漏计公开决策成本0.1，并有后续流程条件措辞不清，单列为解释局限；候选及引用合法不证明理由完全正确。理解题通过也不等于自主回查行为已获验证。

两种配置均通过预先冻结的门槛，按已报告用量费用较低选择**修订接口、思考关闭、max_tokens=16384、A/C思考关闭、600/660秒网络等待**。选择未使用解决率或政策效果，见[配置冻结](../../runs/v34-qa-repair-20260913-preflight/profile-selection.json)。这些诊断样本不作为政策效果证据；前次缺少公共接口说明的QA结果不合并。

随后启动了[4条短轨迹的顺序批次](../../runs/v34-trajectories-20260913/batch_status.json)，首条结束后已停止，详见顶部。该批次原计划使用同一源码和选定配置，分别覆盖派单至调查反馈、拟案至评审反馈及B关闭/开启，每条20轮。沿用全量授权的320次请求/30元/4次尝试/0次自动恢复，接续原账本。[按脚本路径和实测诊断用量的费用测算](../../runs/v34-qa-repair-20260913-preflight/trajectory-cost-estimate.json)为基准268次/约5.08元，仅作规划，不预测模型自主路径或保证完成；运行清单、预算及框架配置见[启动冻结](../../runs/v34-qa-repair-20260913-preflight/trajectory-launch-freeze.json)。八组尚未启动，须先完成短轨迹的独立核验及交接目标。

### 2026-09-13首次全量诊断与输入缺口（历史记录）

最小试跑完成后，用户明确要求“开始全量运行吧”。本次按原计划执行后续阶段，仍保留诊断、短轨迹和逐组核验门槛：复用同一源码下已通过的4次网关探针，先做96项主体诊断与8项C服务诊断，通过后进入4条短轨迹，再进入八组合、种子3001、每组60轮，先000与111。该轮源码冻结为`a2415c5b7e1910ba27ff23de997421c36158ff4ae410b62f89b3a5ae58744f56`，各阶段结果独立保存，不把最小样本并入完整诊断。

执行上限沿用先前提案：诊断304次/28.5元/1次尝试，短轨迹320次/30元/4次尝试，八组2400次/100元/8次尝试；合计最多3024次请求、158.5元、13次尝试、0次自动恢复。数值为执行侧沿用的停止上限，不是用户要求花完的金额。每个后续阶段仅在前置证据通过后绑定当前账本和清单启用，不自动扩额。本次起点为原账本3542条、累计占用48.4385652元，旧账保留。见[用户授权及范围](../../runs/v34-full-20260913-preflight/user-approval.json)、[启动冻结](../../runs/v34-full-20260913-preflight/launch-freeze.json)及[诊断清单](../../runs/v34-full-20260913-preflight/diagnostic-manifest.json)。**该轮104项诊断完成，但两种修订配置均未通过理解题门槛，因此当时未启动短轨迹与八组。修正后的复测结果见本页顶部。**

启动前[379项完整离线检查](../../runs/v34-full-20260913-preflight/offline-tests.json)通过；实际104项任务使用107次API请求（3次格式修复均未挽回对应旧版输出），1次阶段尝试，无传输重发或整组恢复。107份原回执与账本逐项一致：输入910,720 token、输出101,188 token，用量费用估算**1.3357152元**，新增未知用量为0。账本由3542条增至3649条，累计占用49.7742804元；原账本前缀及V3.3的532个文件哈希未变，无在途请求，框架锁及预算锁已释放。见[独立重放与逐笔核验](../../runs/v34-full-20260913-preflight/diagnostic-verification.json)、[完整原始对照](../../runs/v34-full-diagnostic-20260913/report.json)和[364个结束工件哈希](../../runs/v34-full-20260913-preflight/closed-diagnostic-file-hashes.json)。

| 接口/思考 | 首次格式通过 | 修复后格式通过 | 理解任务全部答对（每项2题） | 用量费用估算/元 |
|---|---:|---:|---:|---:|
| 旧版/关闭 | 22/24 | 22/24 | 11/12 | 0.2780940 |
| 旧版/开启 | 24/24 | 24/24 | 11/12 | 0.3772704 |
| 修订/关闭 | 24/24 | 24/24 | 10/12 | 0.2609808 |
| 修订/开启 | 24/24 | 24/24 | 10/12 | 0.3606360 |

C服务独立8项：旧版首次及修复后均3/4通过，历史重复主题材料的一次旧版输出修复后仍有重复；修订版4/4首次通过。主体两次最终结构失败都在旧版/关闭的合法等待情景，连续回复`action: "wait"`，缺少candidate_id。修订版两档共24份自主决策均首次合规；[行为复核](../../runs/v34-full-20260913-preflight/behavior-review.json)未发现足够明确的错误必经前提或未授权来源引用。4份等待确无任务，另1份因派单错误成本而延期回查，没有已在途原文、也没有实际回查，是否误解同轮读取仍不确定。两份拟案理由存在证据过度概括或虚构预算拆分，单独保留为未解决的解释问题；合法候选与合法引用不能证明方案正确。

**理解题暴露了诊断输入缺口。** 6项理解任务错误全部发生于“能否本轮回查原文”，其中修订版两种思考各2次均答no。冻结状态实际允许回查：12项合法索引、原文未送达、已用0次/限额2次；离线调用读取校验成功。但QA提示遗漏了自主决策中已有的材料接口说明，且没有区分“本次问答不执行动作”与“给定仿真轮可用动作”。因此保留与冻结key不符的原始分数，同时标明归因不确定，不将其直接表述为模型生产流程理解失败，也不删题让配置过关。见[独立题目复核](../../runs/v34-full-20260913-preflight/raw-read-question-review.json)及[未通过的配置选择结果](../../runs/v34-full-20260913-preflight/profile-selection.json)。

运行结束、独立核验及原件冻结后，已离线修复`policy_v3/diagnostic_runner.py`：四种理解条件均获得同一公共材料接口合同，并澄清仿真轮与问答执行的区别。新冻结源码为`30f0b9b1bcae0d867154bc8f91ecaf41e59ee1788471e2793e912e3891299406`；22项相关检查通过。48份QA输入发生预期改变；48份自主决策及8份C服务的首轮消息逐项与原运行相同；案例与答案键字节相同。见[修复核验与新源码](../../runs/v34-qa-repair-20260913-preflight/repair-verification.json)。后续已完成独立复测，旧分数不重新标记；旧诊断的独立核验是在改动前用其运行时冻结源码完成，复现应使用对应[源码包](../../runs/v34-full-20260913-preflight/source.zip)。

首次诊断已用完其1次阶段尝试，原短轨迹及八组授权仍受前置门槛约束。[追加复测提案](../../runs/v34-qa-repair-20260913-preflight/retest-proposal.json)为新源码网关与完整诊断共最多150次请求、5元、2次额外尝试、0次自动恢复；按前次用量估算约1.4元，不保证复测通过或完成。用户随后明确“继续”，[追加授权](../../runs/v34-qa-repair-20260913-preflight/user-approval.json)已生效，整体尝试上限从13增至15；即使按新增与剩余阶段上限计算，请求和金额仍在原3024次/158.5元内。提案原件的`approved=false`保留为历史，实际启用文件另存并绑定新源码、清单及原账本。

修正后的网关与完整复测结果见本页顶部；先前有输入缺口的诊断保留原分数，不并入新对照。

### 2026-09-13最小真实试跑

本次只取冻结案例中的首次派单与诊断后拟案两个历史状态，每个独立请求一次。新增`minimal`阶段固定这两个任务，不能代替完整诊断门槛。当前源码冻结为`a2415c5b7e1910ba27ff23de997421c36158ff4ae410b62f89b3a5ae58744f56`，启动前28项相关离线检查通过；前述378项完整套件对应9月12日准备版本。案例、请求设置、上限及源码见[本次启动冻结](../../runs/v34-minimal-20260913-preflight/launch-freeze.json)。

| 检查 | 实际请求 | 结果 |
|---|---:|---|
| 两份固定输入，思考关/开 | 4 | 均完整返回，思考字段与配置一致，用量可核算 |
| 首次派单，修订接口、思考关闭 | 1 | 自主选择将`T:F1-1:0`派至部门2调查 |
| 诊断后拟案，修订接口、思考关闭 | 1 | 自主选择为`P:1`拟案，理由明确“先拟案、后评审” |

两次业务输出均首次合规，无格式修复、材料回查或重发。为区分输出合法与动作可执行，另外离线重放各自原始世界前缀，确认主体观察与冻结输入一致，再将真实模型所选动作结算一步：派单返回`routed`；拟案返回`proposed_plan_recorded`，项目变为`planned`并生成两项评审任务。其他角色在这一步使用合法等待；这项检查是独立的离线单步分支，**没有验证真实模型多轮交接或评审反馈送达**。见[原始业务输出](../../runs/v34-minimal-business-20260913/report.json)及[单步执行核验](../../runs/v34-minimal-20260913-preflight/business-execution-check.json)。

本次未复现原来的两种流程误解，但每种情景仅一个样本，没有新增旧版对照或重复性估计。思考开启仅通过网关探针，不能据此判断它改善办理行为；C服务、B开启后的协同、多轮材料交接及60轮稳定性仍未实测。当前证据不足以选择最终推理配置或解释政策效果，后续仍按诊断和短轨迹门槛推进。

本次范围来自[用户最小试跑请求](../../runs/v34-minimal-20260913-preflight/user-request.json)，执行侧收紧为最多12次请求、3元、2次阶段尝试、0次自动恢复；这些数值是操作上限，不是用户要求花完的金额。实际6次请求、2次尝试均完成，共25,709输入token、509输出token，估算0.0320724元（按已冻结价格及上游用量，不是平台账单）。6份回执与原预算账本逐项一致，账本由3536条增至3542条，原3536条前缀和V3.3的532个原始文件哈希未变，无在途请求。完整结果见[试跑与对账](../../runs/v34-minimal-20260913-preflight/final-results.json)及[网关核验](../../runs/v34-minimal-20260913-preflight/gateway-verification.json)。

9月12日完整诊断的准备工件保留在 [V3.4准备目录](../../runs/v34-preparation-20260912/)，其源码冻结与本次最小阶段分别标注：

- [实施与证据核验](../../runs/v34-preparation-20260912/implementation-verification.json)、[完整离线检查](../../runs/v34-offline-checks-20260912/unit-tests.json)、[官方脚本批次](../../runs/v34-offline-framework-20260912/batch_status.json)。
- [冻结案例](../../runs/v34-preparation-20260912/cases.json)、[网关清单](../../runs/v34-preparation-20260912/gateway-manifest.json)、[理解与决策对照清单](../../runs/v34-preparation-20260912/diagnostic-manifest.json)、[行为判读模板](../../runs/v34-preparation-20260912/behavior-review.template.json)。
- [逐阶段预算提案](../../runs/v34-preparation-20260912/budget-quote.json)与[冻结源码及测试](../../runs/v34-preparation-20260912/source.zip)。这些文件不构成收费授权。

### 实际修改及解释边界

角色流程说明区分派单后调查、分工确认、诊断后拟案再评审，以及已经送达与尚待送达的材料。修订版模型视图仅移除与候选清单重复的 `available_actions`，保留候选集合、历史、原文权限及内部校验观察；新增流程卡和输出结构示例整体作为“接口呈现修订”因素。旧版消息、规范化与默认参数保持可调用，历史坏回复仍被拒绝。业务等待、拒绝与技术失败分别记录，程序不补造派单、理由或C主题。

思考对照固定 `deepseek-v4-flash`：办理主体关闭思考或开启且effort=high，A/C服务始终关闭；两档输出上限均16384。配置同时约束客户端、代理、预算授权、运行记录和独立审计。新配置请求采用固定JSON序列化以重建请求哈希；旧配置序列化不变。推理token包含在completion总量中，不再额外相加。思考开启时temperature不生效，因此比较两种推理配置，不声称采样行为完全相同。网关探针检查请求设置、完整JSON、用量、响应编号与是否出现思考字段，不把这些检查解释为直接测得模型内部推理强度。

新配置上游网络等待600秒、客户端660秒，取消外层分块的固定墙钟时限；仍遵守显式执行停止期限。四个主体本轮完成后才结算和推进仿真，技术超时不会生成业务wait。新阶段禁用自动传输重发和整组恢复；格式修复仍最多一次，同轮材料回查最多两次。旧V3.3重试行为仅用于旧配置。

### 已冻结的诊断与进入条件

| 阶段 | 首轮任务或运行 | 请求边界 | 用途 |
|---|---:|---:|---|
| 网关 | 2份输入×思考关/开＝4 | 4，无修复或重发 | 核验参数通路、完整输出和计量 |
| 办理主体 | 6类情景×2种呈现×2种思考×理解/选择×2重复＝96 | 288，含回查和一次格式修复 | 区分流程理解与自主选择 |
| C服务 | 2份材料×原/修订说明×2重复＝8 | 16，含一次格式修复 | 历史重复主题与留出输入 |
| 短轨迹 | 派单调查/拟案评审×B关/开＝4 | 待诊断后刷新费用测算 | 核验合法行动与材料交接 |
| 完整八组 | 单种子3001，每组60轮 | 待短轨迹通过后刷新费用测算 | 同一冻结版本的描述性比较 |

理解问答与自主决策使用独立上下文，答案键和判读证据不进入模型请求。任务顺序固定混排；每项允许的请求数已冻结。`first_pass_valid`表示该任务无需格式修复即可完成（合法回查不算格式失败），`final_valid`表示预算内修复后结构是否有效。错误但格式合法的理解答案不修复、不反馈正确答案。

实际响应会逐项保留原文、消息、UUID、配置、usage和回执；进入下一阶段前以保存响应离线重放，重新计算格式、答案、动作和用量结果。行为判读仅依合法材料及模型写出的理由：填写错误前提、信息越界、等待依据和证据位置，并绑定响应哈希。关键理解题、最终结构与行为判读均通过才可进入短轨迹；两档通过时用诊断已知费用选择，持平关闭。若理解正确而持续不作为，先审查目标与成本设定，不按解决率或政策采用率选配置。

短轨迹保持标准初始世界：派单情景从第0轮开始；拟案情景先用3轮已冻结合法动作建立诊断状态，再由真实模型决策，总窗口仍最多20轮。初始化明确标注、无API调用、不混成真实模型行为，审计独立重放该前缀。派单链目标是有权限的专业部门取得调查记录；派单员不会因此获得原本无权读取的部门记录。评审链目标是负责人收到评审记录。脚本验证只检验执行路径；尚未完成真实模型短轨迹。

完整八组清单只在四条真实短轨迹通过后生成；运行顺序先000、111，再其余六组，每组技术完成后立即独立核验，失败则停止扩跑。全组使用同一呈现与推理配置，均从初始状态开始。技术通过但结果较差仍如实报告；单种子不提供正式多种子推断。

### 入口、额度和下一步

离线准备入口为 `tools/prepare_v34.py prepare --output <runs中的新目录>`；收费入口为 `tools/run_v34_diagnostics.py --manifest ... --authorization ... --output ... --execute`。第二阶段还必须传入已通过的 `--gateway-evidence .../report.json`。新授权必须绑定冻结清单、源码、请求配置、价格及原账本当前前缀；未经授权的提案不能启动API。

诊断完成并填写行为判读后，使用 `tools/prepare_v34.py trajectories --manifest ... --results ... --behavior-review ... --output ...` 生成受控轨迹清单；沿用 `tools/run_v3_batch.py --stage trajectory` 运行官方框架。四条真实轨迹核验通过后，`tools/prepare_v34.py full --trajectory-manifest ... --runs <四个目录> --output ...` 才能生成新八组清单，继续沿用现有批次、收集和分析入口。

9月12日原提案为网关与诊断两阶段合计**最多308次请求、30元、2次阶段尝试、0次自动恢复**，其中网关4次/1.5元、诊断304次/28.5元；短轨迹暂提320次/30元/4次尝试，完整八组暂提2400次/100元/8次尝试。9月13日最小试跑后，用户进一步授权全量执行，当前生效范围见本页顶部；不重复网关。金额是停止上限，不保证用满请求数，也不是平台实际账单。预算提案同时列出按最大请求字节预留的保守上界，实际请求按现有1.2元/百万输入、2.4元/百万输出费率逐笔计量；阶段门槛、按实测刷新测算及原账本约束继续适用。

旧授权剩余金额不能绕过已耗尽的尝试额度；本次最小试跑已在同一账本追加6条，并用完对应两次阶段尝试。未用请求或金额不自动转为扩跑授权。V3.3历史冻结证据保持不变。

## V3.3历史执行背景

当前状态为 `policy-v3-3.3`，观察/决策接口为 `v3.3-materials-1`，研究协议为 `policy-v3-design-3.3`。V3.3修复输出兼容、受控传输重试、业务拒绝反馈及B确认回执送达，沿用四类主体、12个初始问题、八组合、单种子3001和60轮窗口。**修复验收阶段真实API调用为0；随后获批的八组真实运行尝试已结束，3组完整、5组失败，结果见下一节。** 模型、资源、治理目标与办理token口径不变，不以提高办结率作为程序通过条件。正式多种子N仍未冻结。

V3.2收费批次已结束，仍仅100和110两组完整通过；其全部原始输出、失败分支、账本及冻结源码保留在下方历史记录。V3.3不得跨版本恢复、重标旧结果或混入旧轨迹进行八组合比较。

## V3.3真实模型执行

用户已[确认启动及累计额度](../../runs/v33-single-seed-20260911-preflight/user-approval.json)，范围为八组合、单种子3001、每组60轮。批次于**2026-09-12 00:02（北京时间）结束**：000、011、110完整完成60轮并通过独立核验，另外5组因模型输出一次修复后仍不合规而失败。全部八次尝试已登记终态，所有控制器回执均确认Ray关闭和请求排空，预算锁及框架锁已释放。见[最终结果与账目](../../runs/v33-single-seed-20260911-preflight/final-results.json)、[终态批次记录](../../runs/v33-single-seed-20260911/batch_status.json)及[逐组核验与收集](../../runs/v33-single-seed-20260911-preflight/collected-records.json)。[首批启动核验](../../runs/v33-single-seed-20260911-preflight/first-progress.json)仅代表启动时刻。

累计阶段上限已批准调整为**121.82元、4161次请求、21次技术尝试**。仍从原1067次/13.626144元基线统一记账，旧阶段1358次/16.997976元和13次尝试继续占用；本次启动前剩余104.822024元、2803次请求、8次尝试。累计2次整组恢复已用完，不再追加。V3.3每逻辑调用最多两次已结算传输重发仍由原代理控制并逐次计费。所有模型/schema终止保持原件，单组失败不冒充完整结果；全局安全错误或额度耗尽时停止，不自动扩额。

执行绑定见[已批准清单](../../runs/v33-single-seed-20260911-preflight/manifest.approved.json)、[累计预算授权](../../runs/v33-single-seed-20260911-preflight/authorization.approved.json)、[启动冻结](../../runs/v33-single-seed-20260911-preflight/launch-freeze.json)。源码与341项离线检查、八组合官方脚本验收一致，运行期保持冻结；使用全新V3.3目录，不跨版本恢复或混入V3.2结果。原[启动方案](../../runs/v33-single-seed-20260911-preflight/launch-proposal.json)及未批准候选保留为本次确认前记录，以本节批准文件为执行依据。

本次新增**1111次请求，已报告用量费用估算17.7823728元**，无在途请求和新增未知用量。完整组526次/10.1446068元，失败组585次/7.6377660元。985次为办理agent调用，另有A服务50次、C服务76次仅计预算；未发生传输重发或整组恢复。所有UUID与原控制器回执及账本一一对应，2条失败客户端记录缺少本地usage，但代理已报告用量，均按原回执计入。见[逐笔对账](../../runs/v33-single-seed-20260911-preflight/request-reconciliation.json)。失败并不等于未收费，也不等于HTTP调用失败；本次上游回执均为200。

该授权阶段累计2469次请求，已知费用估算34.6572144元，加历史2次未知用量预留0.1231344元，合计占用**34.7803488元**。阶段剩余87.0396512元、1692次请求，但21次尝试及2次整组恢复额度均已用完，不自动补跑。整个本机账本累计3536次，占用48.4064928元；原1067行授权基线及启动前2425行账本均核对保持原样。以上为用量估算和预算预留，并非已核对的平台账单，也不包含未迁入的云端历史。

以下仅列同一V3.3源码、完整60轮且核验通过的轨迹。T_agent是四类办理agent的实际输入与输出token之和，政策服务生成不计入；U为累计未解决问题轮，越低表示该窗口内未解决负担越少。

| A/B/C | T_agent | 输入token | 输出token | U | 初始12个问题已解决 | 期末未解决 | 物理生效/行政验收项目 |
|---|---:|---:|---:|---:|---:|---:|---|
| 000 | 1,948,420 | 1,934,064 | 14,356 | 720 | 0 | 12 | 0/0 |
| 011 | 4,201,022 | 4,170,392 | 30,630 | 704 | 1 | 12 | 0/0 |
| 110 | 1,978,102 | 1,963,309 | 14,793 | 720 | 0 | 12 | 0/0 |

011相对000的T_agent增加2,252,602、U减少16；110相对000的T_agent增加29,682、U不变。011记录5次新增/复发问题、16个风险设施轮；其“曾解决1个初始问题”不代表期末保持解决。000和110的风险暴露均为0，不能把没有新增问题解释为预防成功。三组均未形成物理生效项目。正式N仍未冻结，单种子没有可估计的标准误、置信区间或显著性；五组缺失可能与处理相关，不能据此判断完整八组合优劣或交互效应。详见[单种子描述性分析](../../runs/v33-single-seed-20260911-preflight/single-seed-analysis.md)及[机器可读分析](../../runs/v33-single-seed-20260911-preflight/single-seed-analysis.json)。

| 失败组合 | 失败回合（从1计） | 最后完整5轮副本 | 一次修复后仍存在的问题 |
|---|---:|---:|---|
| 101 | 21 | 20 | action包装缺少candidate_id |
| 010 | 29 | 25 | 规范化后仍缺少必填reason |
| 111 | 9 | 5 | 增加candidate_id后仍保留非法action字符串 |
| 100 | 60 | 55 | params与analysis冲突，修复保留空params和非空analysis |
| 001 | 35 | 30 | C分析仍包含重复主题组 |

失败原件、部分回合状态和全部实际用量均保留；表中副本全部通过哈希核验，部分轨迹不进入60轮比较。各失败响应的原文件、行号、UUID与哈希见[最终结果](../../runs/v33-single-seed-20260911-preflight/final-results.json)，全部结束目录的[文件哈希清单](../../runs/v33-single-seed-20260911-preflight/closed-run-file-hashes.json)用于后续核对。此次仅运行现有离线核验、收集与分析入口，并执行[收尾对账脚本](../../runs/v33-single-seed-20260911-preflight/finalize_summary.py)；[收尾验收](../../runs/v33-single-seed-20260911-preflight/final-report-verification.json)通过，532个结束目录文件哈希一致，未改冻结源码或追加收费调用。五分钟监控在收尾核验完成后暂停。

## V3.3真实轨迹为何停滞

用户对低解决率提出疑问后，使用既有停滞诊断入口核对三个完整组的实际动作、候选、项目阶段和问题事件，见[本次轨迹诊断](../../runs/v33-single-seed-20260911-preflight/outcome-stall-diagnosis.md)及[原始理由与行号索引](../../runs/v33-single-seed-20260911-preflight/outcome-stall-diagnosis.json)。532个原始文件、冻结源码和预算账本均未改变，新增收费调用为0。

- **个案办理入口停滞。** 000与110的派单员60轮全部等待，每轮仍有24个派单候选；两个专业部门每轮只有等待候选，未收到工单。000的模型理由反复等待现场调查或上级指示才派单，实际派单是后续调查的入口。110反复表示要等原文，但没有使用已提供的原文回查接口。011派单员55轮等待，仅派发5张工单，全部集中在F1-1。
- **项目卡在诊断之后。** 三组各创建并诊断4个项目，却均未执行一次拟案。负责人拥有拟案候选的轮数分别为000的47轮、011的57轮、110的43轮。011日志轮30输出称“拟案需要先获得专业评审意见”，而源码中拟案才创建评审任务；另外两组也反复等待评审、反馈或指令，并多次重复申请已有主题。真实轨迹因而没有进入评审、施工和投运阶段。
- **011有处理，但没有持续解决。** 同一设施F1-1的问题先后在日志轮6、18、26、44、53解决，共5次；其中只有第1次属于初始12个问题，后4次是复发问题。轮7、18、28、46、59又产生新问题，最后一次到期末未解决。因此“初始已解决1个”“总共解决过5次”和“期末仍有12个未解决问题”可以同时成立。问题事件不应与持续正常的设施数混为一谈。

上述证据定位了等待和流程先后理解方面的行为停滞，不能把低解决率解释为政策工具无效或框架无法执行修复。此前脚本验收证明既定行动路径可以走通，真实自主模型的业务闭环验收仍不足。后续应先核验派单、主动回查和诊断后拟案的流程理解，再决定是否启动新批次；本次未改提示、未验证改动效果，也未追加运行授权。模型给出的理由是输出证据，不等于直接测得其内部认知过程。

用户进一步明确：本项目是科研试验，不要求工程实时性。应区分现实计算耗时、仿真时间和主体选择的等待。当前运行先等待模型选择并提交，四个角色全部提交后才结算并推进一轮；`tick=60`推进的是仿真时间，不是要求模型60秒内回答。部门暂时没有任何可执行任务时可记录空闲，但派单员具有派单选项，不走这个空闲分支。

[执行等待核对](../../runs/v33-single-seed-20260911-preflight/dispatch-timing-check.json)确认000和110派单员各60次请求均正常结束（HTTP 200、finish_reason为stop），120份原始回答都明确选择了等待；每轮四角色提交齐全。因此这两组未派单不是模型尚未回答便被推进，也不是超时后自动代填等待。提示已明确“不要求先知道真实根因、收到专业调查或其他部门确认”，模型仍反复输出相反的等待依据；110则等待原文而未发起回查。多增加现实等待时间不会自动启动尚未派单的调查或代替原文回查。

后续研究验证应允许模型充分完成计算，按预先定义的仿真事件与信息送达规则推进；技术超时保持技术失败身份，不能混成主体业务等待。需要核验的是主体是否理解流程、是否把缺少信息与需要主动取信息区分开，以及等待是否有真实的后续事件。成本表述或历史理由是否强化停滞仍是待检验假设；不能直接用强制派单、自动拟案或按期望结果筛选提示来消除低解决率，也不以降低现实延迟或提高吞吐为本研究目标。

本次冻结模型参数还设有`thinking: {type: disabled}`，即未启用显式思考模式；这与代码是否等待API完成是两个问题。无实时性要求时，可将推理模式和规则理解作为小规模对照的候选因素，但目前没有启用思考后的对照证据，不能据此认定它就是停滞原因。本次仅核对参数，未改模型设置或重新调用。

## V3.3修复与证据边界

- **确定性兼容。** 单层唯一`action`包装可以展开；冗余`kind/target/params`必须与当前候选完全相同；仅含`source_ids/hypothesis`的立项`params`可映射为`analysis`。未知字段、重复JSON键、冲突内容和错误候选哈希继续拒绝。省略来源类型前缀只按本次允许来源作唯一精确匹配，之后仍执行送达、版本、权限和窗口校验。
- **一次模型修复。** 原文、规范化结果和转换规则同时保存，独立审计重新推导。C错误反馈含字段路径、重复位置或引用问题及合法结构示例；程序不合并主题、不改写假设。规范化及一次修复后仍非法，则暂停该组并保留失败原件，继续其他组，不用等待动作或C原文回退掩盖失败。
- **局部传输重试。** V3显式启用最多两次重发，间隔2秒、5秒；相同内容、新UUID，并绑定逻辑调用、序号和前驱UUID。只有本地代理已结束并记账的连接/超时或429、500/502/503/504才可重发，账本与客户端错误状态必须一致。每逻辑调用最多3次实际请求，全部经过原预算。认证、预算、授权、证据或未排空错误停止执行；本地连接状态未知先排空，再按既有检查点与额度判断恢复。模型/schema失败不再自动整组重启。
- **准确业务回执。** 立项区分`topic_sources_unavailable`、`topic_sources_not_delivered`、`topic_sources_outside_signal_window`、`topic_sources_cross_district`、`topic_sources_cross_category`、`topic_distinct_episode_threshold_not_met`、`topic_already_active`及`topic_in_cooldown`。条件不满足仍消耗该轮，不进入免费格式修复。各组合应用相同的角色说明：派单先于后续专业调查，6轮为回溯窗口，分工确认不必等待他人先确认。
- **B登记后回执送达。** 当前分工的参与者确认、负责人确认和异议可在激活前送达，沿用一轮时延与维护费用。失败记录保持待发、后续逐轮重试，同一事项同轮只尝试一次维护。其他业务材料仍需原共享条件；依赖作业仍受全员确认、当前任务及实际前置材料约束，B0和旧版本确认不能取得该权限。

[真实错误回放](../../runs/v33-repair-20260911-preflight/historical-failure-replay.json)覆盖15条真实样本：6条主体输出、4条C输出和5次实际混组立项，均符合预期。可兼容响应进入原校验，001的重复C主题仍被拒绝；5次原立项均准确返回跨片区原因。另1条错候选哈希边界明确标为合成样本。旧校验器从冻结源码隔离加载，未恢复或改版旧world；原文件哈希保持不变。篡改规范化结果或规则的反例由完整运行审计拒绝。

[停滞诊断](../../runs/v33-repair-20260911-preflight/stall-diagnosis.md)解释的是旧100/110完整轨迹：100派单主体60轮均等待，供水/协同主体各60轮没有其他候选，负责人57轮等待、3次混组立项；110四角色分别等待58/45/46/58轮，2次立项混组，3条应向其他参与者送达的确认中有1条到期末仍未送达。两组均未创建项目，因此低办结发生在前端派单、立项和个案协同阶段，不能归为施工失败。可见其他候选不保证业务条件满足，等待也不自动等于错误；这些诊断不证明V3.3已改善真实模型行为。

## V3.3离线验收与重跑费用

完整离线套件**341项全部通过**，包含已安装SciPy数值对照，见[检查记录](../../runs/v33-repair-20260911-preflight/offline-suite-final/unit-tests.json)和[日志](../../runs/v33-repair-20260911-preflight/offline-suite-final/unit-tests.log)。验收针对来源/送达、一次修复、重试结算与未知用量、业务消耗、B费用与旧版隔离、恢复副本和独立审计。

**官方AgentSociety/Ray八组合各60轮全部通过**：共480轮、1920份观察和1920份动作。111从第5轮完整副本恢复至60轮，与不间断运行的世界、动作、观察及指标一致；失败原件哈希未变，异步事件顺序差异经过核对。见[框架与恢复验收](../../runs/v33-repair-20260911-preflight/framework-acceptance.json)。另用[合成故障恢复场景](../../runs/v33-repair-20260911-preflight/pending-recovery-acceptance.json)验证待发B确认、费用不足后的再次发送以及失败请求记录恢复：复制后仍只计2个实际模拟请求，1个未知用量保持未知。该补充场景使用手工检查点元数据和假上游，不冒充官方研究轨迹；官方完整运行证据与它分别标注。

[新版费用估算](../../runs/v33-repair-20260911-preflight/single-seed-cost-estimate.json)按上述八组完整60轮材料重建当前提示，中心估算**87.35元、2335.5次请求**；仅供参考的20%余量为**104.82元、2803次请求**。启动确认前剩余85.90元比中心估算少约1.45元，剩余1445次请求比中心估算少约891次；因此随后按本页执行节另行确认累计上限。下表是规划估算，不是实测费用。

| A/B/C | 期望请求 | 中心费用/元 |
|---|---:|---:|
| 000 | 248.40 | 8.77 |
| 001 | 308.25 | 9.22 |
| 010 | 252.55 | 12.53 |
| 011 | 309.25 | 12.99 |
| 100 | 272.00 | 8.85 |
| 101 | 331.85 | 9.30 |
| 110 | 278.25 | 12.62 |
| 111 | 334.95 | 13.07 |

估算继续使用旧3.1的666次有效调用校准消息字节与输入token比例，以及用户提供的输入1.2元/百万、输出2.4元/百万价格快照；这不是实时平台账单。中心假设为可回查活跃回合中50%回查一次、5%格式修复、A/C输出250/1500 token、无传输重发。回查比例取0%/50%/100%时，同一脚本轨迹估算约75.21/87.35/99.48元，均保留5%格式修复。形成该估算时，真实模型的等待、材料增长、服务缓存、输出长度和重试频率尚未实测；20%不是统计上界或完成保证，也未在该验收阶段添加到原授权上限。随后实际执行见本页顶部，因五组提前失败，17.78元实测估算不能作为八组完整运行成本。

[总验收记录](../../runs/v33-repair-20260911-preflight/verification.json)集中绑定修复源码、测试、框架/合成恢复、历史回放、停滞诊断及预算原件哈希。

离线验收结束时，原阶段累计上限仍为102.90元、2803次请求，已占用16.997976元；13次尝试和2次自动恢复均已用完。该验收过程未修改账本或授权。随后用户确认的V3.3启动与累计额度修订见本页执行节，旧费用未删除。

## 当前研究口径

比较固定60轮内，`000–111` 八种组合对治理结果及四类办理主体实际 token 消耗的影响。保持四类角色、12个初始问题；按种子配对初始环境、外生随机数、模型设置、资源和技术标准。静态开关只取0/1，强度、顺序与人员异质性不进入本版执行范围。随机数配对不代表模型输出可复现。

| 政策 | 关闭 | 开启 | 共同边界 |
|---|---|---|---|
| A：个案匹配辅助 | 派单主体默认收到待派工单原文与职责目录 | 默认收到同一工单来源的摘要、部门建议、引用和不确定性；原文可回查 | 不读取隐藏责任答案、不强制采纳；普通派单不再区分“标记采纳”或虚构认知成本 |
| B：跨部门协同流程 | 个案、项目通过普通请求与手动材料交接推进 | 个案调查明确跨部门需求、项目拟案明确跨部门职责后，自动登记必经流程，登记后发送当前版本确认和异议；全员确认与实际材料送达后才可开展依赖工作 | 确认不等于履约；旧版本确认不能授权新拟案；允许异议、调整、等待和有据撤项，不能撤出联办后绕行 |
| C：跨个案分析辅助 | 项目负责人默认收到最近6轮原始诉求及本人依法收到的调查材料 | 默认收到相同范围的高频分析、关联引用、待验证假设、证据缺口和调查建议；原文可回查 | 不提供隐藏根因，不替代调查、评审或物理投运；任务包派发、自动共享和跟踪由B控制 |

C0不再免费收到聚合主题或由聚合答案预生成的立项候选。所有组合共享一个“提交专题分析”入口，由主体引用实际送达原文或分析实际引用的诉求，提出待调查假设。时间窗口、同片区同类别、独立问题去重、最低3个问题及活动项目/冷却校验完全相同；原文索引本身不算已读证据。`001` 具有分析辅助并使用普通协作，`011` 同时具有分析辅助与B流程。分析错误或资源不足仍可能带来延误和失败，基准主体也可独立分析并成功治理。

## 材料、调用与核验

`materials.source_index` 记录有权访问的来源，`raw` / `delivered_raw_ids` 记录实际原文送达，`analyses` 单列整理结果。来源绑定内容版本、创建时间、接收主体与收到时间。必要输入默认送达，核心比较不依赖主动查询；专业调查、职责规则、资源及依法可见流程状态在各组保留。

同一主体每轮最多两次批量 `read_materials`，随后提交一个业务动作；读取不占仿真轮次或额外劳动。选择候选、专题分析与读取协议合用一次格式修复额度，因此每轮最多4次办理模型逻辑调用；空正文或输出截断直接保留失败记录，不伪装成格式修复。原文返回后按新上下文重新绑定候选。决策提示包含本轮实际送达材料及最近3轮真实动作/回执；不得拼入未收到记录。A/C服务只接收重建出的合法来源和公共规则，结果明确标为分析或假设。

运行保存 `observations.jsonl`、`material_reads.jsonl`、主体 `decisions.jsonl`、`policy_services.jsonl`、`model_requests.jsonl` 以及检查点缓存。核验器重放世界与动作，逐项检查观察投影、完整提示/历史、材料查询、候选/专题引用、服务输入和缓存；缓存限定运行及材料版本，恢复保留来源与记录前缀。旧状态、旧接口与旧设计不直接恢复或重标为3.3。

## token与治理结果并列评价

研究指标为 **T_agent = 四类办理 agent 所有实际调用的 input tokens + output tokens**，包括阅读整理材料、回查后的判断、格式修复、已发生失败和恢复重做。政策A/C生成的 token 只作为预算核验信息保留，不进入研究指标或政策效率表。既有单一预算控制器继续约束全部实际请求；原收费阶段的累计约束见下方历史记录；V3.3真实执行接续原账本和基线，按本页执行节批准的累计额度控制，不重置、不另建。

请求发出前持久化用途、唯一UUID、运行/尝试/角色/轮次及提示/请求体哈希，控制器逐笔保存同UUID预算回执。用量仅取上游实际报告的输入、输出计数；已包含在输出中的思考token不再叠加，不用字符数折算研究token。同UUID的恢复副本只计一次；相同提示实际重发产生新UUID并计新消耗。缺用量保留已知下界和未知调用数，总数设为缺失；用途或回执无法对账的记录不能进入完整token比较。

每个完整运行输出输入/输出拆分、角色与轮次分布、累计曲线数据，以及最终轨迹和失败/重做消耗。彻底失败的尝试仍报告已知下界；无法核验其完整轨迹时，用量单列为未分类，不冒充最终轨迹或完整比较。治理结果包括累计未解决问题负担、初始问题解决情况、期末积压、施工/投运/物理修复及行政验收；新增与复发问题结合可再次发生问题的设施暴露轮次解释，不能把一直未解决造成的“没有新增”解释为预防成功。

T_agent与累计负担U分别计算7个组合相对000的配对差，以及6个第三因素条件下的两因素交互；使用原单位，不把U的[0,720]界限套给token。分析给出配对差、逐比较t区间和每个结果13项检验族内的Holm校正，并报告缺失；离线脚本输出仅供描述和程序验收。结果更好或相当且token更少，才可描述观察到的效率优势；方向冲突报告权衡，不临时加权总分。“每初始问题解决token”只作辅助，零解决时为缺失。

## 设计与复现入口

- [机器可读协议](design_protocol.json)与[八组合模板](design-8.json)同步为V3.3。通用模板仍为8个配对种子、64条记录，`formal_n=null`，不代表批准多种子执行；本次八组单种子离线清单为[design-1.json](../../runs/v33-repair-20260911-preflight/design-1.json)。
- [源码冻结记录](../../runs/v33-repair-20260911-preflight/source-freeze.json)只保存离线验收的源码证据，根目录仍是唯一维护实现，不授予收费权限。
- 纯脚本世界入口：`tools/run_v3_offline.py`；官方框架脚本入口：`tools/run_v3.py --manifest <新版离线清单> --run-id <编号> --mode scripted --steps 60 --output runs/<新目录>`。
- 整体框架与恢复复现：[check_framework.py](../../runs/v33-repair-20260911-preflight/check_framework.py)；合成故障补充：[check_pending_recovery.py](../../runs/v33-repair-20260911-preflight/check_pending_recovery.py)；历史原文回放：[replay_failures.py](../../runs/v33-repair-20260911-preflight/replay_failures.py)。恢复脚本使用新目录，不覆盖旧原件。
- 诊断入口：`tools/diagnose_v3_stalls.py --runs <原始运行目录...> --output runs/<新目录>/stall-diagnosis.json`；输出包括JSON和Markdown，拒绝写入被诊断的原始运行目录。

离线成功只证明程序、流程与证据路径可执行，不证明真实模型会有效治理，更不能直接证明现实政策因果效应。技术劳动、施工时滞与外生风险仍为探索性假设。

## V3.2历史：单种子执行结果与费用

本节保留2026-09-11 V3.2收费批次的当时事实；下列“本次”“当前”均指该已结束批次，不构成V3.3执行授权。

本次固定外生种子3001，计划八组合各运行一次、每次60轮，共480轮；只作描述性比较，不计算跨种子的标准误、置信区间或显著性。执行冻结使用 `frozen_single_seed_descriptive`，`formal_n=null`，不会借此批准后续多种子实验。

实际没有取得八组完整结果。最终状态与逐笔账目见[结果及收尾核验](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-final-results.json)，原始失败定位见[统一故障记录](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-failures.json)。表中的失败轮数为最后完整检查点，未提交的末段及恢复重做调用另行保留并计费。

| 组合A/B/C | 最终状态 | 最后完整检查点 | 完整运行T_agent | 完整运行U | 终止原因 |
|---|---|---:|---:|---:|---|
| 000 | 未完成 | 45 | — | — | 动作字段/包装错误，一次恢复后再次格式失败 |
| 001 | 未完成 | 50 | — | — | C同组重复主题，一次格式修复后仍失败 |
| 010 | 未完成 | 30 | — | — | 上游传输错误，用量未知 |
| 011 | 未完成 | 25 | — | — | 动作使用kind/params等非协议字段，格式修复失败 |
| 100 | 完成且核验通过 | 60 | 1,668,403 | 720 | — |
| 101 | 未完成 | 20 | — | — | C引用省略source_id前缀，格式修复后仍失败 |
| 110 | 完成且核验通过 | 60 | 3,004,750 | 712 | — |
| 111 | 未完成 | 5 | — | — | 上游传输错误，用量未知 |

两个完整运行中，100解决初始问题0/12，110为1/12；期末均有12个未解决问题，均没有物理生效项目。T_agent只含办理主体的实际输入和输出token，不含A/C生成服务。000及其他五组缺少完整结果，预定26项配对对比均不可计算；[收集结果](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-collected-records.json)与[描述性分析](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-analysis.md)保留排除原因和失败尝试用量，不能据此给出八组合效率排序或现实政策因果结论。

修复版新增1058次请求，预算占用13.7517012元；加修复前300次请求、3.2462748元，本阶段累计1358次请求，已报告用量折算16.8748416元，另保留2次未知用量请求的0.1231344元，**累计预算占用16.997976元，102.90元上限内剩余85.902024元；请求上限内剩余1445次**。这是完成与失败尝试合计，不是八组完整60轮的实测成本，也不是已核对的平台账单。

本阶段累计13次尝试、2次自动恢复均已用完，当前没有追加收费恢复授权。源码在执行期间保持冻结，309项离线验收对应的源码哈希未变；全部1058个修复版收费请求的UUID和请求体哈希与原始模型审计逐项一致，恢复副本去重、最后检查点哈希、失败原件、登记表哈希链及控制器退出检查均通过，API和框架锁已释放。实际失败仍表明模型会违反动作/来源/分组协议，并存在传输不稳定；提示修正和离线通过不能保证真实模型完整执行。下一轮收费前需先处理输出协议与恢复机制的可靠性，并明确新的执行范围。

[费用估算明细](../../runs/v3-formal-20260911-preflight/single-seed-cost-candidate.json)按新版官方脚本完整60轮的观察、动作与服务输入重建提示，以历史3.1的666次有效调用校准消息字节与输入token关系。旧数据仅用于费用量级校准，不是新版实测结果。单价沿用用户提供的价格快照：输入1.2元/百万token、输出2.4元/百万token；不代表实时账单核验。

中心估算85.7495元，按用户要求仅加20%，本轮增量上限为**102.90元**；期望请求2335.5次，加20%向上取整为2803次。中心假设为可回查的活跃回合中50%回查一次、每个活跃主体回合或唯一政策服务有5%格式修复，A/C服务输出分别250/1500 token。上述频率与输出长度未实测；20%是预算余量，不是统计上界或完成保证。估算使用60轮实际材料增长，不能把旧30轮费用简单翻倍；真实模型动作可能改变材料、空闲回合及缓存命中。

所有实际收费请求（含政策服务、失败与恢复）接续既有本机账本，执行保持每5轮完整副本、每次运行最多一次技术恢复、全批最多两次恢复。单种子执行入口新增两个边界检查，完整离线套件308项通过，见[本次测试日志](../../runs/v3-formal-20260911-preflight/single-seed-offline-suite-complete.log)。

修复前执行证据：[冻结设计](../../runs/v3-formal-20260911-preflight/single-seed-manifest.json)、[公式授权与预算](../../runs/v3-formal-20260911-preflight/single-seed-authorization.json)、[源码与输入冻结](../../runs/v3-formal-20260911-preflight/single-seed-freeze.json)、[暂停批次状态](../../runs/v32-single-seed-20260911/batch_status.json)、[修复前汇总](../../runs/v3-formal-20260911-preflight/single-seed-progress.json)。这些原件保留修复前事实；修复版执行入口见下方批准记录。

本次暂停时，`000`的60轮已通过完整独立核验，`010`已干净保存到20轮；`101`在初始尝试及一次恢复中分别出现同组重复主题、跨片区/类别引用，两次均在允许的一次结构修复后仍未通过。共发生300次请求，按已报告token折算3.2462748元，无未知用量或在途请求。批次父进程先暂停派发，现有子分段完成、Ray及代理排空后才结束父进程；010最后提交已补记到原登记表并生成完整副本，没有丢弃已完成分段。

离线复现确认响应为完整JSON，分组拒绝符合既有规则；初始C提示缺少同组唯一主题约束，修复提示没有传递具体错误。现明确按输入原始`district/category`字段分组、一组最多一个主题，并把校验器错误加入仅一次修复请求；原有校验与信息边界未放宽，独立审计同步重建该反馈。见[诊断证据](../../runs/v3-formal-20260911-preflight/c-service-failure-diagnosis.json)和[309项离线验收](../../runs/v3-formal-20260911-preflight/c-service-repair-verification.json)。修复后101组第5轮检查点的12条A、2条C真实服务响应均通过独立来源、提示、输出与缓存审计，未使用服务格式修复，见[首批真实服务核验](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-first-services-audit.json)；这不代表整个60轮已完成或模型长期稳定。

[重做方案原件](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-proposal.json)已获[用户确认](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-user-approval.json)：保留全部旧原件为修复前诊断证据，用单一修复版源码重新完成八组合各1次、每次60轮，包含重做已完整成功的000。原授权ID、1067笔历史基线、账本、102.90元/2803请求累计上限均保留；重启前已发生的300请求和3.2462748元仍占用额度，当时剩余2503请求、99.6537252元，不另加一份20%额度。累计尝试上限现为13，即既有4次、修复版8次和原授权尚余1次自动恢复。修复版八组中心估算约85.80元，连同已发生费用约89.04元，仍非保证上界。旧数据不得重标为修复版结果或混入其八组对比。执行绑定见[批准后设计](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-manifest.approved.json)、[累计预算授权](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-authorization.json)、[运行前冻结](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-freeze.json)；完成后由[修复版汇总](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-progress.json)记录实际核验和累计用量。

修复版000组另发生办理主体动作格式错误：初始尝试在尚未提交的第29轮添加`action`包装，恢复后在尚未提交的第49轮添加禁止的`kind`字段，均在一次具体错误反馈后仍未通过。最后干净检查点为45轮，耗用了本授权剩余的1次自动恢复；该组标为未完成后，控制器继续执行了剩余组合，期间未修改冻结的模型、提示或校验器。见[动作格式失败原件复现](../../runs/v3-formal-20260911-preflight/single-seed-c-repair-000-failure-diagnosis.json)。当前没有完整的修复版000基准，不能将其部分轨迹或修复前000冒充完整配对对照。

### V3.2当时的离线验收

- [机器可读协议](design_protocol.json)与[八组合模板](design-8.json)：模板为8个配对种子、64条静态记录，`formal_n=null`，不是正式N或执行授权。可用 `tools/build_v3_design.py`生成指定数量的离线模板；旧U单指标样本量自动冻结逻辑已停用。
- 纯脚本世界验证：`python -B tools/run_v3_offline.py --design research/v3_1/design-8.json --output runs/<新目录> --coverage`。
- 官方框架脚本入口：`tools/run_v3.py --manifest <新版模板> --run-id <编号> --mode scripted --steps 60 --output runs/<新目录>`。`llm`模式在创建运行输出及调用模型前要求另行冻结的设计、N、源码和有效收费授权。
- 完整离线检查：`python -B -m unittest discover -s tests -v`。本版收费前**306项全部通过**，包括已安装SciPy数值对照；见[测试记录](../../runs/boundary-token-20260911-preflight/final-suite-complete/unit-tests.json)和[测试日志](../../runs/boundary-token-20260911-preflight/final-suite-complete/unit-tests.log)。单种子入口与C修复后的追加验收见本页顶部。
- **官方AgentSociety/Ray八组合各60轮全部通过**：480轮、1920份观察与1920份动作通过独立核验；`111`从第5轮副本恢复至60轮，失败原件哈希不变，业务状态、动作、观察和指标与不间断运行一致，异步原始事件排列允许已核验差异。见[框架与恢复验收](../../runs/boundary-token-20260911-preflight/framework-acceptance.json)。
- 最后仅补充独立核验器对彻底失败尝试的用量报告，仿真与运行时源码没有变化；原框架源码作为运行证据保留，新核验器已重新核验全部八组及恢复、失败目录。收集与分析出口接受8个离线运行，生成T_agent和U共26个对比；见[总验收记录](../../runs/boundary-token-20260911-preflight/verification.json)、[收集结果](../../runs/boundary-token-20260911-preflight/collected-records.json)及[离线分析](../../runs/boundary-token-20260911-preflight/offline-analysis.md)。脚本token为0只表示无模型调用，不能据此评价效率。本轮真实API调用为0。

上述记录对应本版收费前验证，当时尚未同步云端或调用真实模型；后续本机真实执行见本页顶部。离线通过只证明程序实现、证据与计量路径，不能证明模型会怎样选择，也不能证明现实政策有效。技术劳动、施工时滞和外生风险仍是探索性假设。


## V3.1历史：消息容量与故障恢复修复（2026-09-11）

用户已批准实施修复计划，并要求完成原六组30轮诊断。消息请求窗口按本阶段授权扩大至1MiB，保留完整观察、近三轮历史、现有提示及 `v3.1-candidate-id-2`；模型、4096输出上限和一次格式修复规则保持原冻结设置。默认旧请求窗口仍为96KiB，费用按实际序列化请求字节预留。

每个成功的5轮分段在官方driver退出、Ray关闭和代理请求排空后，保存整个工作目录的独立副本，核验全部文件哈希后发布。失败路径原样保留，恢复只使用最后完整副本并写入新尝试目录；审计核对复制日志前缀及原控制器回执，复制响应不重复计为新增调用。自动技术恢复上限为每组1次、整批2次，持久化尝试记录约束控制器重启；本组耗尽恢复次数后继续其他组，预算、授权、证据或共享运行时异常停止整批。

修复已完成：281项完整离线测试通过，六组官方框架脚本均完成30轮并通过核验；最终冻结源码上的半轮失败恢复也从第5轮副本续跑至30轮，与不间断运行的业务状态、120份动作/观察和指标一致，失败原件哈希保持不变。异步日志顺序允许存在已核验的差异。原112364字节客户端请求和原提示逐字回放通过；原有代理添加 `n=1` 后转发112372字节，入口与转发上限均为1MiB。完整范围与证据见[本次修复验收](../../runs/mac-capacity-recovery-20260911-preflight/verification.json)、[完整测试日志](../../runs/mac-capacity-recovery-20260911-preflight/offline-tests-final.log)和[最终源码恢复验证](../../runs/mac-capacity-recovery-20260911-preflight/final-recovery/framework-acceptance.json)。

用户已明确确认向既有模型接口发送本次合成实验输入。两次原始大请求真实验证均通过：正常结束、正文非空、候选及动作校验通过、完整响应保留且原提示逐字一致；新增2次请求，估算0.0830064元，详见[真实容量探针](../../runs/mac-capacity-recovery-20260911-preflight/live-capacity-probes/report.json)。

**本次六组真实模型诊断已于2026-09-11 09:18（北京时间）完成，6/6组均达到30轮并通过最终独立核验。** 共180轮、720份观察和720份动作记录；重建请求体哈希与账本逐项对应，用量、动作重放、指标重算、检查点和恢复来源均通过。源码在收费执行期间保持冻结，实际最大请求体130717字节。完整汇总见[最终结果与分项账目](../../runs/mac-capacity-recovery-20260911-preflight/final-results.json)，每组独立报告保存在[核验目录](../../runs/mac-capacity-recovery-20260911-preflight/verified/)。执行目录为 `runs/mac-diagnostic-capacity-20260911/`；[批次状态](../../runs/mac-diagnostic-capacity-20260911/batch_status.json)记录恢复后各组的实际证据路径。执行器已正常退出，五分钟汇报已暂停。

第5组（种子1002，A0/B0/C0）发生一次代理访问上游的传输错误，本地返回502；当时请求体28582字节，未触及容量上限。控制器从第10轮完整副本自动恢复并续跑至30轮，失败原件保持原哈希，复制的历史响应只计一次。整批共7次运行尝试、1次自动恢复，未超过每组1次／整批2次限制。失败分段的8次请求独立保留：7次有用量的估算费用0.0667992元，1次用量未知，继续保留0.049044元预算预留，合计占用0.1158432元；不把未知用量当作零费用。

下表仅描述这六组诊断，不能据此认定正式政策组合研究完成或推断现实政策因果效应。有效请求仅计入最终完整轨迹，失败分段与容量探针另计。

| 种子 | 情景（A/B/C） | 初始12个问题已解决 | 期末未解决问题 | 物理生效项目 | 行政验收项目 | 有效API请求 | 用量估算费用/元 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1001 | 0/0/1 | 0 | 12 | 1 | 1 | 112 | 1.9364688 |
| 1001 | 0/1/0 | 0 | 12 | 0 | 0 | 107 | 1.0405872 |
| 1001 | 0/0/0 | 0 | 12 | 0 | 0 | 108 | 0.9931032 |
| 1002 | 0/0/1 | 1 | 12 | 1 | 1 | 112 | 1.9038648 |
| 1002 | 0/0/0 | 1 | 11 | 0 | 0 | 115 | 1.2046104 |
| 1002 | 0/1/0 | 1 | 12 | 0 | 0 | 112 | 0.9053748 |

本次六组批次新增674次请求，其中666次进入最终轨迹、8次属于失败分段；已报告用量的估算费用8.0508084元，加未知用量预留后预算占用8.0998524元。另有两次容量探针0.0830064元，因此整个修复验证与重跑阶段新增676次请求、预算占用8.1828588元。接续原391次／5.4432852元后，同一本机账本累计1067次，已报告用量估算13.5771000元、未知用量预留0.0490440元，**总预算占用13.6261440元；20元／1440次上限内剩余6.3738560元／373次**。无在途请求，1次已结束请求的用量未知；估算及预留均不是已核对的平台账单，本机账本也不包含未迁入的云端历史。

启动核验见[真实启动预检](../../runs/mac-capacity-recovery-20260911-preflight/live-launch-preflight.json)，恢复规则、输入及源码绑定见[冻结授权](../../runs/mac-capacity-recovery-20260911-preflight/authorization.json)。本次授权截止时间为2026-09-11 14:56:47（北京时间）；六组完成后未继续启动收费实验。

此前候选编号版本的首组在第27轮被本地96KiB请求限制拦截，26轮后状态包含未提交主体更新，不能直接恢复。旧运行目录 `runs/mac-diagnostic-20260910-candidate-v2/` 作为失败证据保留；该批完成数为0/6。下节保留截至各历史启动点的记录，不能作为本次实时进度。

## V3.1历史：改造前政策边界核查（2026-09-11）

本节记录改造前的源码与离线程序边界核查；下列“当前”均指当时的3.1状态。用户进一步明确：B应作为适用事项必须遵循的流程；A与C须区分政策专属分析服务和基准主体自身分析能力。逐项证据、源码哈希、离线对照及适用范围见[边界核查记录](../../runs/policy-boundary-audit-20260911/audit.json)。

- **A的信息与计量边界。** A0没有推荐对象，A1会额外提供推荐；真实辅助模型只读取办理主体已经拥有的工单字段与职责目录，并使用同一声明模型。没有按材料检索量或分析复杂度另计基准认知成本。模型已看到建议后，仍可选择相同去向的普通派单；固定种子对照中，普通与标记采纳分别消耗0.6、0.8劳动，采用标记分别为假、真。因此采用标记不能证明是否受建议影响。额外分析调用是否有行为增益仍需专门验证，不能从输入相同推出必然零效应。
- **B的流程边界。** 同一公开文本明确的跨部门事项，在B0和B1下均可合法执行普通派单、调查、普通协调、分项工作与手动回执，均在第6轮解决；全过程未激活联单，无业务拒绝。当前B1提供可选联合服务，不满足此次明确的强制流程定义。
- **C的识别边界。** 固定种子1001的初始C0与C1均收到相同四个聚合高频主题、原始工单及公共规则，主题仅强化准入标记不同；普通项目候选在两组均存在。沿既有合法观察脚本运行C0共60轮，可产生两个普通源头项目的物理生效。这证明基准保留相关能力，不代表自主模型能够稳定实现。当前C的增量主要是结构化任务包、自动派发和授权记录归集，而非独占高频识别与根因诊断。
- **组合机制边界。** A不改变C聚合使用的公开类别；B限定个案协同，不控制C项目内部组织。相同四步结构化立项/拟案动作在001与011下都自动向部门2、3派发评审，四个主体的最终观察完全一致。因此当前实现没有操作化“A分类改善C识别”和“B改善C内部协同”这两条机制；个案进度、资源竞争及后续诉求仍可能形成其他交互。

上述发现促成了本文顶部的3.2改造。该次边界核查无收费API调用；当时的离线对照用于证明旧程序路径及输入差异，不作为正式政策效应数据。

本节是3.1实现改造前的诊断证据。原先讨论过把政策服务生成与办理调用合计为研究成本，以及人员异质性、人工查询劳动等扩展；这些建议已由本文顶部的3.2决定替代。新版只以实际办理 agent token 作为研究指标，政策生成仍纳入全请求预算账本；暂不增加人员差异或查询劳动设定。

## 历史执行与价格依据（2026-09-10）

用户随后明确要求“修复并从新开始实验”。候选编号及修复反馈已修正，264项完整离线测试通过，当前已启动新版接口的六组诊断，第一组已形成5/30轮完整检查点。当前执行目录为 `runs/mac-diagnostic-20260910-candidate-v2/`，见[当前授权](../../runs/mac-diagnostic-20260910-candidate-fix-preflight/authorization-candidate-v2.json)、[冻结清单及版本对应](../../runs/mac-diagnostic-20260910-candidate-fix-preflight/diagnostic-manifest-candidate-v2.json)和[启动核验](../../runs/mac-diagnostic-20260910-candidate-fix-preflight/protocol-preflight.json)。五分钟汇报已恢复；运行中的最新进度以控制器和账本为准。

接口升级为 `v3.1-candidate-id-2`：候选标签由74字符改为顺序号加64位上下文哈希前缀（通常20字符），完整256位哈希继续保留在观察和响应证据中。角色、轮次、可见事实和动作列表均参与上下文计算；解码重新计算并精确匹配，不模糊纠错或代选。一次修复提示明确列出校验错误及本轮合法编号；审计同步验证这些反馈，并拒绝已提交轨迹中出现空正文或非 `stop` 响应。原失败轮17个候选的内容和顺序保持一致，离线回放及边界见[修复回归](../../runs/mac-diagnostic-20260910-candidate-fix-preflight/regression.json)。该回放的成功修复响应为脚本提供，不能当作真实模型验证；长程输出表现由新六组运行检验。

新版所有六组从0轮开始，原条件、种子、轮数及运行顺序不变；旧版本已完成组不能作为失败重试，因此冻结了带 `_candidate_v2` 后缀的独立运行编号，并保留旧编号对应关系。首次复用编号被启动保护拒绝，未发出API请求、未改变尝试记录，见[启动保护记录](../../runs/mac-diagnostic-20260910-candidate-fix-preflight/startup-guard.json)。账本仍为同一独立本机账本，以累计296次、4.1548896元为起点；新阶段最多1144次、15.8451104元，累计上限仍是1440次／20元。旧版本结果与本次不拼接。完整测试日志及源码快照见[预检记录](../../runs/mac-diagnostic-20260910-candidate-fix-preflight/preflight.json)；原生命周期固定基准未重建，仅在测试边界把新编号投影为旧展示格式后比对，16条轨迹及2类恢复基准全部一致。

此前输出兼容修复后的重跑完成1/6组，在第2组第18轮停止，证据保留于 `runs/mac-diagnostic-20260910-rerun/`，见[此前重跑授权](../../runs/mac-diagnostic-20260910-rerun-preflight/authorization.json)与[此前启动核验](../../runs/mac-diagnostic-20260910-rerun-preflight/preflight.json)。该次新增178次请求、估算2.2043328元，停止时累计296次、4.1548896元，均已结算。此次停止与下文首次失败、接口探针均属于历史阶段，不计入当前完成进度。

此前停止原因已离线定位：角色1返回的JSON完整且以 `stop` 结束，但把合法候选编号中的 `4a78bb` 写成了 `4a24bb`，一次格式修复后仍返回同一错误编号。177条已保存动作响应中仅这2条无效；全部响应的提示内候选、记录内候选与程序重新计算的候选一致，未发现本地绑定漂移。仅在诊断副本中改正这两个字符，即可通过同一动作解码与校验；对应合法动作是向部门2派发 `T:F2-3:0`，与模型理由吻合，支持长哈希抄写错误的解释。批次因严格候选校验及一次修复上限停止；第2组完成17轮，最后完整检查点为15轮，其余4组未启动。详见[候选编号失败诊断](../../runs/mac-diagnostic-20260910-rerun-preflight/candidate-id-diagnosis.json)。该次原因分析没有修改运行时、替模型提交动作或新增收费请求；后续获用户授权的修复及重启见本节顶部。

用户已选择在当前 Mac 执行。重构后247项离线测试及一个代表情景的官方框架30轮脚本运行、恢复和不间断对照已通过；完整范围及异步日志顺序差异见[本机集成记录](mac_integration_20260910.md)，阶段条件见[就绪检查](readiness_20260910.md)。下文228项测试、94情景和云端状态保留为此前验证的历史事实。

用户20:25:33截图中，当前模型 `deepseek-v4-flash` 输入1.2元、输出2.4元／百万Token，`bge-m3`显示免费；不要混用 `deepseek-v4-flash-0731` 的3/9元费率。截图为用户提供的当前价格证据，未独立核验实际账单。原图、哈希及结构化费率保存在[价格证据](../../runs/price-evidence-20260910-202533/price.json)，同目录保留 `pricing.png`。

6组诊断共180轮、请求硬上界1440次。按现有代理的96KiB请求体限制、4096输入预留和4096输出上限，全部请求均达到最大预留时合计191.102976元；这是保守预留上界，不是预计花费，也不意味着应授权该金额。完整6组的实测费用与耗时仍未知，部分运行及接口探针统计见下文。见[更新报价](../../runs/price-evidence-20260910-202533/diagnostic-quote.json)。上述 runs 证据只在当前本机保存，不随 Git 分发。

用户随后明确批准本机6组真实诊断：增量20元、最多1440次请求、任一上限即停、不自动重跑失败运行，并批准独立本机账本作为接续旧账本规则的例外。执行仍使用原代理、请求预留、单控制器锁及检查点保护；独立账本为 `runs/api-local-budget.json`，尝试记录为 `runs/v3_local_control/`，密钥沿用已存在的 `.env`。云端原记录标为未迁入，独立本机统计不代表账户全部历史消耗。授权与冻结证据见[当前执行授权](../../runs/mac-diagnostic-20260910-preflight/authorization-corrected.json)，执行数据保存于 `runs/mac-diagnostic-20260910-execution/`。

首次启动在配置检查阶段失败：本机接入代码误把 `/v1/chat` 当作 API base；真实配置 `/v1` 正确。该尝试没有启动 driver/Ray，API请求及费用均为0，失败记录完整保留。已修正后缀解析，实际配置读取通过，253项完整离线测试通过。随后在原6组仿真授权内启动：尝试记录容量包含1条零请求配置失败和6条原计划仿真，不增加科学重复数或付费重跑，不清除失败记录；20元/1440次请求上限不变。见[失败与修正核验](../../runs/mac-diagnostic-20260910-preflight/preflight-failure-review.json)与[修正后启动核验](../../runs/mac-diagnostic-20260910-preflight/corrected-launch-preflight.json)。

此前首次本机真实诊断已停止：首组完成25/30轮，在第26轮角色1首次响应及唯一一次修复均返回空正文、`finish_reason=length`，每次输出4096 token；其余5组未启动，完整完成数为0/6。112次请求均为HTTP 200，估算费用1.8934032元，未触及20元或1440次请求上限。当时五分钟进度定时器已暂停，未自动重跑。部分运行不能作为完整情景结果。

对原失败运行的离线复核发现15次长度截断（14次空正文、1次不完整JSON），此前13次通过一次修复恢复，最后一次连续失败。已按实际序列化方式重建全部112份请求体，与预算账本的请求哈希逐一相符，确认本地向上游发送了 `thinking: {type: disabled}` 和4096输出上限。上游报告的思考token约占输出95%，但部分非空正文仍报告文本token为0，因此该细分计数仅作为上游报告，不能视为独立验证。当时的解析器将截断统一当作格式错误，在同一输出上限下请求修复，最终通用报错掩盖了直接原因。

详细统计、失败请求编号和核验边界见[原输出失败诊断](../../runs/mac-diagnostic-20260910-preflight/model-output-diagnosis.json)。[DeepSeek官方说明](https://api-docs.deepseek.com/guides/thinking_mode/)和[无问芯穹说明](https://docs.infini-ai.com/gen-studio/api/text-generation/tutorial-reasoning/deepseek.html)均支持该关闭参数写法，但文档本身不能证明网关实际路由生效。

## 输出兼容修复与真实接口验证（2026-09-10）

用户明确批准了最多6次、0.50元的定位和修复验证，计入现有20元/1440次累计额度。已完成全部6次，估算费用0.0571536元；本机账本累计118次、1.9505568元，原112条记录的哈希保持不变。前2次最小候选任务通过；随后2次原失败轮完整输入均返回空正文、`length` 和4096输出token。取证点位于原预算代理的上游响应入口，正文与实际客户端返回逐字相符，排除了本地丢失正文；原始响应另含非空思考内容。基线两组重复请求各自返回同一响应标识，不能视为独立生成。上述费用根据上游用量和冻结费率估算，未独立核对平台账单。

网关[公开OpenAPI](https://llmapi.fiblab.net/openapi.json)声明为LiteLLM 1.85.0；对应版本[官方DeepSeek转换源码](https://github.com/BerriAI/litellm/blob/v1.85.0/litellm/llms/deepseek/chat/transformation.py)会删除 `thinking: disabled`。已从匹配版本提取相关方法进行无网络复现，证明加入 `allowed_openai_params: [thinking]` 后该设置可以保留，见[参数转换复现](../../runs/model-output-probe-20260910/parameter-reproduction.json)。未检查网关的私有路由配置，因此这是与实测吻合的兼容性定位，不声称读取了实际服务端调用链。

最小运行时代码修正位于共用客户端和V3输出解析：明确传递已有的关闭思考设置，并按[网关缓存协议](https://docs.litellm.ai/docs/proxy/caching)设置 `cache: {no-cache: true, no-store: true}`；模型、观察、历史、候选、提示和4096上限保持一致。V3在解析前检查结束原因和空正文；截断或空响应直接留下分类错误并停止，不再请求格式修复。完整但格式或候选不合法的正文仍最多修复一次。没有自动代选动作。

修正后的最后2次原输入验证均通过：结束原因为 `stop`，输出分别为83和79 token，原始思考字段均为空；返回的 `candidate_id` 和 `reason` 通过本轮候选解码与动作校验，且两次响应标识不同。**本次接口验证通过，尚未证明长程稳定性或政策有效性。** 接口验证阶段没有恢复完整实验，后续授权重跑见本文顶部。原运行25轮部分结果仍属于旧行为，不能与修正后的结果直接拼接为同一完整情景。

完整离线套件262项全部通过，覆盖真实客户端适配到动作解析的保存失败回放、空正文、截断、合法输出、错误候选和一次修复边界。原失败轮完整输入离线回放也确认只调用一次并报 `output_truncated`。命令、用量、源码版本、请求哈希和验收边界见[本次核验](../../runs/model-output-probe-20260910/verification.json)及[测试日志](../../runs/model-output-probe-20260910/offline-tests.log)。探针入口为 `tools/probe_v3_output.py`，需要冻结计划与显式授权，不能绕过原账本；同一阶段不可自动重复执行。原始响应、计划、授权和修正前后源码快照均保存在该运行目录，密钥不进入证据。后续正式执行须按当前源码重新冻结授权，并接续当前累计账本。

代码在项目根目录原地维护，当前本机路径为 `/Users/zy/Desktop/AgentSoiety`（原Windows路径 `D:/AgentSociety`），该历史阶段的状态格式为 `policy-v3-3.1`。本目录只存研究说明、输入清单和审计记录，不是另一份源码。

## V3.1阶段实现记录

- **物理与行政分开。** 两项施工完成仅表示建成；角色2须取得合法派工与两项完成材料，满足时滞后执行技术投运。成功投运在下一轮边界产生物理效果；角色4收到成功材料后再行政验收。未验收不会撤销已发生的物理修复。失败投运消耗实际技术劳动和既有工程资金，不自动变成有效修复。
- **证据索引与候选编号。** 只索引主体本轮合法可见材料，区分发送、收到、本人确认与历史任务快照。模型返回本轮候选编号及理由，程序再解码为原动作；旧轮次、异角色或候选外编号拒绝。公共派单建议变化后重新绑定编号。最多一次有记账的格式修复，不自动替主体挑选行动。
- **审计与版本隔离。** 物理生效按独立事件统计，行政验收另列；候选映射、实际提交和响应记录对应核验。旧状态拒绝直接恢复为新版，旧实测结果不能重新标记为新版或用于新版用量测算。
- **单一源码。** 已把有效改动合并回根目录，删除临时 `variants/v3_1_20260910` 目录及建目录辅助脚本，清理6个编译缓存目录。云端同步保留覆盖前哈希核对，取消自动复制版本备份。`policy_mve` 的 I/O、客户端、router及基础主体仍被当前实现引用，予以保留。历史运行、冻结源码证据及原始模型响应也保留。

## 更早的V3.1离线验收记录

专项物理验证见 [physical_review.md](physical_review.md)，对应根目录 `tests/test_v3_physical.py`。完整测试命令：

```powershell
& D:/miniconda1/python.exe -B -m unittest discover -s tests -v
```

当时的旧设计包含638项待冻结候选，覆盖检查每个阶段/情景仅取一个种子。它不是当前 `design-8.json`；当前文件已改为3.2的64条静态离线模板，旧94情景结果与检查点不得混入。

完整检查结果见 [validation_summary.json](validation_summary.json)：**228项单元测试全部通过，94个阶段/情景覆盖全部通过**。其中包含3个诊断情景、8个先导端点、33个静态组合与强度情景、14个顺序情景、4个模型重复阶段的脚本路径及32个敏感性情景。上述均为离线脚本检查。

覆盖检查保留先完成的26个情景，再以3个独立进程完成其余68个，没有重复已完成情景。94份状态的重放哈希及282个结果文件均已核对；运行期间源码未变。上一轮接口实验的253个交付文件也全部保持原哈希。

完整套件首轮发现Windows临时目录权限问题和旧测试未包含投运步骤，修复测试夹具及合法操作链后复跑通过，首轮失败记录保留。可选的本地SciPy数值对照未运行，因为当前环境未安装该依赖；未为此新增安装。

## 边界

此前228项单元测试及94个情景覆盖阶段无新增真实模型/API请求；本机后续真实诊断及其失败、恢复见本文顶部。离线脚本有意选择服务及推动流程，只证明程序路径，不代表自主模型选择，也不能证明政策有效。候选编号可限制动作结构，本次六组诊断尚不足以评价其对理解、理由或等待行为的稳定影响。

技术劳动、施工时滞及外生风险仍为探索性假设，不是北京市业务校准值。没有据此改写正式研究结论。

2026-09-10较早的现场查询显示云端工作区为 `Stopped`，该状态不代表此后实时状态。当前修订尚未同步云端；本机已通过顶部链接记录的官方框架脚本执行/恢复验证，真实模型运行各阶段进度见本文顶部。若转回云端执行，应先比较两端源码及当前停止期限，再按阶段授权运行。


**行动可用性修复（候选1+2，attempt-0062之后实施）：** 新增`policy_sim/availability.py`作为行动可用性的唯一判定方：候选生成（observe）、执行裁决（_task_action）与拒绝明细共用`task_blockers`谓词。被前置阻挡的work类候选保留在行动空间中并携带`blocked_by`（仅含"本人尚未收到完成交接的前置"+核实/协同建议，不泄露世界隐藏状态）；结算拒绝回执携带`unmet`明细，`last_receipt`与business回执同步呈现；WORLD_DESCRIPTION补充指引。领域语义与行动空间不变，提示版本official-native-11、接口v3.3-materials-5；新增0062死锁回归测试（T:F1-1:0路由→inspect→blocked候选→拒绝明细），106项离线检查通过。


**attempt-0063（13:00启动，official-native-11）：第10轮因轮询耗尽失败；blocked_by修复目标达成。** 提交10轮、解决2/12、152+笔请求，environment_routing保持0，**业务性拒绝0笔**——attempt-0062的同类前置拒绝累积现象未再出现，行动可用性修复对其目标生效。失败链（新变体）：主体3作为T:F3-3:0的lead在inspect后发现任务计划唯一任务属部门2（自身无任务，request_coordination已提供），却连续8次重读visible_tickets"弄清下一步"，从未提交；静态提示的轮询指引（native-9起）对三个不同主体、三种触发均未能阻止该行为类。修复：环境在主体本轮工具调用过半（第6次起）时于读取结果带内附pace_note（"第N次调用、上限10次、提交后还需一次finish"）——仅陈述主体自身迭代事实，不替其决策；审计用记录的actor_call_index复算同一标注。pace_note置于无框架依赖的work.py（保持audit/checkpoint无密钥导入约束），提示版本official-native-12、接口v3.3-materials-6，新增回归测试，107项离线检查通过。


**attempt-0064/0065（13:10/13:26启动，official-native-12）：48轮后因评审送达缺陷停滞，按停滞规则停止。** 0064行至16轮（3/12、0拒绝）遇上游502，显式resume为0065（无密钥接续路径首次实战通过）；合计提交48个完整轮次、解决5/12、工单关闭5/12、本次目录643笔请求全部完整结算（约5.7M token），environment_routing全程为0，pace_note版零turn失败、零重复读取告警——0057以来的全部行为修复（确定性分发、空回复标注、as_of_round、批量上限、blocked_by/unmet、pace_note）在48轮内均未复发。停滞链（新缺陷，世界层信息送达）：P:1两份评审均已完成（部门3第5轮、部门2第6轮，均为revise），但`_record`只让作者本人学习记录，基线模式无评审结果向项目负责人的送达机制；主体4仅因部门3恰好主动发过一条带记录的status_reply而看到其意见，部门2的revise意见永久不可见——负责人等待一个已存在但未送达的评审，四主体连续多轮全部wait，解决自约30轮起无新增。按"resolved≥15轮无新增"规则写入停止标记优雅退出（643/643请求完整），Ray已清理。修复方向（待定）：评审完成时经业务送达机制向项目负责人投递review_completed记录（或project_package明示requested与received的差集与unknown标记），信息边界仍限已收到材料。attempt-0064/0065证据保留于`runs/deterministic-dispatch-20260914-v8-real-000`。


**评审送达修复（attempt-0064/0065之后实施）：** review_project完成时，世界将review_completed记录经既有消息运输通道作为带记录的status_reply送达项目负责人（`_message`→官方SimpleSocialSpace→receive成功后`_learn`），负责人在下一轮投递后才合法看到意见——与派单/协同邀请同机制，不提前授予知识、不改变信息边界；BUSINESS_CONTRACT的review条目同步说明。提示版本official-native-13、接口v3.3-materials-7，新增回归测试（评审意见经投递抵达负责人视角），108项离线检查通过。


**attempt-0066（13:53启动，official-native-13）：37轮后因模型记忆压倒可见状态停滞，按停滞规则停止。** 494笔请求全部完整结算（约4.3M token，约9元），提交37轮、解决4/12、0业务拒绝，environment_routing保持0。评审送达修复未获行使机会：P:1行进至planned（revision 2）后，主体4连续多轮wait，理由为"revision 2的双部门评审任务均已存在且pending，评审已请求"——但其可见状态明确显示requested.review_project为空、候选明确提供request_review(部门2/3)。世界事实：redraft至revision 2后requested列表已重置，评审须重新发起；主体4以revision 1时期的记忆否定了当前正确的可见信息（违反CONTEXT.md"历史任务状态不证明当前实际状态"原则），评审永不会到来，形成不可逆终态集体等待。第30–37轮全wait确诊后停止。【定性更正（H3诊断后）】此前"模型认识论缺陷"结论有误。回放保存观察证实：负责人视图同时含有两个pending的revision 2评审任务（"评审任务均已存在且pending"为如实陈述）与requested为空——观察自相矛盾，模型采信tasks字段是合理阅读。根因：`_new_project_tasks`在draft_plan后立即`_assign(4,...)`把未派发的模板任务写入负责人知识，视图无法区分"模板已建"与"评审已发起"。修复（H3，用户确认）：`_visible_project`对"他人+pending+当前修订+未在requested"的任务不予呈现（旧修订与已完成任务保持可见，评审可见性与验收路径不受影响，因其基于知识而非视图）；独立可见性审计以回执自算的期望revision复用同一过滤规则。回归测试断言：draft后负责人视图无pending评审任务、request_review后仅被请求部门的任务可见。接口v3.3-materials-8，108项离线检查通过。证据保留于`runs/deterministic-dispatch-20260914-v9-real-000`。


**轮内读取存根（cache-HIT语义，attempt-0067之后实施）：** 四次复发的重复读取（0059 inbox、0060/0063 visible_tickets、0067 projects，0067已能自愈但仍发生）定性为架构层缺口：环境只呈现绝对状态，从不呈现主体与本轮状态的关系，官方ReAct循环亦无任何去重机制（recent_observations原样重放重复内容）。修复：WorkContext维护轮内读取台账，同轮同页（或同来源集）且底层未变的重复读取返回显式unchanged_since_last_read存根——正文不再重发、材料配额不重复计费、无状态变动；pace_note照常叠加。独立审计按路由顺序确定性重放同一台账规则。读取接口语义变更属v3.3-materials-9，提示official-native-14；新增单元与官方循环级回归（含审计重放一致性），110项离线检查通过。注：官方API盘点确认无等价能力可替代，此为实现层于官方@tool接缝内的幂等语义；read_work与business/文件双通道的内容重复暴露留待后续收敛评估。


**账本检查记录（v11冻结前）：** request 11918为attempt-0067被外部终止时的在途请求，状态残留reserved；检查确认属主进程已死、响应未落盘、用量未知。按既有终态词汇将其标记为transport_or_decode_error（reserved_rmb 0.213644保留计入），未删除或重置任何账本行；v11 preflight以该检查后的账本为基线。


**架构对齐重构（attempt-0068之后，用户确认全面实施）：** 依据官方2.8.7源码设计意图审查（官方哲学：失败是常态/职责薄层/状态即小文件/隔离式容错/轮询式世界），拆除四处系统性矛盾：(1)失败语义——新增`policy_sim/failure.py`唯一策略方；模型质量类未完成（迭代耗尽/无效finish/未提交）按"该主体本轮未办理"如实结算（世界advance支持子集、路由abandon指令、官方兜底记忆保留），已提交但缺finish的轮次按立案处理；传输/计量/证据类技术服务失败仍全局停止。10/11次历史尝试死于被拆除的死刑语义族。(2)状态归位——`<agent>`回归官方定位（phase/轮次/角色/候选数/回执指针~1KB），完整信息只在observe与read_work；退役business/工作区文件通道。(3)检查点瘦身——运行时仅官方原子写+轮级世界摘要标记，逐文件哈希与逐字段相等校验移除（独立审计离线重放仍全覆盖）。(4)屏障语义——official-finite-4：未办理主体不阻塞其余主体结算。106项离线检查通过（含未办理结算、立案-兜底记忆、通道退役回归）。


**attempt-0069（15:47启动，official-finite-4架构对齐版）：35轮后用户停止；架构对齐的完整验证记录。** 1004/1006请求完整结算（2笔终止时失败如实记录），约8.57M token（估算¥18.9）。提交35个完整轮次、解决8/12、工单关闭8/12、业务性拒绝2笔（均带明确原因且未重复）、**未办理轮0、turn失败0、告警0、environment_routing全程0**；单请求体积从26KB降至~8KB。历史九类缺陷（路由误译/空回复/轮询/批量上限/前置死循环/评审不可达/视图矛盾/重复读取/死刑重启）在本运行全部未复发；评审-改稿循环、评审送达、未办理结算语义均按设计工作。P:1工程链的最终观察：部门2连续四轮以"方案前提被诊断证据反驳"为由给出revise（世界真相：三设施各有独立根因，共享主管不存在——评审意见正确）；主体4改稿三轮后在rev3仅向部门2发起评审、连续15轮以"评审任务pending"为由wait——与其完全正确的可见状态（received_reviews={'2':'revise'}）直接矛盾，正确出口（request_review(3)/cancel_project）每轮在候选中可用而未取。定性：九类接口缺陷消除后，环境已无法更诚实；残余阻塞为模型层现象——错误信念固着与最后四个跨部门任务的协调低效。此运行构成"接口完备下多主体系统协调极限"的基准观察。证据：`runs/architecture-alignment-20260914-v12-real-000`。
