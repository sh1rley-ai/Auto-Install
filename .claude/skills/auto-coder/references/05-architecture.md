## 5. 系统架构与模块设计

### 多 Agent 架构设计

#### 为什么是这三个 Agent

多 Agent 的拆分边界应当跟随「决策职责」而非「工具种类」：

- **Planner Agent**（Deepseek-reasoner）：唯一职责是维护调查计划——初始规划、根据取证反馈重规划（增 / 删 / 改步骤）。它看到的是全局：案件线索、案件上下文、长期记忆、各步骤取证摘要。它不接触原始交易明细，只看摘要，因此上下文不被上千条流水淹没
- **Executor Agent**（Deepseek-chat + Tool Calling）：唯一职责是完成当前取证步骤——CoT 推理后选择工具（调单 / 规则检索 / 名单筛查 / 负面信息），观察结果决定继续取证或宣告本步完成 / 失败。它看到的是局部：当前步骤描述、本步内的工具调用记录
- **Verifier Agent**（Deepseek-chat + Tool Calling）：唯一职责是校验研判结论的证据完整性。与 Executor 共用同一套子图代码，差异只在三处配置：
  - **空白上下文**：只拿到「案件线索 + 待校验结论」，不带调查过程的消息历史。这是为了消除自评偏差（self-grading）——做调查的 Agent 复核自己的结论倾向于放行，典型漏网案例：结论声称「对手方 B 命中制裁名单」，但取证记录里筛查的其实是另一个同名主体；或结论引用了一条实际未命中的规则
  - **对抗性 prompt**（`prompt_verify`）：默认立场是「假设结论缺乏支撑，要求逐条出示证据」，用只读查询回验关键事实，而非顺着调查记录确认结论
  - **只读工具面**：仅允许只读查询类工具（交易查询 / 名单筛查 / 规则检索），不授予任何写入或状态变更能力
  - 输出结构化裁决 `{passed, evidence, failure_reason}`，写入 `AgentState.verdict`；failed 时 `failure_reason` 注入 Planner 的重规划上下文，驱动补充取证循环
- 交易调单、名单筛查、规则检索是**工具**（MCP Tools），不是 Agent——它们没有决策职责，拆成独立 Agent 只会增加通信开销和不确定性
- 规则引擎也不是 Agent——它是确定性计算组件，既作为 MCP 工具供 Executor 按需调用，也在终局 `compliance_node` 全量复跑一次做双路比对

这种拆分的收益：Planner 的上下文不被逐笔流水噪音污染，Executor 的上下文不需要携带完整全局历史，token 消耗和错误率同时下降；Executor 与 Verifier 构成 Generator-Critic（生成者-批判者）分离，校验结论不受调查过程叙述的诱导。Verifier 的新增成本约等于一个新 prompt——子图代码完全复用。

#### 状态与协作协议

```python
class InvestigationStep(TypedDict):
    id: int
    description: str        # 步骤描述，如 "调取主体账户近 90 天完整流水"
    status: str             # pending / running / done / failed / skipped
    result_summary: str     # Executor 回传的取证结果摘要

class AgentState(TypedDict):
    case: dict                    # 案件线索 {alert_id, subject_account, alert_type, window}
    case_context: str             # 案件上下文：机构类型 / 适用辖区 / 可用数据源 / 规则库版本
    memory_context: str           # 长期记忆检索结果（同类案件标准调查路径）
    plan: list[InvestigationStep] # Planner 维护的调查计划状态
    current_step_id: int
    executor_messages: list       # 子图局部消息（Executor 步骤间清空，Verifier 进入时置空）
    evidence: list[dict]          # 证据链 {id, tool, args, digest, timestamp}，报告引用的锚点
    rule_hits: list[dict]         # 规则引擎命中 {rule_id, name, level, citation, matched}
    verdict: dict                 # Verifier 裁决 {passed, evidence, failure_reason}
    report: dict                  # 结构化研判报告与合规审查意见
    consecutive_failures: int     # 连续失败步数，触发重规划
    replan_count: int             # 重规划次数上限保护
    step_count: int               # 全局步数上限保护
```

