# 供水治理最小可执行实验

**价格更正**：当前平台截图中`deepseek-v4-flash`输入、输出均免费；旧名义费用及15元批次收费要求已撤回，见[更正说明](pricing_correction.md)。原调用记录和控制上限未变，下一轮尚未启动。

本次交付见[实施、接入与费用报告](implementation_report.md)；24次真实模型批次尚未启动，具体清单和待批准额度见[批次计划](batch_run_plan.json)。

本版是有政策和案例依据的合成机制预实验。参数权威入口是 `frozen_spec.json` 和 `policy_mve/spec.py`；研究边界见同目录 `protocol.md`。所有工时、工程资源、问题生成概率和强度端点都是未校准的合成设定。

当前业务版本为1.2。[任务图、权限表和资源口径](mechanism_reference.md)列出合法操作；本版观察增加本人上一轮的结算结果、拒绝原因和资源扣款，并公开个案/专项操作顺序。该补丁不改变客观转移和指标。

1.1版调用设置固定为deepseek-v4-flash、temperature=0.2、max_tokens=4096、thinking.type=disabled及JSON对象输出。1.0接入在4096输出上限下两次收到空正文而技术终止，因此单独切换调用设置并重新接入；这不是原运行的无缝延续。思考开关依据[DeepSeek官方文档](https://api-docs.deepseek.com/guides/thinking_mode/)，平台是否支持以真实调用证据为准。

## 运行入口

在本地项目根目录，用现有Python进行纯业务规则检查：

```powershell
python -B tools/run_mve_offline.py --output runs/NEW-OFFLINE-DIR --smoke
python -B tools/run_mve_offline.py --output runs/NEW-MATRIX-DIR
python -B tools/verify_mve.py runs/NEW-MATRIX-DIR/seed-101_policy-000
```

输出目录必须是新目录。前一命令检验8个组合在18轮内存在可执行源头治理路径；第二个命令生成24次脚本矩阵，不调用真实模型。

通过现有Coder连接，在官方云端框架验证脚本控制器：

```powershell
& ./tools/coder.ps1 exec /usr/local/bin/python -B /home/coder/policy-mix/tools/run_mve.py --mode scripted --steps 18
```

真实模型入口（收费；只能在已批准的接入范围使用）：

```powershell
& ./tools/coder.ps1 exec /usr/local/bin/python -B /home/coder/policy-mix/tools/run_mve.py --mode llm --steps 18
```

该入口读取云端既有秘密配置，通过唯一loopback预算代理访问模型。旧16条账本原样保留，只增加本次明确批准的200次请求和5元估算额度；重复启动不会补充额度。初始化、派单建议、决策、格式修复均计费计次。24次真实模型批次仍需另行报价与批准，不能把上述接入命令当作批次授权。

`--resume /home/coder/policy-mix/runs/EXACT-RUN` 只恢复同一运行的干净完整检查点，并要求mode/policy/seed/horizon和源代码版本一致；`--steps 0 --resume ...`仅核查恢复，不推进业务步骤。部分失败或源文件变化时拒绝恢复，不能悄悄换版本继续。

结果回收使用 `tools/retrieve_mve.ps1 -RunName EXACT-MVE-RUN-NAME`，逐文件校验哈希且拒绝覆盖不同的本地证据。密钥不在回收清单中；云端预算副本进入运行对应的证据目录，不覆盖本地旧账本。

## 实现边界

- 四个办理主体继承官方AgentBase，由官方AgentSociety/Ray运行；业务环境继承EnvBase，经官方EnvRouterProxy访问。
- 路由使用受约束的EnvLike接口，只接受程序绑定身份后的observe/submit，不生成或执行模型代码。没有修改预装框架或放宽其代码执行安全检查。
- 模型只能看到角色白名单观察，不能读取完整world、隐藏根因、文件系统或owner审计接口。
- A在真实运行中使用独立模型调用给出可见材料上的建议；脚本测试的规则建议明确标为rule_fixture。展示建议、工作人员选择使用及最终匹配结果分别保留。
- B在1.1版提供联合邀请及本人显式确认，全部参与方确认后展示共享任务清单和进度。确认占用一轮行动并扣除已有决策工时；未确认仍可普通办理，没有自动并行或速度加成。1.0版的隐含接受实现与接入证据保存在独立源码快照中。
- C的第一版操作专项记录和里程碑信息的结构化展示，与个案共享资金及施工容量。验收改变后续风险，不自动修复已发生的局部损坏；这是一项明确的合成结构假设。
- 规则阶段的基准与强化可以得到相同解决结果或不同成本。工具有效并非工程验收标准。
- 独立验证器从事件重算指标，并重放已记录动作核对全状态哈希；这不意味着重新调用模型也会产生完全相同的决策。

## 分析与后续批次

每个完整仿真为分析单位。分析程序只对包含8个有效组合的完整种子区组计算配对差异及条件交互，列出所有缺失或失败区组。3次重复只报告原值、均值和范围，不作显著性推断。

接入完成后，`tools/quote_mve.py`只根据实际调用量生成后续24次运行报价，不变更预算授权、不启动批次。

`tools/run_mve_contract_probe.py`是独立的定向真实接口用例：要求模型编码指定合法动作，检查B联合确认与C结构化专项链，仍使用同一200次/5元接入账本。它不使用AgentSociety调度、不测试自主采用率，不能加入24次自主实验或效果分析。

1.0版证据使用`runs/mve-source-snapshots/policy-mve-1.0/tools/verify_mve.py`核验；当前验证器不会把旧检查点补成新版参与确认状态。各版本不得中途混合恢复。

1.1版19轮及恢复证据使用`runs/mve-source-snapshots/policy-mve-1.1-final/tools/verify_mve.py`核验。1.1版定向接口用例使用`policy-mve-1.1-before-schema-fix`快照；最终交付同时保留失败运行，不能按成功目录数忽略调试请求。
