# AgentSociety 2.8.7 官方 agentic loop 与扩展边界

核查日期：2026-10-31。用途：为重构设计提供版本固定的官方能力依据；不替代研究协议，不决定新的实验规模、角色权限或预算。本轮只读源码与官方网页，未执行下列骨架，未启动模型 API、Ray、仿真或云端。

本文是重构实施前的源码核查记录。官方2.8.7源码依据仍适用；下文关于项目自身实现、项目行号及待迁移职责均指当时状态。最新实现和验收见[当前架构](../../ARCHITECTURE.md)与[研究说明](README.md#native-refactor)。

## 结论与版本

**已安装的 2.8.7 已经提供完整的 PersonAgent agentic loop。项目应调用官方生命周期，并把业务规则、信息权限、预算和证据保护放在其边界；无需再造观察、推理、工具反馈、结束和记忆循环。**但“官方 step 返回”尚不能证明每个主体成功、环境保存成功或业务整轮有效，以下失败路径仍需项目保护。

- 已安装包版本为 `agentsociety2==2.8.7`、`ray==2.55.1`，依据两个安装包的元数据，而非网页版本号。[AgentSociety 元数据][metadata]、[Ray 元数据][ray-metadata]。
- 主证据是 `/opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2` 的实际源码。下文源码链接均指该安装目录，行号为一基。
- 官方对应发布标签为 [`agentsociety2-v2.8.7`](https://github.com/tsinghua-fib-lab/AgentSociety/tree/agentsociety2-v2.8.7/packages/agentsociety2/agentsociety2)，可用作仓库溯源入口；本轮未逐文件比较安装包与标签内容。
- 同日访问的[官方文档首页](https://agentsociety2.readthedocs.io/en/latest/)已标 `v2.9.3`。[Using Agents](https://agentsociety2.readthedocs.io/en/latest/agents.html)、[Agent Skills](https://agentsociety2.readthedocs.io/en/latest/agent_skills.html)、[Quick Start](https://agentsociety2.readthedocs.io/en/latest/quickstart.html)只作为官方方向与导航；具体兼容性以以下 2.8.7 分支为准。新版页面提到的 Thread 压缩、`AGENT_MEMORY.md` 等不能据此认定为本地版本能力。

## 五个层次，四种计数边界

| 概念 | 2.8.7 的实际含义 | 不应等同于 |
| --- | --- | --- |
| 外部 `AgentSociety.step(tick)` | 给全部主体分批提交 Ray Tasks；等批次返回；推进环境；增加仿真时间与 society 步数；保存 society/env。[581–635][society-step] | 一次模型调用、一次业务动作 |
| 单主体 `PersonAgent.step(tick, t)` | 单主体初始化、技能 hooks、初始观察、一次完整 ReAct loop、事件记忆与记忆整理。[392–480][person-step] | ReAct 的一次迭代 |
| 内部 ReAct 迭代 | 一次决策请求，可含一次参数修复重试及多个工具调用；收到工具反馈后进入下一迭代。[1614–1717][react-loop]、[1780–1833][react-retry] | 一次业务整轮；固定一次计费请求 |
| 业务动作 | 由业务工具契约定义的查询、提交、协调等操作；官方 loop 只负责执行并反馈结果。[1694–1714][react-loop] | 自动推进时钟或完成整轮 |
| 业务整轮 | 项目定义的主体完成条件、结算、证据与一致性边界。只有业务契约验证通过，才可将其映射到某次 society step。当前项目已有主体 barrier 与结算检查。[PolicyOfficer.step 208–238][policy-step]、[PolicyRouter.step 282–308][policy-router-step] | 默认 10 次 ReAct 迭代或有字符串返回 |

因此，`num_steps`、主体 `step_count`、`max_react_turns`、请求数和业务动作数应分别记录。实际调用中 `AgentSociety` 把尚未增加的 `self._t` 传给主体与环境，随后才增加 `tick`；不要仅凭文档中“本步结束时间”的注释解释传入的 `t`。[600–635][society-step]

## 公共生命周期：创建、运行、保存、停止与恢复

1. **创建**：`AgentSociety(agent_specs=..., agent_class_name="PersonAgent", env_router=..., service_proxy=..., start_t=..., run_dir=...)` 持有记录，不在主进程常驻主体对象。`agent_specs` 中的 id 与 `profile.id` 须由项目保证一致。[130–179][society-create]、[AgentBase.create 234–283][agent-create]
2. **初始化**：`await society.init()` 依次初始化 dispatchers、解析共享服务、建立 replay、用 `create_agents_batch` 创建主体 workspaces、调用环境 `init`、写一次 `SOCIETY.json`。[360–390][society-init]。不可把 `PersonAgent(...)` 当带 profile 参数的构造器；`create` 只写文件，`from_workspace` 才返回实例。[234–303][agent-create]
3. **运行**：`await society.step(tick)` 或 `await society.run(num_steps, tick)`。后者只循环调用前者，遇私有终止标记才退出。[637–646][society-run]
4. **逐步重建与保存**：每个 Ray Task 通过注册表解析类，`from_workspace → agent.step → agent.to_workspace → agent.close`，并返回轻量结果；批内主体实际用 `asyncio.gather` 并发。不要依据 society 类头部“批内顺序”的旧注释设计顺序协议。[runner 109–152][runner-core]。官方 society 步骤已在增加计数后 `to_workspace()`；单主体的内存对象不是持久状态。[630–635][society-step]
5. **干净停止**：2.8.7 的 `AgentSociety` 未提供公开 `pause()`／`resume()`。在已经验收完整的 step 边界停止继续调用，然后关闭资源。显式 `to_workspace()` 可保存零步初始化或额外干预后的状态；不应在未完成动作中途调用它并宣称事务性暂停。[418–434][society-save]
6. **恢复**：调用方先重建环境 router、绑定相同模块 workspaces 和共享服务，再 `await AgentSociety.from_workspace(run_dir, env_router=..., service_proxy=...)`；随后仍须 `await society.init()`。`from_workspace` 只读取 society 记录，设置计数与跳过新建标记，不创建 actor、不运行环境恢复。[523–569][society-restore]。官方 CLI 也在 fresh/resume 两分支后统一调用 `init()`。[CLI 542–582][cli-restore]。标准 `RouterBase.init()` 先初始化各模块，再恢复其快照，顺序不可倒置。[362–374][router-init]
7. **关闭**：`close()` 关闭环境、所持 replay 资源与 dispatchers；它不再保存，也不负责 `ray.shutdown()`。[392–413][society-close]。`async with society` 等价于进入时 init、退出时 close。[571–576][society-context]。项目显式创建的 Ray actor/会话由其唯一负责人结束。

以下只展示公共调用骨架，**未经执行，尚不包含生产运行必须的预算、结果与保存验收**。`agent_specs`、`env_router`、`service_proxy`、运行目录、起点、步数及 tick 均应来自已对齐配置；环境构建与其业务工具由另一设计分支说明。

```python
from agentsociety2.society import AgentSociety

society = AgentSociety(
    agent_specs=agent_specs,
    agent_class_name="PersonAgent",
    env_router=env_router,
    service_proxy=service_proxy,
    start_t=start_t,
    run_dir=run_dir,
    env_module_types=env_module_types,
    env_kwargs=env_kwargs,
)
try:
    await society.init()
    await society.run(num_steps=num_steps, tick=tick)
finally:
    await society.close()
```

恢复骨架的构造部分改为下列调用，再执行同一组 `init → run → close`。`num_steps` 表示这次追加运行的步数；直接 API 不会替研究者自动从原始计划减去已完成步数，CLI 则另有计划游标逻辑。[CLI 619–629][cli-remaining]

```python
society = await AgentSociety.from_workspace(
    run_dir,
    env_router=env_router,
    service_proxy=service_proxy,
)
```

新的尝试必须使用不覆盖既有记录的目录。`AgentBase.create()` 实际使用写入模式覆盖 `config.json` 与初始 `AGENT.json`，其“write-once”描述不是防覆盖校验。[246–283][agent-create]

## PersonAgent 已承担的完整循环

**首次使用**：`_ensure_initialized()` 建立 TODO 与 memory store，发现技能，加载环境世界描述，保存主体记录。常规 `step()` 先增加主体计数并设置当前时间，再刷新技能、运行已激活技能的 `pre_step`，向环境发送只读 `<observe>`。[360–461][person-init]

**持续决策**：`run_react_loop()` 每迭代经公共 `build_react_messages(...)` 组装 prompt；其中已有 profile、world、技能正文、最近工具反馈、memory 和 TODO。[PersonAgent 311–338][person-prompt]、[AgentBase 1744–1778][react-messages]。工具执行结果的 `ok/observation/data` 自动进入下一迭代，无须项目重建一个反馈消息循环。[1694–1717][react-loop]

**结束或达到上限**：默认 `max_react_turns=10`，可通过 config 设置为至少 1。参数解析错误在同一迭代内还可能重试一次；故“10 迭代”不是“最多 10 请求”。[349–352][agent-restore]、[1780–1833][react-retry]。step 模式的 `finish` 必须带至少一个 `memories` 项；ask/readonly 模式须带非空 `answer`。[2065–2118][react-finish]。没有合法 finish 而耗尽迭代时，官方用观察合成一条 fallback memory 并返回摘要，不抛“未完成业务”的异常。[1719–1742][react-loop]

**记忆生命周期**：loop 后自动执行 `post_step`，然后 `PersonMemoryRuntime.after_step` 将 finish/fallback memories 写入 `memory/episodes.jsonl`；满足阈值时另发模型请求整理 `MEMORY.md`。没有单独的每步 memory-extraction 请求，但 consolidation 仍有费用。[PersonAgent 463–469][person-step]、[memory runtime 289–365][memory-after]、[443–549][memory-consolidate]。默认启用 memory，prompt 最多约 4000 字符摘要与最近 8 条事件；pending 阈值 10、间隔 8 步、重要度阈值 0.75 均有现成 config。[PersonAgent 103–176][person-config]

2.8.7 的短期反馈是每次 loop 的 observations，prompt 只放最近 8 项，不是新版 Thread 持久化与自动压缩的等价物。[person_prompt 326–365][person-observations]。`PersonAgent.to_workspace()` 写主体动态 JSON；memory 已在 after_step 路径保存。[180–197][person-save]。模型记忆是主体的主观记录，不能替代业务权威回执、真实输入和结果审计。

## 角色指导与公共扩展点

**业务角色指导适合使用 2.8.7 已有的 Agent Skills。**纯角色说明可先只写 `SKILL.md`；无需为了接入角色再写循环或脚本。实际配置入口为 `extra_skill_paths`、`default_activated_skill_ids`、`disabled_skill_ids`。默认发现位置是 `env.run_dir/custom/skills` 与主体 workspace 下 `custom/skills`；额外根目录也可显式配置。环境还可通过 `skill_dirs()` 提供技能目录。[AgentBase 335–391][agent-restore]、[901–1019][skill-discovery]

角色技能如注册为 `custom@policy-role`，可用 `default_activated_skill_ids` 使其在第一步观察前就进入正文与 hooks。先核对实际扫描到的 ID，不能把“目录存在”等同于“技能已激活”。PersonAgent 已把 activated 正文加入 system prompt。[311–338][person-prompt]、[skill_runtime 560–600][skill-content]。领域角色、可见信息和真实操作权限仍应由 profile 与环境工具契约共同表达；技能不能赋予隐藏信息，也不能替环境进行权威结算。

2.8.7 已支持 `pre_step`／`post_step` 生命周期 hooks，只有同时可见且激活的技能会执行；`pre_step` 成功输出进入 prompt，摘要输出最多 1000 字符。hook 失败只告警，不能承担必须中止运行的预算、权限或保存校验。[PersonAgent 411–423][person-step]、[AgentBase 1041–1104][skill-hooks]。如确需脚本，2.8.7 的 `entrypoint(argv, ctx)` 路径已有 `ctx.workspace_root` 属性；不要照新版页面的不同写法假定它是方法，也不要使用共享 `cwd/os.environ` 作为主体身份。[skill_runtime 148–173][skill-context]、[819–889][skill-script]

安装包随附的[AgentBase 开发指南][base-guide]明确了兼容边界：

| 已有公开扩展点 | 本项目适用职责 |
| --- | --- |
| `restore`、`build_agent_json` | 恢复与记录必要业务状态；先调用 `super` |
| `build_react_messages` | 在技能不足时补充结构化领域信息；保留官方上下文与 memory |
| `dispatch_react_tool`、`ask_env`、`env_ask_env_ctx_overlay` | 真实权限、身份、业务工具与证据关联；未命中的工具交给官方实现 |
| `run_lifecycle_hooks`、`discover_skill_sources`、`skill_runtime` | 复用官方技能能力，不复制其装配与循环 |
| `run_react_loop`、`acompletion`、`trace_span`、`persist_agent_json` | 自定义架构确有需要时复用；默认 PersonAgent 已自动调用常规路径 |

`_call_react_llm*`、`_parse_react_responses`、`_execute_react_tool`、`_refresh_visible_skills`、`_bind_services` 等被同一指南列为内部实现，不能当作稳定标准接口。[指南 113–134][base-private]。项目若为 2.8.7 的具体缺口暂留这些覆盖，应记录触发条件与移除条件，固定版本并验收该边界；不能据此另复制一套 ReAct 实现。

## 2.8.7 仍需项目保护的具体缺口

| 已核实分支或静态不一致 | 对重构设计的约束 |
| --- | --- |
| runner 将主体恢复、step 或保存异常转成 `ok:false`；society 只合并 token_stats，不检查 results，就继续环境结算与保存。[runner 119–140][runner-core]、[society 621–635][society-step] | 必须验收每个预期主体的结果与持久状态。仅成功 await `run()` 或出现 step_count 不足以判定成功。 |
| `RouterBase.to_workspaces()` 收集模块异常后只日志；society 的外层保存又只告警。[438–453][router-save]、[418–434][society-save] | 不能只在外层再 await 一遍保存便宣称 fail-closed；需要实际保存证据与一致性门槛。 |
| `RouterBase.from_workspaces()` 对失败模块转 fresh，返回的是“任一模块恢复成功”。[404–436][router-restore] | 恢复验收须覆盖全部必需模块与相同轮次，不能把一个 True 当完整恢复。 |
| 主体文件在各 Task 中先写，环境及 society 稍后写；各文件原子写不等于跨文件事务。[runner 119–140][runner-core]、[society 630–635][society-step] | 只能将完整且一致的 checkpoint 当可恢复边界；保留项目 clean-commit/partial-failure 证据，不能静默续跑半轮。 |
| observe 异常仅 debug 日志；hook 失败仅 warning；memory consolidation 异常仅 warning。[PersonAgent 425–458][person-step]、[hooks 1091–1104][skill-hooks]、[memory 352–365][memory-after] | 研究协议认定为必需的观察、hook 或记忆结果，需要单独状态证据；不能用返回字符串替代。 |
| prompt 仍允许“无重要事件时 memories=[]”，但实际 schema 与 parser 拒绝空列表。[person_prompt 52][person-empty-memory]、[person_tools 125–145][finish-schema]、[AgentBase 2102–2118][react-finish] | 这是版本内的明确矛盾。角色指导可要求记录一条真实观察；若保留 prompt 修正，需定位该矛盾，而非重写官方 loop。 |
| `PersonAgent.restore` 将 world description 清空，而持久化的 initialized_at 会让 `_ensure_initialized` 直接返回。[120–134][person-restore]、[360–379][person-init] | 后续 Ray 重建不能假定 `<world>` 自动保持原内容。当前 PolicyOfficer 已有针对此问题的修复；移除前须保证等价世界/角色信息仍可见。[154–158][policy-restore] |
| `build_agent_json` 保存嵌套 `skills.visible/activated`，`restore` 读取顶层 `visible_skills/activated_skills`。[794–811][agent-json]、[356–384][agent-restore] | 静态源码显示动态激活集不能按原样跨重建恢复；本轮未执行 roundtrip。固定角色指导可走 `default_activated_skill_ids` 的重新应用路径。[1013–1018][skill-discovery] 不能把动态激活持久化当已验证能力。 |

## 当前 PolicyOfficer / driver 可收敛的职责

以下是兼容性建议，不是本轮实施变更，也不改变现有未归档、fallback、角色权限或实验约束。

- **保留官方循环作为唯一循环。**当前 `PolicyOfficer.step()` 已调用 `super().step()`，其外围主要负责业务完成标志、未归档状态、回执和失败证据。这些领域责任不等于重复 ReAct，应评估其适用位置后保留。[208–243][policy-step]
- **角色指导优先放入 profile／默认激活技能。**当前 `build_react_messages`、`_load_world_description`、`_refresh_visible_skills` 有领域 prompt 和禁用技能逻辑；可评估用现成技能 config 取代重复装配，但必须同时解决上述 world description 与激活恢复差异。[133–190][policy-prompt] 不能直接删除现有恢复修复，或把角色技能当强制权限控制。
- **共享模型服务继续经 `ServiceProxy` 注入。**现有 `OfficerDispatcher` 还做请求用途、预算失败和审计关联，不应因官方能发请求而一并删除；只需避免它另建决策循环。当前 driver 已用官方 `LLMClients` 绑定客户端。[OfficerDispatcher 73–96][policy-dispatcher]、[driver 114–122][driver-services]
- **保留结果、预算和证据验收，减少对调度内部的依赖。**`AuditedSociety._await_ref` 弥补的是官方忽略 per-agent 失败的具体缺口，但 `_await_ref` 本身是私有接口。暂留时应明确它是固定 2.8.7 的适配；若以公开业务 barrier、保存验证或上游公开结果 hook 替代，先证明能覆盖“业务已提交但 agent 保存失败”等路径。不能直接删掉保护，也不必复制 `AgentSociety.step()`。[driver 69–103][driver-audit]
- **保存只保留一个明确成功边界。**当前 driver override 在 `super().to_workspace()` 前再保存一次环境；设计时可收敛重复 I/O，但前提是明确 RouterBase 内层日志吞错的覆盖办法。[driver 99–103][driver-audit]。运行后的 `commit_round`、源配置冻结、完整性审计和收费预算与官方 agentic loop 职责不同，应保留其研究必要部分。[driver 151–158][driver-run]

本说明已完成静态源码与官方来源核对；49 个本地引用目标及一基行号有效，2 段 Python 骨架通过 AST 语法解析（未导入或执行仿真包）。未验证真实 LLM 行为、Ray 调度、并发可比性、恢复实效或政策效果；所有涉及未来重构行为的表述均为设计建议。

[metadata]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2-2.8.7.dist-info/METADATA:3
[ray-metadata]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/ray-2.55.1.dist-info/METADATA:3
[society-create]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:130
[society-init]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:360
[society-close]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:392
[society-save]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:418
[society-restore]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:523
[society-context]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:571
[society-step]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:581
[society-run]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/society.py:637
[runner-core]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/runner.py:109
[agent-create]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:234
[agent-restore]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:305
[agent-json]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:774
[skill-discovery]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:901
[skill-hooks]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:1041
[react-loop]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:1574
[react-messages]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:1744
[react-retry]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:1780
[react-finish]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/agent.py:2065
[person-config]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person.py:103
[person-restore]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person.py:120
[person-save]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person.py:180
[person-prompt]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person.py:311
[person-init]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person.py:360
[person-step]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person.py:392
[person-empty-memory]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person_prompt.py:52
[person-observations]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person_prompt.py:326
[finish-schema]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/person_tools.py:110
[memory-after]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/memory_runtime.py:289
[memory-consolidate]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/memory_runtime.py:443
[skill-content]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/skill_runtime.py:560
[skill-context]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/skill_runtime.py:148
[skill-script]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/skill_runtime.py:819
[base-guide]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/README.md:38
[base-private]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/agent/base/README.md:113
[router-init]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/env/router_base.py:362
[router-restore]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/env/router_base.py:404
[router-save]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/env/router_base.py:438
[cli-restore]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/cli.py:542
[cli-remaining]: /opt/homebrew/Caskroom/miniconda/base/envs/agentsociety/lib/python3.12/site-packages/agentsociety2/society/cli.py:619
[policy-step]: /Users/zy/Desktop/AgentSoiety/policy_sim/agent.py:208
[policy-restore]: /Users/zy/Desktop/AgentSoiety/policy_sim/agent.py:154
[policy-prompt]: /Users/zy/Desktop/AgentSoiety/policy_sim/agent.py:133
[policy-dispatcher]: /Users/zy/Desktop/AgentSoiety/policy_sim/agent.py:73
[policy-router-step]: /Users/zy/Desktop/AgentSoiety/policy_sim/router.py:282
[driver-services]: /Users/zy/Desktop/AgentSoiety/policy_sim/driver.py:114
[driver-audit]: /Users/zy/Desktop/AgentSoiety/policy_sim/driver.py:69
[driver-run]: /Users/zy/Desktop/AgentSoiety/policy_sim/driver.py:151