`evidence` 是证据链的唯一真相源：Executor 每次工具调用都追加一条带 id 的记录，报告中的每条结论通过 `evidence_refs` 引用这些 id。Verifier 校验的本质就是检查「结论 -> evidence 引用」这条链是否闭合且引用内容确实支持结论。

#### 状态机结构

```python
graph = StateGraph(AgentState)
graph.add_node("planner", plan_node)            # 生成 / 修订调查计划
graph.add_node("executor", executor_subgraph)   # 执行当前取证步骤（内部闭环）
graph.add_node("verifier", verifier_subgraph)   # Verifier Agent（复用 Executor 子图，独立 prompt + 空白上下文）
graph.add_node("compliance", compliance_node)   # 规则引擎双路合规校验 + 出具报告
graph.add_node("memorize", memorize_node)       # 蒸馏标准调查路径入库

graph.add_edge(START, "planner")
graph.add_conditional_edges("planner", route_plan, {
    "execute": "executor",     # 有 pending 步骤
    "verify": "verifier",      # 全部 done
    "abort": END               # 重规划超限，转人工
})
graph.add_conditional_edges("executor", route_step_result, {
    "next_step": "executor",   # 本步 done，取下一步
    "all_done": "planner",     # 无 pending 步骤，交还 Planner 决定是否进入校验
    "replan": "planner",       # 本步 failed 且连续失败达阈值
    "retry": "executor"        # 本步 failed，未达阈值，重试
})
graph.add_conditional_edges("verifier", route_verify, {
    "success": "compliance",
    "failed": "planner"        # 证据不完整，回 Planner 补充取证
})
graph.add_edge("compliance", "memorize")
graph.add_edge("memorize", END)
```

参数默认值（与实现一致）：`max_retries=2`、`max_replans=3`、`max_tool_iterations=6`（Verifier 为 4）。重规划超限走 `abort`，案件转人工，而不是输出一份低置信度报告。

Executor 内部是一个子图（executor_subgraph），实现单步闭环。子图由参数化工厂 `build_executor(llm, tools, prompt, fresh_context)` 装配——换上 `prompt_verify`、只读工具面和空白上下文，同一套代码即得到 verifier_subgraph：

```
reason_node (CoT 推理 + Tool Call)
    |
    +--> tool_node (调用 MCP 工具: query_transactions / screen_watchlist / ...)
    |        |
    |        v
    |    observe: 结果写回 executor_messages，并向 evidence 追加带 id 的证据记录
    |        |
    |        +--> reason_node (结果反馈驱动下一步决策)
    |
    +--> finish_step (宣告本步 done / failed，产出 result_summary)
```

#### compliance_node：双路合规校验

```
        +-- 规则路: rule_engine.evaluate(case, evidence)
        |            -> rule_hits [{rule_id, level, citation, matched}]
        |            -> 规则建议: 上报 STR / 不上报
compliance_node
        |
        +-- LLM 路: 基于 evidence + verdict 生成情境研判
                     -> LLM 建议: 上报 STR / 不上报 + 理由

        两路一致  -> report.conclusion = 该结论，附 rule_refs + evidence_refs
        两路不一致 -> report.conclusion = "needs_human_review"，
                      report.divergence 记录双方结论与依据
```

报告经 `report.schema.json` 校验后落盘：每条 finding 必须携带非空 `evidence_refs`，涉及监管判定的 finding 必须携带 `rule_refs`，否则校验失败并回写为归因 `hallucination`。

### 整体架构图

