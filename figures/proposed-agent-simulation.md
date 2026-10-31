# 按官方 agentic loop 重构的流程图

更新日期：2026-10-31，已实施，限离线验证。完整职责、路由取舍和验收依据见[当前重构设计](../research/v3_1/native-refactor-design.md)，官方能力依据见[2.8.7 调用契约](../research/v3_1/official-agentic-loop-20261031.md)。本图替代上一版以通用运行协调器为中心的提案。

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Arial, PingFang SC, sans-serif", "fontSize": "16px", "lineColor": "#64748b", "primaryTextColor": "#0f172a", "edgeLabelBackground": "#ffffff"}, "flowchart": {"curve": "linear", "nodeSpacing": 24, "rankSpacing": 27, "htmlLabels": false, "wrappingWidth": 320, "padding": 32}, "themeCSS": ".node foreignObject, .nodeLabel, .nodeLabel div { overflow: visible !important; }"}}%%
flowchart LR
    subgraph runtime["官方生命周期"]
        direction TB
        init["agent_specs / 角色 Skill<br/>注入 ServiceProxy<br/>AgentSociety.init"]
        scheduler["AgentSociety.step / run<br/>官方 Ray Tasks 调度"]
        init --> scheduler
    end
    subgraph behavior["每个主体 · 官方 agentic loop"]
        direction TB
        restore["from_workspace<br/>恢复主体、记忆和技能"]
        agent["PersonAgent.step<br/>run_react_loop<br/>观察 → 自主决策"]
        router["ask_env<br/>官方 ReActRouter<br/>选择注册工具"]
        tools["PolicyEnv（EnvBase）<br/>@tool 查询与单次提交"]
        finish["finish / 迭代耗尽<br/>官方记忆与工作区保存"]
        restore --> agent --> router --> tools
        tools -->|真实工具反馈| agent
        agent -->|本主体结束| finish
    end
    subgraph boundary["整轮结算与验收"]
        direction TB
        settle["验收四主体返回结果<br/>通过后 env.step 结算<br/>官方邮箱整轮送达"]
        save["官方工作区保存<br/>项目一致性检查与 commit"]
        done{"有限任务全部完成？"}
        report["独立审计与指标报告"]
        next["下一轮<br/>调用 society.step"]
        pause["技术失败暂停<br/>保留证据并排空在途请求"]
        settle --> save --> done
        done -->|是| report
        done -->|否| next
        settle -->|技术失败| pause
        save -->|保存失败| pause
    end
    runtime -->|逐轮调度| behavior
    behavior -->|全部主体返回后| boundary
    class init,scheduler,restore,agent,router,finish,next framework;
    class tools application;
    class settle,save,done,report,pause evidence;
    classDef framework fill:#e8f0fe,stroke:#2563eb,stroke-width:1.5px,color:#163b72;
    classDef application fill:#fff3e6,stroke:#d97706,stroke-width:1.5px,color:#713f12;
    classDef evidence fill:#eaf5ef,stroke:#338062,stroke-width:1.5px,color:#14523a;
    style runtime fill:#f8fafc,stroke:#cbd5e1
    style behavior fill:#f8fafc,stroke:#cbd5e1
    style boundary fill:#f8fafc,stroke:#cbd5e1
```

蓝色为官方实现；橙色为政策业务环境；绿色为整轮结算和研究验收。失败箭头表示项目必须保证的结果，不表示框架自动传播全部异常。ReActRouter 是官方支持的替代路由，并非默认 CodeGenRouter；actor 组装、可信上下文、计量与失败验收仍为项目适配。

跨组箭头表示执行阶段。未完成时只再调用 society.step，不重新初始化；技术失败先保存证据，再按现有恢复约定处理。

图稿验收：Mermaid CLI 12.0.0 渲染通过，图源与 Markdown 相同。已查看 PNG，核对全部标签、工具反馈回路、整轮屏障、失败和完成分支；文字完整，流程从左向右，评分 9/10，接受。跨组连线表达阶段，细节以设计说明的调用顺序为准。
