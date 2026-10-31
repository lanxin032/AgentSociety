# 重构前的 agent 模拟流程

这是2026-10-31本轮重构前的历史图稿；最新实现见[官方调用流程](proposed-agent-simulation.md)。依据当时源码绘制。箭头表示运行顺序或已标明的数据读写；模型链路为调用关系。四主体在整轮边界结算，接收消息后才获得跨主体信息。

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Arial, PingFang SC, sans-serif", "fontSize": "16px", "lineColor": "#64748b", "primaryTextColor": "#0f172a", "edgeLabelBackground": "#ffffff"}, "flowchart": {"curve": "linear", "nodeSpacing": 24, "rankSpacing": 27, "htmlLabels": false, "wrappingWidth": 320, "padding": 32}, "themeCSS": ".node foreignObject, .nodeLabel, .nodeLabel div { overflow: visible !important; }"}}%%
flowchart LR
    subgraph runtime["运行控制 · 贯穿全程"]
        direction TB
        phase["execution.py<br/>阶段与尝试记录"]
        controller["controller.py<br/>授权、预算代理、子进程"]
        driver["driver.py<br/>官方调度、恢复与保存"]
        phase --> controller --> driver
    end
    subgraph behavior["每个主体的行为循环"]
        direction TB
        view["组装合法观察<br/>PolicyWorld<br/>WorkContext"]
        agent["PersonAgent<br/>Memory + 模型自主决策"]
        tools["PolicyRouter / PolicyEnv<br/>校验、读取、排队提交"]
        finish["原生finish或未办理收尾"]
        view --> agent --> tools
        tools -->|查询结果| agent
        tools --> finish
    end
    subgraph boundary["整轮结算与交付"]
        direction TB
        world["PolicyWorld.advance<br/>实体状态、规则与历史记录"]
        mailbox["官方邮箱收件<br/>SimpleSocialSpace<br/>接收后更新知识"]
        store["官方工作区、JSONL<br/>保存不可变检查点"]
        done{"全任务完成？"}
        result["独立审计与结果报告"]
        world --> mailbox --> store --> done
        done -->|是| result
    end
    runtime -->|调度四主体| behavior
    behavior -->|四主体均结束本轮| boundary
    boundary -->|未完成：下一轮| behavior
    class phase,controller,view,tools application;
    class driver,agent,finish,mailbox framework;
    class store,done,result evidence;
    class world data;

    classDef framework fill:#e8f0fe,stroke:#2563eb,stroke-width:1.5px,color:#163b72;
    classDef application fill:#fff3e6,stroke:#d97706,stroke-width:1.5px,color:#713f12;
    classDef evidence fill:#eaf5ef,stroke:#338062,stroke-width:1.5px,color:#14523a;
    classDef data fill:#f4efff,stroke:#7c65ad,stroke-width:1.5px,color:#46306c;
    style runtime fill:#f8fafc,stroke:#cbd5e1
    style behavior fill:#f8fafc,stroke:#cbd5e1
    style boundary fill:#f8fafc,stroke:#cbd5e1
```

当前流程中：运行控制分布在execution/controller/driver；PolicyWorld同时维护状态、生成候选、组装合法观察并执行结算；WorkContext承担本轮送达、分页和重读处理；官方PersonAgent负责ReAct与Memory，生产主体的选择由模型给出。

可定位的扫描包括core._legal_records对主体记录按对象过滤、core.observe对实体和消息生成视图，以及materials.lawful_sources为每条收到的记录寻找原始送达消息。它们是索引化候选，尚未测得对整场运行耗时的占比。

图稿核对：Mermaid CLI 12.0.0渲染通过，图源与Markdown一致。已逐项核对箭头、模块内容、整轮交付和完成分支；已查看PNG，文字完整、布局可读，评分9/10。跨组箭头表示执行阶段，不是具体函数调用。
