# 政策组合实验 V3

本目录实施用户确认的完整V3计划：RQ1组合、RQ2a强度、RQ2b两类顺序。C保持完整的高频共性诉求专项源头治理。旧版最小实验和真实接入记录保留在`research/mve_20260909`及原`runs/`目录，不能合并为V3结果。

最近执行状态（2026-09-09）：自主诊断2次完整核验通过，第3次在18轮后因两次候选外模型动作而技术失败，后3次未启动；累计280次请求，云端已停止。见[诊断报告](diagnostic_report.md)、[原版本恢复方案](diagnostic_recovery_plan.md)和[待批准的额度清单](diagnostic_recovery_quote.json)。工程验收报告中的零API状态属于较早阶段。

- [实验协议](protocol.md)：研究问题、机制、矩阵、估计对象和阶段门槛。
- [模型说明与假设](model_odd.md)：四类主体、业务过程、权限及结果判定。
- [政策到实现对应表](mechanism_mapping.md)与[参数依据](parameter_provenance.json)：分开来源事实、机制假设和参数设计。
- `design-8.json`、`design-10.json`、`design-12.json`：638、740、842次候选清单。生成清单不表示样本量已冻结或模型已运行。
- `design_protocol.json`：机器可读的种子池、数量、日程和样本量计算规则。
- `implementation_report.md`：本次实施最终验证与尚未执行部分，以报告实际生成的内容为准。

## 入口

在项目根目录运行。云端执行使用已有`/usr/local/bin/python`；下列`python`表示已确认的现有Python，不要求另装环境。

```powershell
python -B tools/build_v3_design.py --n all --output-dir NEW_DESIGN_DIR
python -B tools/run_v3_batch.py --manifest DESIGN_JSON --stage diagnostic --mode scripted --output NEW_REVIEW_DIR --dry-run
python -B tools/quote_v3.py --help
python -B tools/run_v3.py --help
python -B tools/analyze_v3.py --help
python -B tools/run_v3_offline.py --design DESIGN_JSON --output NEW_OUTPUT --coverage
python -B tools/collect_v3_records.py --design DESIGN_JSON --run-dir EXACT_COMPLETED_RUN --output NEW_RECORDS_JSON
python -B tools/build_v3_design.py --freeze-from-pilot VERIFIED_PILOT_RECORDS_JSON --frozen-output NEW_FROZEN_DESIGN_JSON
python -B tools/plot_v3.py ANALYSIS_JSON --output-dir NEW_FIGURES --units both
python -B -m unittest discover -s tests -v
```

`run_v3.py`的scripted模式使用官方框架及脚本决策，不读取秘密配置、不启动API代理。真实LLM模式只能由受850次总尝试和8次技术重跑约束的阶段控制器发起，必须绑定阶段授权、原API账本、来源代码和情景清单。旧200请求接入额度不是V3新阶段授权。

每轮实际动作、模型观察与输出、消息送达、成本、独立验收、失败和恢复都应留存。`controller_receipt.json`只报告最近一次分段调用；累计调用量必须汇总独立invocation回执并核对原API账本，不能累加重复的latest文件。

## 状态解释

离线脚本验证说明环境和测量可运行；官方框架脚本验证说明生命周期及恢复可运行；真实自主诊断说明模型在所给观察下的实际选择；正式研究结果必须来自冻结后的完整核验数据。四类证据分别标记。零采用、撤项、资源不足及负效果都是可保留的业务结果。

原平台截图对精确模型`deepseek-v4-flash`显示输入输出免费；该截图不是历史账单。新运行前仍核验价格和授权，不将旧错误费率当作实际收费，也不因此取消请求数和尝试数限制。

## 首阶段可审阅清单

[诊断请求与时间上限](diagnostic_quote.json)仅对应000、010、001各两个种子、每次30轮。请求硬上限1440，模型输入输出按已提供截图记0元；V3真实模型耗时尚未实测。单次完整运行采用1800秒超时，六次总运行时间上限10800秒，这是停止上限而非预测。

[未批准授权草案](diagnostic_authorization_UNAPPROVED.json)明确`approved=false`，不能直接执行。它绑定原API账本193条的只读基线，不删除旧账、不修改旧费用记录；旧名义估算金额不代表实际账单。批准后才记录真实用户授权并再次核对账本、模型价格和云端停止期限。每个后续阶段仍另行审阅。

以下是云端实际入口示例，`APPROVED_AUTH`必须指向该阶段有效授权。当前没有生成此类已批准文件：

```text
/usr/local/bin/python -B /home/coder/policy-mix/tools/run_v3_batch.py --manifest /home/coder/policy-mix/research/v3_20260909/design-8.json --stage diagnostic --mode llm --authorization APPROVED_AUTH --output NEW_RUNS_DIRECTORY --chunk-steps 30 --stop-at VERIFIED_UTC_DEADLINE --execute
```

`design-8.json`在诊断阶段只是包含共同6次诊断的候选清单，使用它不等于正式N已选8。规模冻结必须读取32条完整核验的真实预实验记录。`policy`三位字段仅保留旧接口标签；V3比较必须使用`scenario_id`、`q`和`schedule`，不得用旧标签重分组。

## 本次脚本证据复核

本次官方脚本的运行源码已保存快照。执行后只修正了独立验证器的JSON键比较，并增加存档源码参数；原仿真规则及适配器必须与当前重放实现相同才能通过复核。

```powershell
D:/miniconda1/python.exe -B tools/verify_v3.py --run-dir runs/v3-framework-diagnostic-20260909/v3_diagnostic_s1001_r0_diagnostic_A0_B0_C1 --source-root runs/v3-source-snapshots/c754073f2e7a89ea47f0b0f0d00de501379820e3ac87e1041681d90cd01c1225
```

事后过程审计不导入仿真器，单独记录自身及输入哈希：

```powershell
D:/miniconda1/python.exe -B research/v3_20260909/audit_process.py --run-dir EXACT_RECOVERED_RUN --output NEW_PROCESS_AUDIT_DIR
```

最终验收和未运行部分见[实施报告](implementation_report.md)，全交付文件哈希见`delivery_manifest.json`。