```
+------------------------------------------------------------------+
|                          CLI (main.py)                           |
|        python main.py --case ALERT-20260115-0032 --verbose       |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                       EnhancedConfig                             |
|          CLI Args > config/user_config.json > ENV vars           |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|              LangGraph 父图 (core/agent.py)                      |
|                                                                  |
|  [START] -> planner --------> executor 子图 -----> verifier      |
|               ^  (维护调查计划) (单步闭环:            |           |
|               |                 CoT -> tool -> 反馈)  |           |
|               +---- replan <--- 连续失败 -------------+           |
|               +---- 证据不足 <--------------------- failed        |
|               |                                       |           |
|          [END 转人工]                            compliance       |
|                                                       |           |
|                                            memorize -> [END]     |
+------+--------------------+------------------+-------------------+
       |                    |                  |
       v                    v                  v
+---------------+  +----------------------+  +----------------------+
| Short-term    |  | MCP Server           |  | RuleEngine           |
| Memory        |  | (mcp_server/)        |  | (core/rule_engine)   |
| (Checkpointer |  |  - query_transactions|  |  rules/*.yaml        |
|  + 阈值摘要)  |  |  - query_profile     |  |  绝对阈值 + 基线偏离 |
+---------------+  |  - search_regulations|  |  输出条款引用        |
       |           |  - screen_watchlist  |  +----------------------+
       v           |  - adverse_media     |
+---------------+  |  (全本地数据源      |  +----------------------+
| Long-term     |  |   受控访问 + 脱敏)  |  | AuditLogger          |
| Memory        |  +----------------------+  | (core/logger.py)     |
| (SQLite +     |                            |  logs/audit_*.jsonl  |
|  调查路径蒸馏)|                            |  哈希链防篡改        |
+---------------+                            |  logs/report_*.md    |
                                             +----------------------+
```

### 完整目录结构

```
AML-Guard/
├── main.py                          # CLI 入口（--case / --replay / --show-config）
├── requirements.txt                 # 依赖清单
├── CLAUDE.md                        # 开发规范（精简版）
├── DEV_SPEC.md                      # 本文档
│
├── config/
│   ├── enhanced_config.py           # 配置管理（dataclass + 三优先级加载）
│   └── user_config.json             # 用户配置（API Keys，不得硬编码）
│
├── core/
│   ├── __init__.py
│   ├── agent.py                     # LangGraph 父图（Planner/Verifier/Compliance/Memorize 节点 + 路由）
│   ├── executor.py                  # 参数化子图工厂（Executor/Verifier 共用: reason -> tool -> observe）
│   ├── plan.py                      # InvestigationStep/AgentState 定义 + 计划增删改操作
│   ├── investigator.py              # [RENAME<-installer.py] 对外接口，内部委托给 agent.py
│   ├── rule_engine.py               # [NEW] 规则引擎：YAML 规则加载 + 确定性判定 + 条款引用
│   ├── report.py                    # [NEW] 结构化研判报告生成 + JSON Schema 校验
│   ├── evidence.py                  # [NEW] 证据链记录与引用解析
│   ├── history_manager.py           # 短期记忆（阈值触发 LLM 摘要压缩）
│   ├── memory_manager.py            # [NEW] 长期记忆（SQLite CRUD + 调查路径蒸馏 + 检索）
│   └── logger.py                    # [REFACTOR] AuditLogger: 哈希链 JSONL 审查轨迹 + 完整性校验 + Markdown 报告
│
├── mcp_server/
│   ├── __init__.py
│   ├── server.py                    # [NEW] FastMCP Server 入口（stdio）
│   ├── transactions.py              # [NEW] 交易调单（账户/时间窗/对手方/金额区间）
│   ├── profile.py                   # [NEW] 客户档案与 KYC 查询
│   ├── regulations.py               # [NEW] 监管规则库检索（条款全文 + 出处）
│   ├── watchlist.py                 # [NEW] 名单筛查（制裁/PEP/内部黑名单，模糊匹配）
│   ├── adverse_media.py             # [NEW] 负面信息检索（本地策展语料，无外部网络请求）
│   └── guard.py                     # [NEW] 受控访问：条数上限/超时/字段脱敏/审计
│
├── rules/
│   ├── pboc.yaml                    # [NEW] 人行反洗钱规则（大额/可疑交易报告要点）
│   ├── fatf.yaml                    # [NEW] FATF 建议映射
│   └── report.schema.json           # [NEW] 研判报告结构定义
│
├── data/
│   ├── schema.sql                   # [NEW] 交易/账户/名单/负面信息/预警表结构
│   ├── generate_dataset.py          # [NEW] 固定 seed 合成数据生成器
│   ├── seed.json                    # [NEW] 生成参数与 seed（提交进仓库）
│   ├── aml_dataset.sqlite           # [NEW] 生成结果（提交进仓库，保证可复现）
│   └── DATASET.md                   # [NEW] 数据字典、可疑模式构造说明、校验和
│
├── utils/
│   ├── __init__.py
│   ├── deepseek.py                  # Deepseek API 封装（streaming + retry）
│   ├── qwen.py                      # Qwen API 封装（摘要 / 蒸馏 / 相关性判断）
│   └── text_processors.py           # 文本抽取工具
│
├── prompt/
│   └── prompt.py                    # 所有 prompt 模板集中管理（规划/取证/重规划/校验/研判/蒸馏）
│
├── eval/
│   ├── benchmark.jsonl              # [NEW] 约 200 条标注案件测试集
│   └── run_eval.py                  # [NEW] 批量评估脚本，统计准确率与四类失败归因
│
├── tests/
│   ├── unit/
│   └── integration/
│
└── logs/                            # 运行时生成，不提交 git
    ├── audit_*.jsonl                # 结构化审查轨迹（回溯/回放用）
    └── report_*.md                  # 人类可读研判报告
```

