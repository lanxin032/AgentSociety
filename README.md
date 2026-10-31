# AgentSociety 政策组合研究

当前唯一执行架构为`policy_sim`，复用官方AgentSociety2 **2.8.7**、PersonAgent/ReAct、Agent Skills、TODO、Memory、SimpleSocialSpace、工作区与Ray；业务请求实际执行官方`ReActRouter.ask()`，岗位指南为默认激活的静态Skill，领域结算归`PolicyEnv.step()`。四主体、种子3001、12个初始问题、合法信息、候选行动和ABC政策机制保持；消息交付统一在整轮边界。有限任务无固定轮数终点；费用只记录，未提交轮次记为未办理，技术服务失败暂停。

- [当前研究与验收状态](research/v3_1/README.md)
- [HTML：当前000与token诊断](research/v3_1/token-diagnosis.html#current-run)
- [架构和官方适配依据](ARCHITECTURE.md)
- [按官方 agentic loop 重构的设计与流程图](research/v3_1/native-refactor-design.md)
- [领域术语与研究边界](CONTEXT.md)

## 当前命令

本机使用Conda `agentsociety`（Python3.12.14）；`environment.yml`引用[requirements.lock](requirements.lock)，精确锁定已验收Mac arm64环境的125个Python包，本轮没有升级或重装。运行前核对包版本，实际Python、平台和包版本写入冻结配置及driver报告，恢复和审计核对环境一致性。其他平台尚未重建验证。当前模型`deepseek-flash`、temperature0.2、max_tokens16384、thinking关闭、上游600秒/客户端660秒。

当前研究协议由[policy_sim/protocol.py](policy_sim/protocol.py)生成：固定有限任务，以全任务完成为终点、`T_system`为指标；先验收真实000，再开放其余七组。[旧60轮协议](research/v3_1/design_protocol.json)与[旧八组合模板](research/v3_1/design-8.json)已标为历史不可执行文件，只用于解释旧证据。

```sh
conda activate agentsociety
python -B -m unittest discover -s tests -v
python -m policy_sim prepare --output runs/<new-preflight>
python -m policy_sim run --manifest runs/<new-preflight>/manifest.json --authorization runs/<new-preflight>/authorization.json --output runs/<new-run>
python -m policy_sim resume --manifest runs/<new-preflight>/manifest.json --authorization runs/<new-preflight>/authorization.json --output runs/<existing-run>
python -m policy_sim audit runs/<new-run>/<attempt>
```

`prepare`只生成冻结方案和未批准授权草案，不调用API。`run`/`resume`要求明确授权并核对原账本、源码和模型配置；resume是用户明确接续，创建新attempt，保留旧失败证据与费用，不自动重试。实际attempt路径见运行目录的`batch_status.json`。

生产执行使用现有`.env.deepseek`秘密配置和`runs/api-local-budget.json`，统一通过loopback代理。不要在命令行或报告中粘贴密钥。环境路由的coder和最终summary全部经原计量客户端，统一计入`environment_routing`和`T_system`；官方10次主体ReAct迭代不等于10次API调用；缺提交记未办理；已提交但缺finish保留立案、使用官方兜底记忆，不替模型提交wait；主体可直接finish而不提交，按未办理记录。仅真实000完整完成且独立审计通过后，才开放另外七组；离线轨迹不能替代真实模型行为验证。

监控入口为`python tools/monitor_000.py --preflight runs/<new-preflight> --batch runs/<new-run>`，记录token、完成进度和当前异常。重复读取只作为线索，已完成轮次的历史重复不触发停机。

## 源码、同步和历史证据

当前包、注册薄层、测试和选定研究文档纳入源码；凭据、账本、授权、原始runs和下载证据不纳入Git。新克隆不是运行证据和秘密配置的备份，也不构成收费授权。

```sh
python tools/build_source_bundle.py --output runs/source-review.zip
```

此命令生成可核对的源码/同步候选包、导入闭包与逐文件哈希，不执行上传。云端覆盖前仍需比较现状哈希。连接工具`tools/coder.ps1`、`tools/open-cloud.ps1`保留；云端历史地址为`/home/coder/policy-mix`，框架位于`/app/packages/agentsociety2`。本次实现和验证在本机进行，不代表已同步或实测云端。

旧MVE/V3/runtime执行实现已由当前包替代，原实验和诊断记录继续保留。[重构前源码指纹](runs/official-refactor-20260913/before-source-manifest.json)、[退役与替代覆盖](runs/official-refactor-20260913/migration.json)、[历史根说明与云端事实](runs/official-refactor-20260913/before-source/README.md)。历史指令仅解释当时版本，不作为当前入口。

研究历史：[MVE](research/mve_20260909/README.md)、[政策组合V3](research/v3_20260909/README.md)、[当前研究及历史运行记录](research/v3_1/README.md)。模拟结果只说明合成条件下的行为，不直接证明现实政策因果效果。
