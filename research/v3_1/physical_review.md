# 建成—技术投运—行政验收独立验证

日期：2026-09-10。仅验证当前原根`policy-v3-3.1`的物理与信息边界；本次只新增`tests/test_v3_physical.py`及本报告。未创建版本代码副本，未改业务代码或历史数据，未调用模型/API、访问云端或运行完整测试集。

结论：**13项定向离线测试通过**，其中11项对应原候选规程的11个用例，另2项检查零摩擦/强化合法同步及隐藏真实匹配信息隔离。通过表示这些构造路径的工程行为符合断言，不是自主模型行为或政策效果证据。

命令：在`D:/AgentSociety`执行`D:/miniconda1/python.exe -B tests/test_v3_physical.py`。测试入口显式把原根置于sys.path首位，并断言实际导入文件为`D:/AgentSociety/policy_v3/core.py`、schema为`policy-v3-3.1`。输出：`Ran 13 tests in 1.564s — OK`。

## 用例与证据

| 原规程id / 扩展项 | 可执行测试 | 验证内容 |
|---|---|---|
| built_no_commission | test_built_no_commission | 合法两分项施工在轮12建成；推进至轮15仍未投运、根源未修复，行政open。没有把建成或等候当作物理生效。 |
| commission_not_reported | test_commission_not_reported | 普通、非零摩擦通道中完成投运及生效后，角色2已知effective，但没有给角色4送达结果；角色4整个项目观察与投运前一致，行政仍open。 |
| late_admin | test_late_admin | 无成功回执时行政验收被业务拒绝，物理仍effective；角色2普通报告送达后可验收。负责人该次只扣0.1决策劳动，无重复技术费。 |
| wrong_plan | test_wrong_plan | 普通和强化两条完整流程均允许无共享根源方案取得自主approve、预算、两项施工；投运失败、无root_repaired，已花工程资金6保留，该次角色2支出0.5技术劳动加0.1决策劳动。 |
| cancel_before | test_cancel_before | 无共同根源的已建项目依据现场材料撤项。未通知角色2前其本地项目视图不变；其仍可见的陈旧投运候选实际执行被拒，只收0.1决策劳动，不收技术0.5，不退工程资金，不伪造物理生效。 |
| cancel_after | test_cancel_after | 利用未确认专项流程中仍合法存在的手工报告路径，先成功投运；部门3提出可见异议并报告负责人后，以已有容量/范围依据撤项。行政cancelled，built_at/effective_at及已修根源保留、资金不退。 |
| same_physics_both_modes | test_same_physics_both_modes | 合法普通流程取得全部材料后，复制同一状态仅切项目mode；同轮、同分派/回执、同资源的两次投运具有相同物理结果、劳动资金、时点和外生冲击记录。没有给强化组额外物理能力。 |
| stock_vs_recurrence | test_stock_vs_recurrence | 技术投运不会清掉初始12个未解决问题或叠加episode。随后通过正常个案派单、调查、作业修复一个局部问题；下一次具备再发生条件的冲击使用修复后风险，即使行政未验收。每设施未解决episode至多1个。 |
| invalid_combination | test_invalid_combination | 仅完成前一项施工时，已收到分派的角色2可以提出投运申请但业务执行被拒；负责人行政验收也拒绝。无物理效果、无行政accepted。 |
| boundary | test_boundary | 通过合法等待使后项在轮12完成；轮13投运因时滞拒绝，轮14成功，effective_at=15。物理激活事件早于轮15冲击；此前已记录冲击完全保留，不回溯改概率或事件。 |
| already_repaired_accept | test_already_repaired_accept | 确认所有项目设施已root_repaired=True后，合法投运结果报告送达负责人；行政验收仍正常通过，没有重复要求根源尚未修复。 |
| 合法自动同步 | test_zero_and_activated_sharing_can_lawfully_inform_owner | 普通零摩擦及已激活强化共享均能把投运结果依法送达负责人。未手工报告不被误当成必然未知，不为隔离测试而阻断合法共享。 |
| 隐藏信息隔离 | test_hidden_matching_never_filters_project_observations | 在已取得合法材料的同一状态，仅扰动审计层真实根源/匹配；四个角色观察逐字段相同，候选也相同。真实匹配留给执行环境，不通过提示或候选筛选泄漏。 |

## 测试准备与触发的区别

正向流程通过observe提供的候选依次执行：选题、主责确认、调查、拟案、专业自主同意、取得意见、预算、施工派工、技术交接、施工及投运。普通通道使用实际request_review/request_project_work和report_status；强化通道要先本人确认后才利用共享，零摩擦按共同被动规则送达。测试没有直接写入knowledge或伪造接收回执，也没有把某个预期状态预先设为成功。

两种明确的fixture例外不作为政策结果：第一，准备时用审计字段选取“有/无共享根源”或“单部门”设施原型，只用于隔离待测机制，不注入角色观察。第二，same_physics复制合法形成的同一状态后仅切mode；隐藏信息测试则只扰动审计真值且保留全部既有材料。这些用于受控边界/负例验证，不声称由自主主体产生。

## 结果边界

本轮未发现需要业务实现者返工的物理P1/P2。测试不覆盖全部自主选择组合、长期参数敏感性、随机模型输出、云端恢复、预算控制、全事件独立复算或全文档一致性；这些属于主方其他集成检查。新的物理实现不能回填或改变旧8530冻结版本历史运行，也不能将本报告的离线通过计为真实模型重复。