### 模块职责说明

| 模块 | 职责 | 关键类/函数 |
|------|------|------------|
| `main.py` | CLI 参数解析、配置加载、案件入口、轨迹回放、审计链校验 | `main()`, `replay_trace()`, `verify_audit()` |
| `config/enhanced_config.py` | 三优先级配置加载、字段校验、序列化 | `EnhancedConfig`, `AIModelConfig` |
| `core/agent.py` | 父图定义：Planner / Compliance / Memorize 节点、Verifier 装配与条件路由 | `build_graph()`, `plan_node()`, `build_verifier()`, `compliance_node()` |
| `core/executor.py` | 参数化子图工厂（Executor 与 Verifier 共用）：CoT 推理 -> 工具调用 -> 结果反馈闭环 | `build_executor(llm, tools, prompt, fresh_context)`, `reason_node()`, `route_tool()` |
| `core/plan.py` | 调查计划数据结构与增删改操作，重规划 patch 应用 | `InvestigationStep`, `AgentState`, `apply_plan_patch()` |
| `core/investigator.py` | 对外接口，加载案件、组装图、驱动一次完整调查 | `AMLGuard.investigate()`, `get_investigation_status()` |
| `core/rule_engine.py` | YAML 规则加载、绝对指标与基线偏离指标计算、确定性判定、条款引用输出 | `RuleEngine.load()`, `RuleEngine.evaluate(case, evidence)`, `compute_baseline()` |
| `core/report.py` | 研判报告组装、Schema 校验、Markdown 渲染 | `build_report()`, `validate_report()`, `render_markdown()` |
| `core/evidence.py` | 证据链追加、id 分配、引用解析与闭合性检查 | `append_evidence()`, `resolve_refs()` |
| `core/history_manager.py` | 短期记忆：消息超阈值触发 LLM 总结，保留最近 N 轮完整记录 | `HistoryManager`, `summarize_old_entries()` |
| `core/memory_manager.py` | 长期记忆：调查通过后蒸馏路径入库，启动前检索相关案件 | `MemoryManager`, `distill_investigation_path()`, `retrieve_relevant()` |
| `core/logger.py` | 哈希链 JSONL 审查轨迹（step_type/content/timestamp/prev_hash/entry_hash）+ 完整性校验 + Markdown 报告 | `AuditLogger.log_step()`, `AuditLogger.verify_chain()`, `AuditLogger.attribute_failure()` |
| `mcp_server/server.py` | FastMCP Server 入口，注册工具，stdio 传输 | `mcp = FastMCP("aml-guard")` |
| `mcp_server/transactions.py` | 交易调单：账户 / 时间窗 / 对手方 / 金额区间，返回聚合摘要 + 明细引用 | `query_transactions()` |
| `mcp_server/profile.py` | 客户档案与 KYC：开户信息、经营范围、历史风险等级 | `query_account_profile()` |
| `mcp_server/regulations.py` | 监管规则库检索，返回条款全文与出处 | `search_regulations(query)` |
| `mcp_server/watchlist.py` | 名单筛查：制裁 / PEP / 内部黑名单，rapidfuzz 模糊匹配 | `screen_watchlist(name, id_no)` |
| `mcp_server/adverse_media.py` | 负面信息检索：查本地策展语料表，返回命中条目与出处 | `search_adverse_media(entity)` |
| `mcp_server/guard.py` | 受控访问：返回条数上限、超时、敏感字段脱敏、访问审计 | `guarded(fn)`, `mask_sensitive()` |
| `utils/deepseek.py` | Deepseek API 调用，streaming + 指数退避重试 | `Deepseek.chat()`, `Deepseek.stream_chat()` |
| `utils/qwen.py` | Qwen API：摘要、蒸馏、相关性判断 | `QueryTongyi.chat()` |
| `prompt/prompt.py` | prompt 模板集中管理 | `prompt_plan`, `prompt_replan`, `prompt_execute`, `prompt_verify`, `prompt_judge`, `prompt_distill` |
| `data/generate_dataset.py` | 固定 seed 合成交易 / 账户 / 名单 / 负面信息 / 预警，注入已知可疑模式并打标 | `generate(seed)`, `inject_patterns()` |
| `eval/run_eval.py` | 在标注测试集上批量运行，统计准确率与四类失败归因分布 | `run_benchmark()` |

