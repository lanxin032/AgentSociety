# 按 AgentSociety 官方执行链重构

更新日期：2026-10-31。**已按此设计实施，限离线验收。**本说明替代上一版以通用运行协调器为中心的提案。实际执行方式见 [ARCHITECTURE.md](../../ARCHITECTURE.md)。本轮修改运行代码和必要回归，不调用真实 API，不启动 Ray 或云端仿真，不升级依赖，不覆盖历史证据。

## 设计决定与依据

采用 **官方 PersonAgent 的 agentic loop + 官方 ReActRouter 的环境工具调用 + EnvBase 政策环境**。岗位指导通过官方 Agent Skills 提供；`PolicyOfficer` 收窄为必要的权限、取证和版本兼容适配。项目继续维护政策世界、合法信息、结算、预算与研究验收。

官方已有“观察 → 模型决策 → 工具执行 → 反馈 → 继续决策 → finish／迭代上限 → 记忆”。`AgentSociety.step()` 在外层调度全部主体，等待返回后调用环境 step、推进时间并保存。当前 driver 逐轮调用 `society.run(num_steps=1)` 是有限任务的实验推进循环，并非另写主体 agentic loop。[2.8.7 源码核查](official-agentic-loop-20261031.md)、[官方架构说明](https://agentsociety2.readthedocs.io/en/latest/architecture.html)。

当前安装并冻结的是 **2.8.7**，在线 latest 文档已为 **2.9.3**。具体调用以已安装源码为准，不假定新版 Thread、压缩或 `AGENT_MEMORY.md` 已存在。Python、Ray、模型、MCP 和依赖冻结保持现状。

## 职责分配

| 职责 | 复用的官方实现 | 项目保留的内容 |
| --- | --- | --- |
| 生命周期与调度 | AgentSociety、Ray Tasks、ServiceProxy | 现有入口、授权和资源清理；不增加通用协调器 |
| 主体行为 | PersonAgent.step、AgentBase.run_react_loop | 极薄 PolicyOfficer；不另写循环、parser 或格式重试 |
| 岗位指导 | profile + 默认激活的静态 Agent Skill | 一份共同办理指南，由 profile 区分岗位；不编排固定行动序列 |
| 环境调用 | ask_env → EnvRouterProxy → ReActRouter.ask | 可信 caller、计量与真实回执；工具选择执行 super().ask |
| 政策世界 | PolicyEnv(EnvBase)、@tool | 规则、权限、查询、材料阅读、提交与整轮结算 |
| 记忆和个人文件 | Memory、WorkspaceFS、TODO | 路径限制；主观记忆不能替代权威业务状态 |
| 消息运输 | SimpleSocialSpace | 领域信封、收件后授予知识；不开放绕过政策流程的任意全员通信 |
| 保存与恢复 | 官方工作区生命周期 | 同轮一致性、有效 commit、失败现场和恢复谱系 |
| 研究验收 | 沿用现有 budget/client/audit/verify | 原账本、全用途请求证据、技术失败锁和独立重放 |

[流程图与说明](../../figures/proposed-agent-simulation.md) · [可编辑图源](../../figures/proposed-agent-simulation.mmd) · [PNG](../../figures/proposed-agent-simulation.png)。

## 为什么选择 ReActRouter

**采用官方支持的 ReActRouter，不采用默认 CodeGenRouter。**2.8.7 的默认 actor 硬编码创建 CodeGenRouter，不能声称改一个公共 router_type 配置即可切换。复用现有 actor 组装位置，继续实现官方 EnvRouterProxy 协议；这仍是项目适配，并非零自定义的官方 CLI 默认路径。[官方路由清单](https://agentsociety2.readthedocs.io/en/latest/architecture.html#environment-routing)、[2.8.7 默认 actor](https://github.com/tsinghua-fib-lab/AgentSociety/blob/agentsociety2-v2.8.7/packages/agentsociety2/agentsociety2/env/env_router_actor.py)。

| 方案 | 本次判断 |
| --- | --- |
| 默认 CodeGenRouter | 生成代码可接触真实环境模块，当前 PolicyEnv.owner/world 通向全局状态。通用 AST 检查不等于岗位权限，不能原样接入；另建代码执行隔离会扩大设计。 |
| 官方 ReActRouter | 主方案。通过注册工具调用环境，已有 readonly 强制；可信身份和输入、岗位权限由项目工具边界保证。保留官方自然语言到工具的转换，不执行生成代码。 |
| RouterBase 下确定性分发 | 固定四种操作最省模型请求，但属于项目分发。本次不作为主线，不再继承 ReActRouter 却禁用它的模型循环。 |

ReActRouter 增加**环境侧的第二层模型循环**；主体具有 agentic 行为并不依赖它。本次选择是为了优先使用官方工具调用方式，处理自然语言环境请求，不据此声称更智能、更快或更省 token。主体决定办理意图，环境路由落实请求；两者都不能获得隐藏世界信息。[2.8.7 ReActRouter](https://github.com/tsinghua-fib-lab/AgentSociety/blob/agentsociety2-v2.8.7/packages/agentsociety2/agentsociety2/env/router_react.py)。

新运行不再由 dispatch_plan 决定工具调用。历史审计若依赖它，保留旧版解释路径，不能跟随新版路由改变。ReActRouter 构造器未暴露父类的 llm_clients_spec 参数；使用公开 acompletion 接缝复用已有计量客户端，覆盖 routing 与最终 summary，不写私有 dispatcher 字段，不绕过原 loopback 代理和账本。

原生 set_status 和最终摘要来自模型，**不能证明已提交**。ask 返回时附上工具实际产生的回执；只有 PolicyEnv.submit 已登记的 submission ID 表示排队成功。查询成功但没有提交必须如实表示，不能凭摘要里的 success 算立案。审计核对真实调用参数、工具结果和事件。

## 主体与整轮的具体流程

1. **创建与恢复主体。**配置 agent_specs、ServiceProxy 与角色 Skill，通过 AgentSociety.init 创建工作区；每个 Ray Task 由官方 from_workspace 重建主体。恢复时只做一次计量绑定和必要兼容。
2. **官方自主决策。**PersonAgent.step 获取合法观察后进入 run_react_loop。模型可查询、阅读、维护个人记忆、提交或结束。Skill 说明岗位职责和操作约束，不规定第几轮必须选什么。
3. **工具落实请求。**ask_env 经官方 ReActRouter 选择 observe、read_work、read_materials、submit。ask 外围绑定可信 caller、round、readonly 和证据关联，并在结束后清理上下文；这些字段不由路由模型任填。工具入口验证未知输入和岗位权限。
4. **提交只排队。**submit 立即检查合法候选、材料与“每主体每轮至多一次”，然后登记待结算动作。重复调用不得产生第二次副作用；查询不推进世界时间。
5. **官方收尾。**finish 或迭代耗尽后使用官方记忆和工作区保存。没有提交记未办理；已提交但没有正常 finish，保留排队行动和官方 fallback memory。技术失败另行暂停。
6. **整轮结算。**全部主体返回且结果验收通过后，PolicyEnv.step 消费行动、记录未办理、执行领域转移，并经 SimpleSocialSpace 投递到期消息。实际收件后才授予知识，其他主体下一轮才能使用；普通与零摩擦消息都保留整轮边界。
7. **保存、验收、继续。**复用官方保存，核对世界、邮箱、主体和 society 同轮一致性，只发布一个有效 commit。有限任务未完成则再调用 society.step／run(num_steps=1)，完成则独立审计并退出。

主体 ReAct 迭代、环境路由迭代、HTTP 请求、业务动作和业务整轮分别计数。一次迭代可能含多个工具或格式重试，不能当作一次请求或一次业务推进。

complete/abandon 握手已由官方任务结果验收替代，保留“已提交但后续记忆/保存失败”的保护。2.8.7 没有公开 pause/resume：干净暂停是在有效整轮后停止发起下一步；恢复先重建环境和共享服务，再 from_workspace → init → step/run → close。close 不再次保存，也不负责 ray.shutdown。详见[生命周期核查](official-agentic-loop-20261031.md#公共生命周期创建运行保存停止与恢复)。

## 必须保留的适配

| 已核实的缺口或约束 | 处理 |
| --- | --- |
| runner 把主体异常变成 ok:false，society 默认仍推进环境 | 验收每个预期主体的返回结果；暂留固定 2.8.7 的 _await_ref 私有兼容 hook，不复制官方 step |
| 初始 observe、工具和记忆整理的部分异常只成日志/反馈 | 保留技术失败锁，在下一次请求及结算前检查；业务拒绝仍让模型自纠 |
| 环境保存可能只告警，恢复可能部分成功 | 核对全部必需状态与轮次，不凭 await 返回或一个 True 发布 commit |
| 恢复清空 world description；空 memories 提示与 schema 冲突 | 保留针对性修正，角色指导与恢复验收等价后再删重复处理 |
| 动态 skill 激活集保存/读取字段不一致 | 使用 default_activated_skill_ids，每次恢复重新发现静态角色指南；不依赖未经验证的动态恢复 |
| 模型文件工具及新的路由/summary 请求 | 保留文件权限、原预算和 UUID 证据；全部请求计入 T_system |

以上是本地 2.8.7 源码事实及据此提出的设计约束，证据逐项见[官方契约核查](official-agentic-loop-20261031.md)。不得因“官方已有”删除研究保护；也不把这些适配称为框架原生能力。

## 数据结构与代码归位

当前已有实体 dict。只在政策环境中补必要索引，不建通用存储层。

| 数据 | 结构与约束 |
| --- | --- |
| 工单、任务、工程、材料 | 有类型记录 + dict[id, record]；保持原 ID、规则和候选顺序 |
| 本人对对象的合法材料 | dict[(actor_id, object_id), list[record_id]]；仅实际已收到记录，保留顺序 |
| 收件与任务版本 | dict[(actor_id, record_id), received_round]；送达时保存不可变任务版本，不能引用全局最新状态 |
| 待投递消息 | deque 保存未交付信封，稳定筛选到期项；不假定所有消息按到期时间排序，保留普通/零摩擦的原相对顺序 |
| 本轮提交 | dict[actor_id, command]；至多一项，wait 与未办理分别记录 |

索引可从权威实体和交付证据重建，独立审计不信任缓存。对应键定位预期平均为常数级，再遍历实际结果；没有实测加速倍数。视图复用需同时检查状态与本人材料版本，轮内阅读也可能改变知识上下文。集合迭代不得改变候选顺序和随机种子下的结算。

以下三步已实施，并由对应离线回归验收：

| 顺序 | 影响位置 | 完成判据 |
| --- | --- | --- |
| 1. 官方主线 | agent.py、router.py、driver.py、custom 注册与角色 Skill；profiles/interface/audit 调用方 | 官方循环负责决策和工具选择，真实回执与全部模型用途可追踪，权限与技术失败保护有效 |
| 2. 环境归位 | core.py、work.py、materials.py、messaging.py、router.py、检查点调用方 | 结算落在 EnvBase.step，删被替代的握手；未办理、送达与零摩擦语义保持 |
| 3. 索引和收敛 | 实体/视图、受影响 tests/fixtures、协议版本、源码打包清单和说明 | 视图与事件顺序不漂移，每类状态只有一个权威来源，旧审计仍解释旧证据 |

不增加通用协调器、事件总线、repository 或可切换多路由配置。budget、execution、controller、checkpoints 只合并与官方重复的职责。custom/agents 和 custom/envs 继续是发现入口，不复制业务实现。删除自定义 finish 门槛、节奏提示或行为阶段前，检查对应调用方与证据；提示变化不宣称模型行为完全等价。

## 验收与未验证项

迁移前的 **125 项离线测试**作为回归起点，[旧证据在此](../../runs/offline-followup-20261031/validation.json)。本轮新增23项主体、路由、索引与审计回归，完整离线套件148项通过，外网连接和Ray启动尝试均为0。当前结果见[本轮验收](../../runs/native-refactor-20261031/validation.json)。

已补以下关键离线回归，使用真实官方轻量类与可记录的模型替身，禁止外网和 Ray 启动：

- 官方 PersonAgent 完成 observe → 读取 → submit → finish → memory；另测无提交耗尽及提交后耗尽。不用直接调用领域方法冒充框架链路。
- 真实 ReActRouter 调用四种工具；覆盖 attempt-0056 的缺 analysis、自纠、只读成功却未提交和摘要假成功，检查真实回执。
- 身份伪造、越权材料/路径、readonly 写入及重复提交被拒绝，合法分页与材料读取仍可完成。
- observe、路由/summary、记忆、主体或环境保存失败，留下证据并阻止有效结算，不生成替代业务行动。
- 直接运行官方工作区初始化、保存、重新构建和恢复；缺必需状态、轮次错位、角色指导丢失必须可见。组件检查不宣称真实 Ray 恢复通过。
- 已知答案核对索引前后合法视图、材料版本、候选/消息顺序、零摩擦和独立重放；最后运行受影响检查及完整离线套件。

本轮已核对官方文档、已安装源码，并独立复核路由选择；59 个本地文档链接/源码行号检查通过，契约说明中 2 段调用骨架通过 AST 语法解析。流程图经 Mermaid CLI 12.0.0 渲染、图源一致性检查及 PNG 目视核对通过。以上为设计核查；本轮另已执行官方轻量调用链的离线验证，未执行Ray调度或真实模型。

新路由与 Skill 会改变模型输入、费用与系统 token，已冻结新运行/提示/接口版本，旧检查点不接入新版。后续真实比较必须在相同新架构下重新建立 000，路由、摘要、记忆及 A/C 服务全部计入 T_system。真实模型能否完成任务、额外费用与延迟仍待授权验证，不能用离线替身证明。
