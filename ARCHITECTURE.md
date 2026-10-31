# 当前执行架构：官方主体循环与环境路由

唯一执行包为 `policy_sim`。AgentSociety2 **2.8.7**、Ray **2.55.1** 和现有模型/依赖保持冻结。当前为 `official-finite-5` / `native-tools-profile-5`，运行时 `official-policy-6`，接口 `v3.3-materials-13`，提示 `official-native-17`。旧版检查点不接入新版。研究目标见 [CONTEXT.md](CONTEXT.md)，重构依据见[官方调用契约](research/v3_1/official-agentic-loop-20261031.md)，验证状态见[研究说明](research/v3_1/README.md#native-refactor)。

## 执行与状态所有权

1. driver 配置 `agent_specs`、共享 `ServiceProxy` 与默认激活的岗位 Skill，调用官方 `AgentSociety.init()`。每个 Ray Task 通过 `from_workspace → step → to_workspace` 重建、执行并保存主体。
2. `PolicyOfficer` 继承 `PersonAgent`，调用官方 `PersonAgent.step()` 与 `AgentBase.run_react_loop()`。岗位指南位于 `custom/skills/policy-role/SKILL.md`，TODO、记忆和个人文件使用官方工具。没有自写 ReAct 循环、固定行动序列或 choose/finish 行为阶段。
3. 初始 `<observe>` 是已知生命周期入口，直接调用注册的只读观察工具，提供合法工作概览。后续业务 `ask_env` 经 `PolicyRouter` 的可信上下文包装，实际执行官方 `ReActRouter.ask()`，再调用 `PolicyEnv` 的 `@tool`。一个 ask 可以包含多次工具调用和自纠。
4. 四主体的官方任务成功返回后，driver 验收其结果，并向环境确认已保存的主体结果。`PolicyEnv.step()` 才消费排队行动、记录未办理、推进领域并投递消息。
5. 官方 society 保存一次环境工作区；项目随后检查保存状态，核对同轮世界、邮箱、主体与 society，并发布不可变 commit。未完成则再调用 `society.step/run(num_steps=1)`。

完整[流程图](figures/proposed-agent-simulation.md)与[重构设计](research/v3_1/native-refactor-design.md)均指向上述调用方式。外层逐轮推进服务于有限任务终点，不是另一套主体 agentic loop。

| 所有者 | 职责 |
|---|---|
| `PolicyEnv` 内的 `PolicyWorld` | 单一权威领域状态；政策、合法观察、候选、待结算行动、物理效果和完成条件，不依赖框架或文件系统 |
| `PolicyRouter` | 包装可信 caller、轮次、readonly、请求关联和真实回执；官方 ReActRouter 负责环境工具选择，项目不手动翻译生产请求 |
| 官方 PersonAgent / Agent Skills / Memory / WorkspaceFS | 决策与反馈循环、角色指导、默认10轮ReAct、原生格式重试、最近8条工具观察、TODO、finish及fallback记忆 |
| `PolicyMailbox` 内的官方 `SimpleSocialSpace` | 唯一消息运输；业务信封与历史保留，正式 receive 成功后才授予收件知识 |
| 现有 controller / checkpoints | 原预算与资源归属、有效整轮保存、失败排空、显式恢复，不新增通用协调器 |
| 独立审计 | 用原始响应重放官方路由，独立重算工具效果、材料可见性、完成和全用途用量，不信任缓存或模型摘要 |

## 工具、角色与权限

业务工具保持 `observe`、`read_work`、`read_materials`、`submit`。路由只看到可信主体、轮次和模型已提供的 variables；其他模型 ctx 字段不进入路由提示。真实身份由 `env_ask_env_ctx_overlay` 和 ContextVar 固定，不能由工具参数覆盖。工具入口校验 Schema、readonly 与岗位权限。

`submit` 每主体每轮至多产生一次排队副作用。排队后仍可合法查询、维护记忆或 TODO，再由官方循环结束。`finish` 不再要求先提交；无提交记未办理，已提交但耗尽保留立案与官方 fallback memory，不伪造 wait。正常 finish 的主观记忆与真实业务回执分别取证。

原生 router 的 `set_status` 和最终摘要不证明立案。主体只收到工具实际产生的回执；只有实际 `submission_id` 表示排队成功。查询可以成功而没有提交；没有工具执行时明确返回失败。`native_routes.jsonl` 绑定 ask UUID 和 `router_call_index`，`native_router_decisions.jsonl` 保存实际 coder/summary 调用或引用原请求 ID。

岗位 Skill 只含文字，默认激活 `custom@policy-role`，由 profile 区分岗位；不包含脚本、hooks 或隐藏世界状态。当前只允许该指南可见，禁止技能脚本执行，个人文件操作限 `notes/`；记忆和 TODO 使用各自官方工具。必要的公开指南读取不开放账本、配置、其他主体文件或任意材料。

本项目采用官方支持的 ReActRouter，而非默认 CodeGenRouter。2.8.7 默认 actor 硬编码后者，因此保留 EnvRouterProxy 协议下的少量 actor 组装适配。生成代码可接触真实环境对象，通用 AST 守卫不等于岗位信息权限；本轮没有另建代码执行隔离。

## 有界上下文与可重建索引

`WorkContext` 保存本轮合法观察和实际读到的材料。主体 JSON 仅增加岗位、轮次、候选数和真实排队回执，不重复装入完整工作台。概览不超过 **12,000 UTF-8字节**，工作页不超过 **16,000字节**；过大的工程任务与收到记录由 `projects/<id>/tasks`、`projects/<id>/received_records` 有界分页提供。材料用合法 source_id 查询，A/C建议继续可查。

读取存根仅在对应 ask 仍处于官方最近8条工具观察时复用；淘汰后再次返回正文。当前调用不再追加自定义轮内节奏提示。查询不推进时间，材料正文是数据。发送前 **240,000字节**预检及原代理 **262,144字节**上限保留。

实体仍按 ID 使用 dict；另维护主体/对象的已收记录与任务、首次送达轮次，以及待投递 deque。索引从权威记录重建，不进入 export_state，不另存竞争的真相。保持材料版本、候选和普通/零摩擦消息的原顺序；未测具体加速倍数。

普通和零摩擦消息都在整轮边界通过官方邮箱交付。作者创建时可见，其他合法成员正式收件后才可见；非作者材料使用实际接收轮。有限任务仍为四主体、种子3001、12个问题、baseline环境，政策机制与完成判定保持。

## 剩余适配与必要性（提交前复查）

| 适配 | 必要性 |
|---|---|
| `PolicyOfficer` 的恢复、工具边界和薄取证钩子 | 固定身份、限制个人文件/可见Skill、记录原始调用，拒绝截断及歧义参数。实际 parser、重试、TODO、工具和循环仍调用官方实现。2.8.7 恢复清空 world description，因此保留回填；已删除重复的 `_load_world_description` 覆盖，改用官方公开 getter。 |
| `CheckedMemoryRuntime` | 官方记忆整理会吞异常；只暴露失败状态，记忆存储、整理和 fallback 继续走官方实现。 |
| `PolicyRouter` + 自定义 actor 组装 | 官方默认 actor 硬编码 CodeGenRouter。这里保留 EnvRouterProxy 协议，实际调用官方 ReActRouter；包装可信上下文、Schema、真实回执与计量。技术工具/证据写入失败必须锁定错误，阻止官方把它当作普通工具失败继续请求。 |
| `AuditedSociety._await_ref/to_workspace` | 官方默认忽略主体 ok:false、环境保存错误只告警；验收已保存主体和实际保存轮次。主体调度、结算后的保存仅执行一遍官方流程，没有复制 step。 |
| `official_adapter.PROMPT_CORRECTIONS` | 三处固定2.8.7文本修正：空memories、业务wait及本任务禁技能脚本的说明；严格匹配版本，不另造prompt/循环。 |
| `ModelClient/BudgetProxy/TaskDrain/checkpoints` | 原预算、UUID、失败响应排空和跨工作区整轮提交属于项目研究约束，官方不提供这些项目合同。不得为减少适配删除它们。 |
| `PolicyEnv/PolicyWorld/WorkContext/PolicyMailbox` 与独立审计 | 政策规则、合法材料、整轮知识交付和证据验收属于研究业务。邮箱运输复用 SimpleSocialSpace；审计重放官方实现并独立核对规则，不是第二套生产Agent引擎。 |

生产主体与环境分别直接使用官方 PersonAgent 与 ReActRouter 循环。`dispatch_plan`仅供显式离线模型替身及旧格式解释，`paced`仅供旧格式重放；它们不进入当前生产分发。旧运行的完整审计仍需匹配历史冻结源码。独立审计保留自己的工具合同检查，避免执行端和审计共享同一个错误。

仍有固定版本的私有钩子：主体的解析前校验/调用取证、技能可见集、记忆失败观测和society返回验收。各自对应上述具体缺口；不宣称它们是稳定公开接口。升级框架时应重验或删除这些兼容。本轮不升级。

## 计量、恢复与验证边界

系统 token 包括 `agent_decision + environment_routing + memory + policy_A + policy_C`；现行 coder 与最终 summary 都计为 environment_routing，全部经过既有 ModelClient、loopback代理和原账本。一次主体迭代、路由迭代、HTTP请求、业务行动和业务整轮分别记录。原请求/响应只存一份，其他证据引用 UUID；失败费用保留，缺 usage 保持未知。

一个主体技术失败后，停止标记阻止新请求，已发请求在原660秒截止期内保存回执；原675秒任务排空与控制器退出余量保持。失败现场不删除，不重试收费执行。显式恢复创建新attempt，复用原不可变请求证据与完整谱系，不覆盖旧运行。

`requirements.lock` 与 environment.yml、角色 Skill 一同纳入源码冻结与同步包；运行前核对精确依赖、Python及平台，恢复、审计与比较身份绑定相同环境。本轮未安装或升级包。

当前检查入口仍为 `python -B -m unittest discover -s tests -v`，离线验收必须在禁止外网和 Ray 初始化的环境进行，loopback上游使用替身。验证覆盖原生主体、路由多工具/自纠、真实回执、角色/TODO恢复、故障暂停、信息边界、消息、索引及独立篡改审计。结果见[当前验收](research/v3_1/README.md#native-refactor)。

本轮没有启动真实API、Ray或云端仿真。新提示与路由改变了模型输入和token构成，不能接续旧检查点或与旧000混比；真实协调行为、完成能力、路由额外开销及分布式恢复仍未验证。attempt-0055/0056等历史失败证据与当时判断保留在[研究历史](research/v3_1/README.md)。