### 规则库定义格式

规则以 YAML 声明，与代码分离，便于合规人员审阅与版本化：

```yaml
- id: R-003
  name: 结构化拆分规避大额报告
  level: high
  citation: "《金融机构大额交易和可疑交易报告管理办法》(银发[2016]3号) 第五条、第十一条"
  window_days: 30
  condition:
    all:
      - metric: near_threshold_count      # 落在报告阈值 90%-99% 区间的笔数
        op: ">="
        value: 10
      - metric: near_threshold_ratio      # 该类交易占同期笔数比例
        op: ">="
        value: 0.6
  evidence_fields: [txn_ids, amount_distribution, threshold]

- id: R-011
  name: 短期内高频跨境交易
  level: medium
  citation: "《金融机构大额交易和可疑交易报告管理办法》第十一条(五)"
  window_days: 30
  condition:
    all:
      - metric: cross_border_count
        op: ">="
        value: 20
      - metric: cross_border_amount_sum
        op: ">="
        value: 1000000
  evidence_fields: [txn_ids, counterparty_countries]

- id: R-024
  name: 交易行为显著偏离账户历史基线
  level: medium
  citation: "《金融机构大额交易和可疑交易报告管理办法》第十一条(一)"
  window_days: 30
  baseline:                             # 基线口径：对比窗之前的 180 天
    lookback_days: 180
    min_observations: 30                # 基线样本不足则本规则不参评，避免新开户误判
  condition:
    any:
      - metric: deviation_from_baseline.amount_sum
        op: ">="
        value: 5.0                      # 期间总额达基线均值的 5 倍
      - metric: deviation_from_baseline.txn_count_zscore
        op: ">="
        value: 3.0                      # 笔数偏离基线 3 个标准差
      - metric: deviation_from_baseline.new_counterparty_ratio
        op: ">="
        value: 0.8                      # 对手方八成以上为基线期内未出现过的新主体
  evidence_fields: [baseline_window, baseline_stats, current_stats]
```

