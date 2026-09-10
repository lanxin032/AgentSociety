# 代码阅读与修改入口

领域用语见 [CONTEXT.md](CONTEXT.md)。MVE 是保留的基线，V3 是当前研究实现；两者复用执行机制，但各自保留世界状态、决策规则和审计口径。

## 共享执行

| 关注的问题 | 入口 | 职责 |
|---|---|---|
| 一轮何时可以恢复 | `policy_runtime/checkpoints.py` | `commit_round` 核验四主体结果、完成轮次、磁盘状态与文件集合，最后原子写入提交标记；`validate_commit` 在恢复或核验前检查同一约束。 |
| 主体怎样完成一次办理 | `policy_runtime/officer.py` | `OfficerRuntime` 完成观察、脚本或模型选择、提交、结构化回执与历史保存。 |
| 如何接入官方主体 | `policy_runtime/framework.py` | `PolicyOfficerBase` 将官方创建/恢复/保存/步进生命周期接到共享办理流程。 |
| 观察与提交如何到达环境 | `policy_runtime/router.py` | `PolicyRouter` 管理四主体提交屏障、公开建议、观察定稿、环境状态保存与建议缓存恢复。 |

`custom/agents/policy_officer.py` 与 `policy_v3_officer.py` 只选择各自的决策函数；`policy_mve/router.py` 与 `policy_v3/router.py` 只装配对应环境及观察定稿规则。V3 不再通过继承 MVE 主体或 router 来获取共享状态约定。

两个 driver 负责官方框架运行和退出，完整轮次交给 `commit_round`。V3 控制器及证据核验直接依赖共享检查点 module，不再从 driver 导入核验函数。MVE 的离线最小证据格式仍由它自己的核验器处理，不冒充完整框架检查点。

已有的 I/O、模型文本解析和受限客户端仍在 `policy_mve/io.py`、`policy_mve/llm.py` 复用；它们不是可删除的旧实现。决策提示、候选编号和格式修复规则分别留在两个实验的决策 module。

## 工程项目生命周期

`policy_v3/core.py` 保留主体权限、任务指派、资源检查、通信和轮次调度；`policy_v3/project_lifecycle.py` 集中施工完成、技术投运、物理激活、行政验收与终止的状态变化。

生命周期对象只在一次操作期间绑定项目及任务引用，不保存在世界状态中。`export_state`、`from_state` 的字段与事件顺序保持兼容。

- 施工回执同步进入主体认知，然后才产生建成事件。
- 物理激活发生在轮次递增后、消息交付和外生冲击前。
- 主体观察仍从已收到材料构造，不能直接读取物理真实状态。
- `policy_v3/verify.py` 从事件独立核算物理效果与行政手续，不使用执行端生命周期判断作为答案。

## 验证与交付

完整离线检查：`python -B -m unittest discover -s tests -v`。

- `test_checkpoints.py`：提交与恢复的文件级契约，包括篡改、缺失、部分失败和原子替换中断。
- `test_policy_runtime.py`、`test_v3_interface.py`：直接调用共享办理及 router module，覆盖回执、等待、历史与候选编号定稿；不再抽取 AST 方法。
- `test_framework_adapters.py`：安装框架时，在禁网络的独立进程中检查官方类的注册、创建、一步办理、保存与恢复；不启动 Ray。
- `test_v3_lifecycle_compatibility.py`：对照重构前冻结的 16 组行为轨迹和两条恢复路径，比较观察、提交回执、完整状态、事件顺序与指标。`tests/data/project_lifecycle_v3_1.json` 是合成回归夹具，不是研究结果；修改预期时需重新说明行为变化，不能用当前输出直接覆盖。

共享源码纳入 MVE/V3 源码清单；V3 同步清单包含 MVE 共用依赖、共享执行目录和全部 Python 工具。同步仍要求覆盖前哈希匹配，生成同步脚本不等于执行上传。

此次整理保持研究状态格式，但源码哈希会变化。已有冻结实验的源码绑定继续生效，不能用新代码绕过原恢复限制，或重标历史运行。云端同步、Ray 整体运行及真实模型执行仍需各自的实测证据。