**关于绝对阈值与基线偏离**：R-003 / R-011 这类绝对阈值规则对应监管明文规定的报告义务，必须保留；但真实可疑交易识别中更有判别力的是**相对该账户自身历史的偏离**——月流水常年 5 万的个体户突然单月 380 万才是异常信号，而同样的 380 万对一家贸易公司可能完全正常。仅靠绝对阈值会同时产生大量误报（活跃大客户）与漏报（金额刻意压在阈值下但相对自身暴增）。

因此规则库支持两类 metric：

- **绝对指标**：`near_threshold_count` / `cross_border_count` / `cross_border_amount_sum` 等，直接对照监管阈值
- **基线偏离指标**：`deviation_from_baseline.*`，在规则声明的 `baseline.lookback_days` 窗口上先算该账户自身的历史统计（均值、标准差、对手方集合），再计算当前观察窗相对基线的倍数 / z-score / 新对手方占比

基线口径由规则自身声明而非全局固定，因为不同可疑模式关心的历史长度不同。`min_observations` 是必需的保护：基线样本不足（新开户、休眠账户刚激活）时该规则直接不参评并在证据中记录原因，否则任何新账户的首笔交易都会被判为「无穷倍偏离」。

`RuleEngine.evaluate()` 输入案件与证据链，输出命中列表 `{rule_id, name, level, citation, matched: {metric: 实际值}}`，其中 `matched` 保留实际计算值以便报告中直接展示「阈值 10 / 实际 43」或「基线均值 4.8 万 / 当期 386 万 / 偏离 80 倍」这类可复算的依据。

### 数据流说明

```
输入: python main.py --case ALERT-20260115-0032
    |
    v
[1] 案件上下文加载 load_case_context()
    -> 主体: 账户 6222****8891（个体工商户，风险等级 M）
       预警: 30 天内 47 笔跨境转入，累计 386 万，单笔集中在 4.5-4.9 万
       上下文: 辖区中国大陆，规则库版本 PBOC-2025.03，可用数据源 [交易/档案/名单]
    -> 注入 AgentState.case / case_context

[2] 长期记忆检索 memory_manager.retrieve_relevant(alert_type="高频跨境+金额贴近阈值")
    -> 命中"疑似拆分规避大额报告"标准调查路径，注入 AgentState.memory_context

[3] planner: Deepseek-reasoner 生成结构化调查计划（结合线索 + 上下文 + 记忆）
    -> plan = [
         {id:1, desc:"调取主体账户近 90 天完整流水", status:pending},
         {id:2, desc:"计算金额分布与报告阈值贴近度，跑规则引擎", status:pending},
         {id:3, desc:"展开一度对手方，识别集中收付款方", status:pending},
         {id:4, desc:"对高频对手方做名单筛查与负面信息检索", status:pending},
         {id:5, desc:"核查 KYC 申报经营范围与资金流向匹配性", status:pending},
       ]

[4] executor step 1: Tool Call query_transactions(account=..., window_days=90)
    -> 返回聚合摘要（1,283 笔 / 转入 512 万 / 转出 498 万）+ 明细引用 id
    -> evidence 追加 E-001

[5] executor step 2: Tool Call run_rule_engine(...)
    -> 命中 R-003（阈值 10 / 实际 43 笔落在 90%-99% 区间）、R-011
    -> evidence 追加 E-002，rule_hits 写入

[6] executor step 3: Tool Call expand_counterparties(depth=1)
    -> 12 个对手方，其中 3 个占转入额 78%  -> evidence 追加 E-003

[7] executor step 4: Tool Call screen_watchlist(对手方 B)
    -> 命中内部黑名单（相似度 0.94，同一证件号）-> evidence 追加 E-004
    Tool Call search_adverse_media(对手方 B) -> 无公开负面 -> evidence 追加 E-005

[8] executor step 5: Tool Call query_account_profile(主体)
    -> 申报经营范围"服装零售"，与跨境资金规模显著不匹配 -> evidence 追加 E-006

[9] verifier: 空白上下文启动（只给案件线索 + 待校验结论，不带调查过程消息历史）
    -> 逐条要求出示证据并只读回验:
       结论"存在拆分规避"      -> E-002 规则命中 + E-001 金额分布  通过
       结论"对手方 B 涉黑名单"  -> E-004 筛查记录（回验证件号一致）  通过
       结论"经营范围不匹配"    -> E-006 档案记录  通过
    -> 裁决 {passed: true} -> compliance

[10] compliance: 双路合规校验
    规则路: rule_engine 全量复跑 -> R-003 / R-011 / R-020 命中，建议上报 STR
    LLM 路: 基于证据链研判 -> 建议上报 STR，理由：资金规模与申报经营严重背离且存在拆分特征
    -> 两路一致 -> 生成报告: risk_level=high, conclusion=submit_str
       每条 finding 附 evidence_refs=[E-001..E-006] 与 rule_refs=[R-003, R-011, R-020]
    -> report.schema.json 校验通过后落盘 logs/report_*.md
    (若两路不一致 -> conclusion=needs_human_review，divergence 记录双方依据)

[11] memorize:
    qwen.distill_investigation_path(trace) -> 剔除试错分支，保留有效取证序列
    memory_manager.save_case(alert_type=..., distilled_steps=..., outcome=submit_str)

[12] 全程 AuditLogger 逐步落盘:
    {"step_type": "plan",      "content": {...}, "timestamp": "2026-01-15T10:00:01"}
    {"step_type": "tool_call", "content": {"tool": "query_transactions", ...}, "timestamp": ...}
    {"step_type": "rule_hit",  "content": {"rule_id": "R-003", ...}, "timestamp": ...}
    {"step_type": "verify",    "content": {"passed": true, ...}, "timestamp": ...}
    每条附 prev_hash / entry_hash 构成哈希链，报告尾部记录链尾锚点
    -> 支持 python main.py --replay logs/audit_xxx.jsonl 回放
    -> 支持 python main.py --verify-audit logs/audit_xxx.jsonl 校验完整性
```

### 双层记忆机制

**短期记忆（调查内）**：

- 载体：LangGraph Checkpointer + `HistoryManager`
- 触发：Executor 消息历史超过阈值（默认 6 轮）时，自动调用 Qwen 总结旧记录为摘要，保留最近 2 轮完整记录
- 目的：长调查链路（对手方展开可能产生大量工具返回）不撑爆上下文，同时不丢失关键线索
- 注意：摘要压缩的只是 `executor_messages`，`evidence` 证据链永不压缩——报告引用依赖它的完整性

**长期记忆（跨案件）**：

- 载体：SQLite（`investigation_records` 表）
- 写入：调查通过校验后，调用 Qwen 对完整轨迹做**调查路径蒸馏**——剔除失败重试和无效取证分支，只保留最终有效的步骤序列，作为同类案件的高质量参考
- 读取：调查启动前按预警类型 + 案件特征检索，Qwen 做相关性过滤（防止「高频跨境」误命中特征完全不同的案件），命中则注入 Planner 上下文
- 收益：同类案件复用标准路径后，平均调查步骤下降约 30%

```sql
CREATE TABLE IF NOT EXISTS investigation_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,          -- 预警类型（高频跨境/拆分/快进快出...）
    case_features TEXT,                -- 案件特征摘要（用于相关性检索）
    jurisdiction TEXT,                 -- 适用辖区
    distilled_steps TEXT,              -- LLM 蒸馏后的标准调查路径（JSON）
    rule_hits TEXT,                    -- 命中规则 id 列表（JSON）
    outcome TEXT,                      -- submit_str / no_action / needs_human_review
    audit_trace_path TEXT,             -- 原始审查轨迹路径（归因/回放用）
    session_id TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_type ON investigation_records(alert_type);
```

### 哈希链审查日志与回放

- **格式**：JSONL，每行一个事件，除业务字段外携带链式哈希：

```json
{"seq": 7, "step_type": "tool_call", "content": {"tool": "query_transactions", "args": {...}},
 "timestamp": "2026-01-15T10:00:07", "prev_hash": "8f3a...c1", "entry_hash": "2b7e...9d"}
```

  step_type 枚举：`plan / replan / reason / tool_call / tool_result / rule_hit / step_done / step_failed / verify / compliance / report / distill / abort`

- **哈希链构造**：`entry_hash = sha256(canonical_json({seq, step_type, content, timestamp, prev_hash}))`，其中 `canonical_json` 用排序键 + 无空格分隔符保证同一条目在任何机器上序列化结果一致；首条 `prev_hash` 为案件 id 派生的创世值（`sha256(case_id + ruleset_version)`），使每个案件的链彼此独立且绑定当时的规则库版本
- **为什么需要**：审查日志是监管检查时的证据本身。事后修改一条记录（改掉一次不该有的账户查询、补一条没做过的名单筛查）在普通 JSONL 里无痕，加链后任何插入 / 删除 / 篡改都会让后续所有 `prev_hash` 失配。这不是防内部人作恶的强保证（持有文件写权限者可整链重算），但把「悄悄改一行」的成本提升到「重写整条链且必须同时改掉归档副本」，配合日志追加写 + 只读归档已足够满足留痕要求
- **完整性校验**：`AuditLogger.verify_chain(path)` 逐条重算并比对，返回 `{ok, broken_at_seq, expected, actual}`；`python main.py --verify-audit logs/audit_xxx.jsonl` 暴露为 CLI，断裂时打印首个失配条目的 seq 与前后上下文
- **合规留痕**：轨迹记录完整的数据访问行为（谁在何时查了哪个账户的哪段区间），满足事后审计与监管检查要求；报告落盘时把最后一条的 `entry_hash` 写入报告尾部作为链尾锚点，报告与轨迹从此互相绑定
- **失败归因**：调查失败或报告校验不通过时，`AuditLogger.attribute_failure()` 沿轨迹定位首个不可恢复问题，归入 planning / tool / verification / hallucination 四类，写入报告与评估统计
- **轨迹回放**：`python main.py --replay logs/audit_xxx.jsonl` 按时间序重现每步决策与取证结果，便于调试、演示与人工复核
- **人类可读报告**：同步生成 Markdown 版研判报告（案件概要、调查过程、证据清单、规则命中、审查意见）

### 配置驱动设计示例

```json
{
    "ai_models": {
        "deepseek_api_key": "",
        "qwen_api_key": ""
    },
    "history": {
        "max_history_rounds": 6,
        "keep_recent_rounds": 2,
        "enable_summarization": true
    },
    "investigation": {
        "max_investigation_steps": 30,
        "max_step_retries": 2,
        "max_replans": 3,
        "tool_timeout_seconds": 60
    },
    "data_access": {
        "max_rows_per_query": 2000,
        "default_window_days": 90,
        "mask_fields": ["id_no", "phone", "address"]
    },
    "compliance": {
        "rules_dir": "rules",
        "ruleset_version": "PBOC-2025.03",
        "require_rule_ref_for_str": true
    },
    "logging": {
        "log_directory": "logs",
        "enable_audit_jsonl": true,
        "enable_hash_chain": true,
        "enable_markdown_report": true
    }
}
```

---
