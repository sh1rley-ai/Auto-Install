# DEV_SPEC.md — AML-Guard 开发规范

> 本文档是项目的唯一技术权威参考。所有架构决策、模块设计、开发规范均以本文档为准。
> 章节结构与 auto-coder skill 的 references 映射一一对应（1 概述 / 2 特性 / 3 技术选型 / 4 测试 / 5 架构 / 6 排期 / 7 未来规划），修改章节标题或顺序前须同步更新 `.claude/skills/auto-coder/scripts/sync_spec.py` 的映射。

---

## 1. 项目概述

### 设计理念

AML-Guard 是一个基于 LangGraph 的多 Agent 系统，面向银行与支付机构的反洗钱与合规审查场景，对可疑交易线索自动完成调查规划、调单取证、多源交叉核验，输出结构化研判报告与合规审查意见。

**目标**：输入一条可疑交易线索（大额异常转账、高频跨境交易、结构化拆分等），系统自动完成调查规划、取证、交叉核验与合规研判，产出可追溯的研判报告。

**核心理念**：将一次可疑交易调查建模为 Plan-and-Execute 多 Agent 协作过程，由 LangGraph 状态机编排规划 / 执行 / 校验三个 Agent。Planner 负责生成并维护一份可增删改的结构化调查计划（Plan State）；Executor 按步取证，每步内部走「CoT 推理决策 -> 工具调用 -> 结果反馈驱动下一步」的闭环；取证结果回传 Planner，失败时先重试，连续失败触发动态重规划；全部步骤完成后由独立的 Verifier 以空白上下文对抗性校验研判结论的证据完整性，不通过则回到 Planner 补充取证。

**背景**：反洗钱调查是银行合规部门的高频重负荷工作。一线分析师需对海量交易预警逐条调单、比对名单、检索监管规则并撰写研判报告，流程繁琐、高度依赖经验，且真实可疑案件在预警中占比极低，人力被大量消耗在排除误报上。而调查本身是一个有章可循的过程：取证路径可结构化、规则引用可确定性计算，大模型可以按标准流程完成事实梳理与初步研判，把人力集中到真正需要专业判断的案件上。

**设计原则**：

- **Plan-and-Execute 多 Agent**：Planner 先生成全局调查计划并全程维护计划状态（可增/删/改步骤），Executor 逐步取证；相比单步 ReAct 循环，全局计划显著降低调查方向性偏差
- **执行闭环 + 动态重规划**：每步取证结果（含异常与空结果）反馈给 Executor 自我修正重试；连续失败超过阈值时上报 Planner 重规划，而非无限重试
- **校验与执行分离（Generator-Critic）**：独立 Verifier Agent 复用 Executor 子图代码，以空白上下文 + 对抗性 prompt + 只读工具面独立裁决研判结论是否有取证支撑，消除「调查者给自己打分」的自评偏差
- **规则引擎与 LLM 双路合规校验**：确定性规则匹配与 LLM 情境研判并行，两路结论合并出具意见，不一致时降级为人工复核而非由模型单方定夺
- **结论必须附证据**：报告中每一条研判结论都携带证据引用（工具调用记录）与规则引用（监管条款出处），无证据支撑的结论不得进入报告
- **工具层标准化**：交易数据查询、客户档案、监管规则库检索、名单筛查、负面信息检索封装为独立 MCP Server，与 Agent 编排层解耦，可被任意 MCP 客户端复用；数据访问的权限校验、字段脱敏与审计留痕在协议边界统一收口
- **全本地数据源**：所有工具只读取仓库内的规则库与数据集，调查过程不发起任何外部网络请求；这是评测可复现的前提，也避免向外部服务泄露案件信息
- **评测可复现**：评测基于公开反洗钱数据集构建，案件抽样与补全数据（档案 / 名单 / 负面信息）全部由单一固定 seed 驱动，原始文件以 SHA256 锁定版本，任何人使用同一 seed 与同一原始文件重建后跑出的 benchmark 结果与文档一致；公开数据集本身为匿名化模拟数据，不含任何真实客户信息
- **可追溯且防篡改**：全流程结构化审查日志（步骤类型 / 内容 / 时间戳）逐条以哈希链串接，任何事后修改或删除都会使链断裂并被校验命令定位；支持失败归因与调查轨迹回放，满足合规留痕与事后复核要求

### 项目定位

面向求职实战的 AI Agent 工程项目，核心展示能力：

- 基于 LangGraph 的 Plan-and-Execute 多 Agent 架构（Planner + Executor + Verifier，规划 / 执行 / 校验三权分离）
- Agent 执行闭环：CoT 推理 -> 结构化 Tool Calling -> 结果反馈 -> 重试 / 重规划
- 模块化 MCP Server（交易调单 / 客户档案 / 监管规则库检索 / 名单筛查 / 负面信息检索）
- 规则引擎与 LLM 双路合规校验，审查结论附规则引用，审查日志全链路留痕
- 短期 + 长期双层记忆：阈值触发 LLM 摘要 + 标准调查路径 LLM 蒸馏入库
- 量化评估：基于公开反洗钱数据集构建约 200 条标注测试集（固定 seed 分层抽样与补全，保证可复现），端到端调查准确率约 75%

---

## 2. 核心特点

| 特点 | 说明 |
|------|------|
| **Plan-and-Execute 架构** | Planner 生成结构化调查计划并维护计划状态（每步含 id / 描述 / 状态），Executor 按步取证；取证结果驱动 Planner 对计划增删改，动态重规划 |
| **Agent 执行闭环** | Executor 每步内部：CoT 推理决策 -> Tool Calling（交易调单 / 规则检索 / 名单筛查 / finish_step）-> 结果反馈驱动下一步；失败自动重试，连续失败触发重规划 |
| **独立 Verifier Agent** | 校验与执行分离（Generator-Critic）：Verifier 以空白上下文、对抗性立场校验研判结论的证据完整性，复用 Executor 子图代码，只换 prompt 与工具面（只读查询），输出结构化裁决 passed / evidence / failure_reason |
| **规则引擎与 LLM 双路合规校验** | 规则引擎做确定性匹配，同时支持绝对阈值（大额 / 高频跨境 / 拆分 / 名单命中）与账户历史基线偏离（金额倍数 / 笔数 z-score / 新对手方占比），后者避免「活跃大客户恒误报、金额压阈值恒漏报」；LLM 结合证据链做情境研判，两路结论合并入报告，不一致时标记 needs_human_review 交人工复核 |
| **结论附证据与规则引用** | 报告中每条结论关联 evidence_refs（工具调用记录 id）与 rule_refs（监管条款出处），报告经 JSON Schema 校验，无引用结论不得落地 |
| **模块化 MCP Server** | 交易调单、客户档案、监管规则库检索、名单筛查、负面信息检索封装为标准 MCP 工具，通过 stdio 暴露，可被 Claude Desktop 等任意 MCP 客户端直接复用 |
| **双层记忆机制** | 短期：单次调查内消息超阈值自动触发 LLM 总结压缩；长期：调查通过校验后 LLM 蒸馏标准调查路径（剔除试错分支）存入 SQLite，同类案件跨会话复用，平均调查步骤下降约 30% |
| **哈希链审查日志与回放** | 每步记录 step_type / content / timestamp 的 JSONL 轨迹，每条携带前一条的哈希构成防篡改链，`--verify-audit` 校验完整性并定位首个断裂点；全链路留痕支持合规回溯与轨迹回放，同时输出人类可读 Markdown 研判报告 |
| **受控数据访问** | 交易调单与名单筛查经受控访问层：查询范围与返回条数上限、超时控制、敏感字段脱敏后入 LLM 上下文、访问全量审计留痕 |
| **量化评估** | 基于公开反洗钱数据集构建约 200 条标注测试集，以固定 seed 驱动分层抽样与补全数据生成、原始文件 SHA256 锁定版本，保证评测可复现；端到端调查准确率约 75%，按规划 / 工具 / 校验 / 幻觉输出四类归因统计失败分布 |

---

## 3. 技术选型

### AI 模型

| 模型 | 用途 | 选型理由 |
|------|------|----------|
| **Deepseek-reasoner** | Planner（调查规划 / 重规划） | 多步推理能力强，支持 thinking 输出；取证顺序、资金链路展开深度这类全局决策需要长链推理 |
| **Deepseek-chat** | Executor（单步取证决策）/ Verifier（证据完整性校验） | Tool Calling 稳定，单步决策与校验不需要 reasoner 的成本 |
| **Qwen-plus** (DashScope) | 会话摘要 / 标准调查路径蒸馏 / 记忆相关性判断 | 成本低，摘要与蒸馏任务不需要最强模型 |

**关于数据出域**：本项目默认走公有云 API，评测与演示数据为公开反洗钱数据集（本身即匿名化模拟数据）及其固定 seed 补全数据，不涉及真实客户信息。生产落地时两个 Agent 角色的模型可整体替换为私有化部署（模型接口经 `utils/` 封装层隔离，替换不影响编排层）；交易明细始终留在 MCP 工具层，只有脱敏聚合摘要进入 LLM 上下文——这是 MCP 边界收口设计的直接收益。

### 为什么不接联网检索

早期方案曾计划用带 `$web_search` 的模型做监管规则更新检索与负面信息检索，最终放弃，全部改为本地规则库与本地策展语料。三条理由：

- **评测不可复现**：本项目的核心产出之一是可复现的量化评测。联网检索结果逐日变化，同一份代码今天与下月跑出的准确率无法归因——是模型改了，还是外部网页变了。所有外部依赖必须是仓库内固定的
- **权威性反而更差**：监管条款需要带出处、带生效日期、可按案发时点复算，这只能由策展语料库提供；搜索结果摘要是幻觉源而不是权威源
- **成本与场景不匹配**：长上下文检索调用是全系统最重的 token 消耗，而评测集的账户与主体来自匿名化公开数据集及合成补全——在真实互联网上并不存在，检索只会返回无关真人，既是噪音也带来隐私问题

因此 `search_regulations` 读本地 `rules/` 规则库与条款语料，`search_adverse_media` 读仓库内固定 seed 生成的合成负面信息语料表。系统在调查过程中**不发起任何外部网络请求**，除模型 API 之外无外部依赖。

### 框架与库

| 库 | 版本 | 用途 |
|----|------|------|
| `langgraph` | >=0.2 | 多 Agent 状态机编排（父图 + Executor / Verifier 共用子图） |
| `langchain-core` | >=0.3 | Tool 定义、消息类型（AIMessage、ToolMessage） |
| `mcp` | >=1.0 | MCP Server 实现（FastMCP，stdio transport） |
| `langchain-mcp-adapters` | >=0.1 | Agent 侧加载 MCP 工具为 LangChain Tool |
| `openai` | >=1.0 | Deepseek API 客户端（OpenAI 兼容协议） |
| `dashscope` | >=1.14 | Qwen API 客户端 |
| `pandas` | >=2.0 | 交易特征聚合（时间窗统计、对手方分布、阈值贴近度、账户历史基线统计） |
| `numpy` | >=1.24 | 基线 z-score 计算；数据集分层抽样与补全数据生成的确定性随机源（`default_rng(seed)`） |
| `networkx` | >=3.0 | 资金链路图构建与关联方扩展（一度 / 二度对手方） |
| `PyYAML` | >=6.0 | 监管规则库 YAML 定义加载 |
| `rapidfuzz` | >=3.0 | 名单筛查模糊匹配（制裁名单的别名 / 音译 / 简繁差异） |
| `jsonschema` | >=4.0 | 研判报告结构校验（强制 evidence_refs / rule_refs 非空） |
| `tenacity` | >=8.0 | API 调用指数退避重试 |
| `sqlite3` | stdlib | 交易数据集与长期记忆存储 |
| `pytest` | >=7.0 | 测试框架 |

### 为什么选 LangGraph 而非 LangChain AgentExecutor

LangGraph 的 StateGraph 完全匹配 Plan-and-Execute 结构：

- 调查计划状态（plan: list[InvestigationStep]）就是图的一等公民 State 字段，Planner 对它的增删改天然可追踪，也天然满足审查留痕要求
- 父图（Planner 循环）+ 子图（Executor / Verifier 单步闭环）的嵌套结构直接表达多 Agent 协作；同一套子图工厂换 prompt 与工具面即得到 Verifier
- 条件边表达「重试 / 重规划 / 校验 / 完成」的路由，比手写 while 循环清晰可控
- 内置 Checkpointer 直接解决会话内状态持久化（短期记忆的载体），也支持调查中断后恢复
- 可视化状态图便于调试和面试展示

LangChain AgentExecutor 的局限：单 Agent ReAct 循环，无法表达显式计划状态、双层循环结构，也无法把校验拆成独立 Agent。

### 为什么工具层用 MCP 而非普通函数

- **复用性**：交易调单、名单筛查、监管规则检索是通用合规能力，封装为 MCP Server 后，Claude Desktop、Cursor 等任意 MCP 客户端可直接复用，不与本项目耦合
- **边界清晰**：Agent 编排层（决策）与工具层（数据能力）通过标准协议隔离，工具可独立测试、独立演进；接入真实核心系统时只需替换 MCP Server 实现，编排层零改动
- **安全与合规收口**：所有交易数据访问必须经过 MCP Server，查询范围限制、返回条数上限、敏感字段脱敏、访问审计日志在协议边界统一实施——金融场景下这是硬性要求，散落在各处的直连查询无法审计

### 为什么保留规则引擎而不是全部交给 LLM

监管合规判断中有相当一部分是确定性阈值计算（例：单笔或当日累计现金交易达到规定金额需报告），这类判断有三个特点：结果必须可复现、依据必须可引用条款、错误代价高。LLM 做数值比较与多条件组合判断存在不稳定性，且无法给出可审计的计算过程。

因此两路分工：

- **规则引擎**负责可形式化的部分——阈值、频次、时间窗、名单命中，输出 `{rule_id, 命中字段, 条款引用}`，结果确定且可复算
- **LLM** 负责规则覆盖不到的情境判断——资金来源解释是否合理、交易背景与客户经营范围是否匹配、多个弱信号是否构成整体可疑

两路结论一致则直接出报告；不一致则标记 `needs_human_review`，把分歧点连同双方依据一并呈给人工。这条设计让系统在不确定时选择降级而不是猜测。

---

## 4. 测试与评估方案

### 测试层次

```
tests/
├── unit/
│   ├── test_plan.py                 # 计划增删改、重规划 patch 应用
│   ├── test_agent.py                # Planner 生成 / 重规划 / 不可解析输出降级、route_plan
│   ├── test_executor.py             # reason_node 解析、幻觉工具名与参数错误回写 observation
│   ├── test_text_processors.py      # extract_tagged_json 抽取与异常
│   ├── test_config.py               # 配置三优先级加载、环境变量映射、--show-config
│   ├── test_rule_engine.py          # 规则加载、阈值/频次/时间窗判定、条款引用输出
│   ├── test_baseline.py             # 基线计算、z-score、样本不足时跳过规则
│   ├── test_audit_chain.py          # 哈希链构造、篡改/插入/删除被检出并定位
│   ├── test_report.py               # 报告 Schema 校验：无 evidence_refs 的结论被拒
│   ├── test_history_manager.py      # 阈值触发摘要、轮数边界条件
│   ├── test_memory_manager.py       # 长期记忆 CRUD + 检索 + 蒸馏结果入库
│   └── test_data_guard.py           # 受控访问：条数上限、超时、字段脱敏
├── integration/
│   ├── test_agent_loop.py           # Mock LLM，跑完整 Plan-and-Execute 循环
│   ├── test_replan.py               # 连续失败触发重规划、重规划次数上限
│   ├── test_verifier.py             # Verifier 空白上下文、只读约束、裁决路由
│   ├── test_compliance.py           # 双路一致 / 不一致（needs_human_review）两条路径
│   └── test_mcp_server.py           # MCP 工具经 stdio 端到端调用
└── e2e/
    └── test_case_investigation.py   # 端到端：跑通一条标注案件并产出报告
```

### 测试约定

- 单元测试 Mock 所有外部依赖（LLM API / 数据库），不调用真实 API；除模型 API 外系统本身无网络依赖
- 交易数据与长期记忆测试使用内存 SQLite（`:memory:`）
- 数据集相关测试断言可复现性：同一 seed 对同一原始数据 fixture 两次构建的规范化校验和一致；原始文件 SHA256 不符时拒绝构建
- 集成测试对五条路由（正常执行 / 重试 / 重规划 / 校验裁决 / 双路合规分歧）各建完整用例；Verifier 用例需断言其上下文不含调查过程历史
- 评测数据仅使用公开反洗钱数据集（匿名化模拟数据）及其固定 seed 补全数据，不得包含真实客户信息

### 端到端评估（Benchmark）

- **测试集**：`eval/benchmark.jsonl`，约 200 条标注案件，由 `data/build_dataset.py` 基于**公开反洗钱数据集**（首选 SAML-D，见子任务 2.2）以**固定 seed** 分层抽样构建，覆盖典型可疑模式：结构化拆分、高频跨境、快进快出（pass-through）、集中收付、名单关联、行为突变，并保留一定比例的正常样本（含活跃大额但合理的账户）用于检验误报。案件标签由原始数据集的交易级洗钱标签按固定口径聚合得到，名单关联等补全样本由构建脚本打标，标注不依赖人工
- **可复现性**：同一 seed + 同一版本原始文件（SHA256 记录在 `data/seed.json`）重建出的案件集与数据库规范化校验和一致；`python data/build_dataset.py --seed <seed> --verify` 重建并比对，任何人下载同一原始数据后跑出的 benchmark 数字应与本文档一致。评测过程不访问外部网络，唯一的不确定性来源是 LLM 采样——评测时统一 `temperature=0` 并在报告中记录模型版本
- **主指标**：端到端调查准确率——研判结论（上报 / 不上报 / 需人工复核）与标注一致，**且**报告中每条结论的证据引用可回溯；原始标签为二分类（上报 / 不上报），`needs_human_review` 不计为命中、占比单独报告；当前结果约 **75%**
- **辅助指标**：误报率（正常样本被判上报）、漏报率（可疑样本被判不上报）、平均调查步骤数、平均 token 消耗
- **失败归因四分类**：评估脚本按 `attribute_failure()` 结果统计，指导后续优化方向
  - `planning`：计划本身缺失关键取证步骤，或调查方向错误
  - `tool`：工具调用参数错误、查询范围不当、结果解析失败
  - `verification`：Verifier 漏判——证据不足的结论被放行，或有效结论被误拒
  - `hallucination`：报告中出现无证据支撑的事实陈述或不存在的规则引用
- **运行**：`python eval/run_eval.py --benchmark eval/benchmark.jsonl --report eval/report.md`

### 验收标准

| 层次 | 覆盖率目标 | 说明 |
|------|-----------|------|
| Unit | >80% | 计划操作、规则引擎、报告校验、记忆、受控访问全覆盖 |
| Integration | 关键路径 | 正常执行 / 重试 / 重规划 / 校验裁决 / 双路分歧五条路由各有完整测试用例 |
| E2E | Benchmark | 约 200 条标注测试集端到端准确率 >=75%，且幻觉输出类失败占比 <5% |
| 可复现 | 校验和一致 | 同一 seed + 同一原始文件重建数据集校验和不变；同一次评测重跑结论一致 |

### 运行命令

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v --timeout=30
pytest tests/ --cov=core --cov=mcp_server --cov=utils --cov-report=term-missing
python data/build_dataset.py --seed 20260115 --verify
python eval/run_eval.py --benchmark eval/benchmark.jsonl
python main.py --verify-audit logs/audit_xxx.jsonl
```

---

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
│   ├── build_dataset.py             # [NEW] 公开数据集分层抽样 + 固定 seed 补全 + 写库
│   ├── seed.json                    # [NEW] seed、原始数据集版本与 SHA256、汇率与抽样配额
│   ├── raw/                         # 公开数据集原始文件（手动下载，不提交 git）
│   ├── aml_dataset.sqlite           # [NEW] 构建结果（许可证允许时提交，否则由 raw + seed 重建）
│   └── DATASET.md                   # [NEW] 数据来源与许可证、字段映射、typology 对照、校验和
│
├── utils/
│   ├── __init__.py
│   ├── deepseek.py                  # Deepseek API 封装（streaming + retry）
│   ├── qwen.py                      # Qwen API 封装（摘要 / 蒸馏 / 相关性判断）
│   └── text_processors.py           # LLM 输出结构化块抽取（extract_tagged_json）
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
| `data/build_dataset.py` | 校验公开数据集原始文件 -> 按 typology 分层抽样案件 -> 截取案件子图与基线历史 -> 固定 seed 补全档案 / 名单 / 负面信息 / 预警 -> 写库并输出带标签的 benchmark | `build(seed)`, `sample_cases()`, `synthesize_enrichment()` |
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

## 6. 项目排期

### 阶段划分

```
Phase 0 (完成) -> Phase 1 (完成) -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6
基础功能          Plan-and-Execute   领域建模   MCP Server  规则引擎   双记忆 +   测试 +
                  编排骨架           + 公开     模块化      + 双路合规  哈希链     Evals
                  [领域无关]         数据集                             审查留痕
                                     + 固定 seed
                                     [P0]       [P0]        [P0]       [P0]      [P1]
```

---

### Phase 1：Plan-and-Execute 多 Agent 骨架（已完成）

**目标**：用 LangGraph 父图（Planner）+ 子图（Executor / Verifier）替代单循环，引入显式计划状态、动态重规划与独立校验

**说明**：本阶段产出的是**领域无关的编排骨架**——计划状态机、三 Agent 分工、四条路由。开发期以软件安装任务作为验证载体，因此当前代码中的 `goal` / `system_info` / `install` 等命名仍带安装语义，领域语义（案件、证据链、规则引用）在 Phase 2 落地。骨架本身无需重写。

#### 子任务 1.1：计划状态与操作

- **修改文件**：`core/plan.py`（新建）
- **实现**：`PlanStep(TypedDict)` / `AgentState(TypedDict)`；`apply_plan_patch(plan, patch) -> plan` 应用 Planner 输出的增/删/改操作
- **验收标准**：patch 操作不可变、越界 id 报错；`pytest tests/unit/test_plan.py`

#### 子任务 1.2：Planner 节点与重规划

- **修改文件**：`core/agent.py`（新建）, `prompt/prompt.py`
- **实现**：`plan_node()` 首次生成完整计划、重入时依据失败反馈输出 plan patch；`route_plan()` 路由 execute / verify / abort
- **验收标准**：Mock LLM 返回固定 patch，验证计划状态正确演进

#### 子任务 1.3：Executor 子图（单步执行闭环）

- **修改文件**：`core/executor.py`（新建）
- **实现**：`reason_node()` CoT 推理 + Tool Call；`route_step_result()` 四态路由；步骤间清空 `executor_messages` 防止上下文污染
- **验收标准**：正常 / 重试 / 重规划三条路由各有集成测试

#### 子任务 1.4：Verifier Agent（复用子图）

- **修改文件**：`core/agent.py`, `prompt/prompt.py`
- **实现**：`build_verifier()` 调用 `build_executor(prompt=prompt_verify, tools=只读, fresh_context=True)`；`prompt_verify` 对抗性立场；输出 `{passed, evidence, failure_reason}`
- **验收标准**：空白上下文不泄露执行历史；证据不足场景被判 failed 并路由回 planner

#### 子任务 1.5：接口兼容

- **修改文件**：`core/installer.py`
- **实现**：对外方法内部改为调用 `build_graph().invoke()`，保持 `main.py` 接口不变
- **验收标准**：CLI 全链路可跑通

**进度追踪**：
- [x] 1.1 计划状态与操作 — 新增 core/plan.py（PlanStep/AgentState 定义 + apply_plan_patch 增删改操作），9 个单测覆盖
- [x] 1.2 Planner 节点与重规划 — 新增 core/agent.py（build_planner 工厂 + plan_node 首次规划/重规划 + route_plan 路由）；改造 prompt_plan 输出为结构化 JSON，新增 prompt_replan；7 个单测（Mock LLM）覆盖
- [x] 1.3 Executor 子图 — 新增 core/executor.py（build_executor 工厂 + reason_node CoT推理/工具调用 + route_tool + route_step_result 三路由）与 prompt_execute；6 单测 + 3 集成测试（正常/重试/重规划）覆盖，均用 Mock LLM + Mock 工具
- [x] 1.4 Verifier Agent — core/agent.py 新增 build_verifier（复用 build_executor，prompt_verify + 只读工具 + 空白上下文）+ route_verify；prompt/prompt.py 新增 prompt_verify（对抗性校验立场）；3 个集成测试覆盖通过/证据不足判失败/空白上下文不泄露执行历史
- [x] 1.5 接口兼容 — core/agent.py 新增 build_graph（组装 planner/executor/verifier/memorize 全图）+ memorize_node（空实现桩，Phase 5 落地）；对外接口改为调用 build_graph().invoke()；过程中发现并修复两处路由缺口：route_step_result 补充区分 "pending"（推进到下一步）/"done"（all_done 交还 planner）两态，plan_node 补充 _needs_replan 判断避免每次重入误判为需要重规划；12 个新测试（含全链路 mock 集成测试 test_agent_loop.py 和接线测试）覆盖

---

### Phase 2：领域建模重构（预计 2 天）

**目标**：把领域无关骨架迁移到 AML 调查语义，建立案件模型、证据链，接入公开反洗钱数据集并以固定 seed 保证可复现

#### 子任务 2.0：安装场景遗留代码清理与骨架加固

**背景**：Phase 1 以软件安装任务为验证载体，骨架外围遗留了一批与 AML 场景冲突、且不在 2.1-6.3 任何子任务范围内的代码：LLM 生成命令经 `shell=True` 直接执行（与「全本地数据源 + 受控访问」原则冲突）、Kimi 联网搜索、主机信息采集；同时暴露出若干领域无关的骨架缺陷。本任务先清场，后续子任务在干净的基础上做领域化。`DeployBot` 更名、prompt 改写、CLI 改为 `--case`、emoji 清理仍归 2.3，本任务不做。

- **修改文件**：`utils/kimi_search.py`（删除）, `utils/get_system_summary.py`（删除）, `utils/text_processors.py`, `utils/__init__.py`, `utils/deepseek.py`, `utils/qwen.py`, `core/installer.py`, `core/agent.py`, `core/executor.py`, `config/enhanced_config.py`, `main.py`, `requirements.txt`, `CLAUDE.md`
- **实现**：
  - 删除遗留能力：
    - `utils/kimi_search.py`，以及配置、CLI 交互配置、校验告警中全部 `kimi_api_key` / `KIMI_API_KEY`
    - `utils/get_system_summary.py`（psutil / GPUtil 主机信息采集，仅服务安装场景）；`installer` 中 `system_info` 暂置空字符串，2.1 由 `case_context` 取代
    - `installer` 的 `run_shell`（`subprocess` + `shell=True`）与 `web_search` 工具；Phase 3 接入 MCP 之前 Executor / Verifier 工具集为空 dict，Verifier 不再与 Executor 共享同一个可写工具集对象
    - `enhanced_config` 的 legacy 加载（`src.config.config`）与 `main.py` 中对不存在的 `src/` 目录的 `sys.path` 注入
    - `text_processors` 中安装语义的抽取函数（搜索词 / Python 代码 / shell 命令 / 安装计划 / 完成标记 / 版本号等）
  - 收拢重复代码：`core/agent.py` 与 `core/executor.py` 各有一份 `_extract_json_block`，合并为 `utils/text_processors.extract_tagged_json(text, tag)`
  - 骨架加固（领域无关缺陷，接入 MCP 后同样需要）：
    - `executor_node`：LLM 调用不存在的工具名或参数不匹配时，不再抛 `KeyError` / `TypeError` 中断整图，而是把错误作为 observation 写回本步消息，由 LLM 在下一轮自行修正（仍受 `max_tool_iterations` 约束）
    - `executor_node`：LLM 输出无法解析（缺标签 / 非法 JSON）时本步记为 `failed`，`result_summary` 写明解析失败原因，走既有 retry / replan 路由
    - `plan_node`：Planner 输出无法解析时不抛异常，把原因写入 `verdict.failure_reason`，首次规划失败则计划保持为空、经 `route_plan` 走 `abort`；重规划失败则计划不变、`replan_count` 仍 +1
  - 模型客户端对齐第 3 节：`Deepseek(api_key, model)` 支持指定模型（Planner 用 `deepseek-reasoner`，Executor / Verifier 用 `deepseek-chat`），非 reasoner 模型无 `reasoning_content` 时返回 `None`；`QueryTongyi(api_key)` 通过调用参数传 key，去掉模块级 `dashscope.api_key_file_path` 全局副作用
  - 配置对齐第 5 节示例：`AIModelConfig` 改为 `deepseek_api_key` / `qwen_api_key`（环境变量 `DEEPSEEK_API_KEY` / `DASHSCOPE_API_KEY`）；`installation` 段改为 `investigation`（`max_investigation_steps` / `max_step_retries` / `max_replans` / `tool_timeout_seconds`），删除 `enable_code_execution` / `enable_web_search` / `search_timeout_seconds`；修复 `print_config_summary` 引用未定义字段 `qwen_api_key_file` 导致 `--show-config` 崩溃
  - `requirements.txt` 只列当前代码实际 import 的依赖（补上缺失的 `langgraph`，移除 `psutil` / `GPUtil` / `socksio` / 旧 Python 兼容包），后续 Phase 引入新库时同步追加
  - `CLAUDE.md` 密钥环境变量改为 `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`
- **验收标准**：
  - `core/ utils/ config/ main.py requirements.txt CLAUDE.md` 中无 `kimi` 字样；代码中无 `subprocess` / `shell=True`
  - `DEEPSEEK_API_KEY=dummy python main.py --show-config` 正常输出不崩溃
  - 幻觉工具名 / 参数不匹配 / Executor 输出不可解析 / Planner 输出不可解析四种场景下图不抛异常，按预期进入修正、retry、replan 或 abort
  - 既有 34 个测试全部通过（安装语义的测试数据保留，2.1 / 2.3 随状态字段一并迁移）
- **测试方法**：`pytest tests/unit/test_executor.py tests/unit/test_agent.py tests/unit/test_text_processors.py tests/unit/test_config.py tests/integration/`

#### 子任务 2.1：状态与数据结构领域化

- **修改文件**：`core/plan.py`, `core/evidence.py`（新建）
- **实现**：
  - `PlanStep` 更名 `InvestigationStep`（字段不变，保留旧别名一版以便平滑迁移）
  - `AgentState`：`goal` -> `case: dict`，`system_info` -> `case_context: str`；新增 `evidence` / `rule_hits` / `report` 三个字段
  - `core/evidence.py`：`append_evidence(state, tool, args, result)` 分配 `E-XXX` id 并写入证据链；`resolve_refs(evidence, refs)` 解析引用；`check_closure(report, evidence)` 校验引用闭合
- **验收标准**：证据 id 单调递增不重复；引用不存在的 id 时 `check_closure` 返回失败明细
- **测试方法**：`pytest tests/unit/test_plan.py tests/unit/test_evidence.py`

#### 子任务 2.2：公开数据集接入与固定 seed 复现

- **修改文件**：`data/schema.sql`, `data/build_dataset.py`, `data/seed.json`, `data/DATASET.md`（均新建）, `.gitignore`
- **数据来源分层**：
  - **交易流水与洗钱标签——公开反洗钱数据集**：首选 SAML-D（Oztas et al., 2023；约 950 万笔交易，交易级 `Is_laundering` / `Laundering_type` 标签，11 类正常 + 17 类可疑 typology，覆盖结构化拆分、Smurfing、跨境高风险地区、行为突变等；时间跨度近一年，可支撑 180 天基线回溯）；备选 IBM AMLworld（Altman et al., NeurIPS 2023 Datasets and Benchmarks；typology 以 fan-in / fan-out / cycle / scatter-gather 等资金图模式为主，采用前需确认时间跨度能否覆盖 180 天基线窗口）。两者都是模拟器生成并已匿名化——真实银行 AML 数据无法公开，这是公开评测的通行做法。字段、时间跨度与许可证以数据集官方页面为准，落地时核对并写入 `DATASET.md`
  - **公开数据集不提供的部分——固定 seed 补全**：客户 KYC 档案、制裁 / PEP 名单、负面信息语料、预警线索。补全与抽中账户的标签对齐，例如为部分可疑账户的对手方生成带别名 / 音译 / 简繁变体的名单条目（名单关联样本），同时为正常账户生成近似名干扰项（考察名单误报）
- **实现**：
  - SQLite 表：`transactions`（流水）/ `accounts`（账户档案）/ `watchlist`（名单）/ `adverse_media`（负面信息语料）/ `alerts`（预警线索）
  - 原始文件手动下载到 `data/raw/`（加入 `.gitignore`）；`seed.json` 记录 seed、数据集名称与版本、原始文件 SHA256、币种折算汇率、各 typology 抽样配额；构建前先校验原始文件 SHA256，不符直接拒绝构建
  - `build_dataset.py --seed <n>`：单一 seed 驱动全部随机源（`random.Random(seed)` + `numpy.random.default_rng(seed)`，不使用全局随机状态）；每次抽样前按主键稳定排序，不依赖文件行序、dict 顺序或并行执行顺序，保证跨机器一致。流程：
    1. 按 typology 分层抽样约 200 个案件主体账户（可疑 / 正常按配额，正常样本中保证一定比例的活跃大额账户）
    2. 截取案件子图：主体账户 + 二度内对手方 + 案件窗口前 180 天历史流水，控制入库体积
    3. 固定 seed 补全档案 / 名单 / 负面信息 / 预警线索
    4. 金额按 `seed.json` 中的固定汇率折算为人民币，使 PBOC 阈值规则可直接适用；原币种与原金额保留在独立字段
  - Ground truth：案件级标签由交易级标签聚合——主体账户在案件窗口内参与任一 `Is_laundering=1` 交易即为「应上报」，否则为「不上报」；`Laundering_type` 作为可疑模式标注保留；补全引入的名单关联样本由构建脚本打标；聚合口径写入 `DATASET.md`
  - 基线偏离规则的两类样本保证配额：金额相对自身历史暴增但绝对值不触阈值的可疑账户（优先取行为突变类 typology，考察漏报）、绝对流水大但符合自身历史的正常账户（考察误报）
  - 构建产物 `aml_dataset.sqlite` 与 `eval/benchmark.jsonl`：许可证允许再分发时两者**提交进仓库**；不允许时只提交 `seed.json` 与 `benchmark.jsonl`（仅含原始交易 id、账户 id 与标签），使用者下载原始数据后一条命令重建。`DATASET.md` 记录来源、许可证与再分发结论、字段映射、typology 与本项目可疑模式对照表、产物校验和
  - 校验和基于按主键排序导出的规范化内容计算，而非 SQLite 文件字节（不同 SQLite 版本的页布局可能不同）
  - 交易表建 `(account, timestamp)` 与 `(counterparty)` 索引，保证 90 天窗口调单与 180 天基线计算响应在秒级
  - `--verify` 模式：从原始文件 + seed 重建到临时库，与 `DATASET.md` 记录的校验和比对
- **验收标准**：原始文件 SHA256 不符时拒绝构建；同一 seed 两次构建校验和一致；`--verify` 通过；抽样案件的 ground truth 可逐条回查到原始交易标签；许可证与再分发结论已写入 `DATASET.md`
- **测试方法**：`pytest tests/unit/test_data_layer.py`（用仓库内几百行、与原始文件同格式的 fixture 替代完整数据集，断言构建确定性与标签聚合口径）

#### 子任务 2.3：Prompt 与对外接口领域化

- **修改文件**：`prompt/prompt.py`, `core/investigator.py`（由 `installer.py` 更名）, `main.py`
- **实现**：
  - `prompt_plan` / `prompt_replan` / `prompt_execute` / `prompt_verify` 全部改写为调查语义；`prompt_verify` 的对抗性立场改为「逐条结论要求出示证据引用」
  - `DeployBot` -> `AMLGuard`，`install_software()` -> `investigate(alert_id)`
  - CLI：`--install` -> `--case`，新增 `--replay`
  - 清理输出中的 emoji（CLAUDE.md 规范）
- **验收标准**：`python main.py --case <alert_id>` 端到端跑通并产出计划与取证记录
- **测试方法**：`pytest tests/integration/test_agent_loop.py`（Mock LLM，断言使用新状态字段）

**进度追踪**：
- [x] 2.0 安装场景遗留代码清理与骨架加固 — 删除 utils/kimi_search.py、utils/get_system_summary.py 与 installer 的 run_shell（shell=True）/ web_search 工具，Executor / Verifier 改为两个独立空工具集；agent.py 与 executor.py 重复的 _extract_json_block 收拢为 utils/text_processors.extract_tagged_json（删除安装语义抽取函数）；executor 新增 invoke_tool，幻觉工具名 / 参数不匹配回写 observation，输出不可解析判本步 failed 走 retry；plan_node 首次规划不可解析保持空计划经 route_plan abort，重规划输出非法则计划不变且计入 replan_count；Deepseek 支持 model 参数（Planner reasoner / Executor chat），QueryTongyi 按调用传 key 去掉模块级全局副作用；配置 kimi_api_key -> qwen_api_key（DASHSCOPE_API_KEY）、installation -> investigation，删除 legacy 加载与 src/ 路径注入，修复 --show-config 因 qwen_api_key_file 未定义而崩溃；requirements 补 langgraph，移除 psutil / GPUtil / socksio；CLAUDE.md 环境变量同步；新增 test_text_processors.py / test_config.py 并扩充 executor / agent / agent_loop / wiring 用例，测试 34 -> 62 全部通过
- [ ] 2.1 状态与数据结构领域化
- [ ] 2.2 公开数据集接入与固定 seed 复现
- [ ] 2.3 Prompt 与对外接口领域化

---

### Phase 3：MCP Server 模块化（预计 3 天）

**目标**：调单 / 档案 / 规则检索 / 名单筛查 / 负面信息封装为标准 MCP Server，数据访问在协议边界收口

#### 子任务 3.1：受控访问层

- **修改文件**：`mcp_server/guard.py`（新建）
- **实现**：`guarded()` 装饰器统一施加返回条数上限、查询时间窗上限、超时控制；`mask_sensitive()` 对证件号 / 手机号 / 地址做脱敏后再返回给 LLM；每次访问写入审计日志
- **验收标准**：超限查询被截断并显式提示；脱敏字段不出现在返回内容中
- **测试方法**：`pytest tests/unit/test_data_guard.py`

#### 子任务 3.2：MCP 工具实现

- **修改文件**：`mcp_server/server.py`, `transactions.py`, `profile.py`, `regulations.py`, `watchlist.py`, `adverse_media.py`（均新建）
- **实现**：
  - FastMCP 注册工具：`query_transactions(account, window_days, filters)`、`query_account_profile(account)`、`search_regulations(query)`、`screen_watchlist(name, id_no)`、`search_adverse_media(entity)`、`expand_counterparties(account, depth)`
  - `query_transactions` 返回**聚合摘要 + 明细引用 id**，不把上千条原始流水灌进上下文
  - `screen_watchlist` 用 rapidfuzz 做别名 / 音译 / 简繁模糊匹配，返回相似度与匹配依据字段
  - `search_adverse_media` 检索仓库内合成负面信息语料表（实体名模糊匹配 + 关键词），返回命中条目与出处，全程不联网
  - `expand_counterparties` 用 networkx 构图，depth<=2 上限保护
- **验收标准**：`mcp dev mcp_server/server.py` 可交互调用全部工具；Claude Desktop 挂载可用
- **测试方法**：`pytest tests/integration/test_mcp_server.py`

#### 子任务 3.3：Agent 侧接入

- **修改文件**：`core/executor.py`, `core/agent.py`, `core/investigator.py`
- **实现**：`langchain-mcp-adapters` 经 stdio 加载 MCP 工具绑定到 Executor；Verifier 只绑定只读子集；工具返回自动追加进 `evidence`
- **验收标准**：完整调查流程中所有数据访问均经 MCP 协议完成，`evidence` 与工具调用一一对应

**进度追踪**：
- [ ] 3.1 受控访问层
- [ ] 3.2 MCP 工具实现
- [ ] 3.3 Agent 侧接入

---

### Phase 4：规则引擎与双路合规校验（预计 3 天）

**目标**：确定性规则判定与 LLM 研判并行，产出附规则引用与证据引用的结构化报告

#### 子任务 4.1：规则引擎

- **修改文件**：`core/rule_engine.py`, `rules/pboc.yaml`, `rules/fatf.yaml`（均新建）
- **实现**：
  - YAML 规则加载与 schema 校验（缺 citation 的规则拒绝加载）
  - 绝对指标层：`near_threshold_count` / `near_threshold_ratio` / `cross_border_count` / `pass_through_ratio` / `counterparty_concentration` 等，用 pandas 在交易集上计算
  - 基线偏离指标层：`compute_baseline(account, lookback_days)` 先算账户自身历史统计（金额均值/标准差、笔数均值/标准差、对手方集合），再产出 `deviation_from_baseline.amount_sum`（倍数）、`.txn_count_zscore`、`.new_counterparty_ratio`；基线样本数 < `min_observations` 时该规则跳过并在证据中记录跳过原因
  - `evaluate(case, evidence) -> rule_hits`，命中项保留实际计算值与基线统计供报告展示
  - 首批落地 10-15 条规则，覆盖主要可疑模式，其中至少 3 条使用基线偏离指标
- **验收标准**：构造边界样本（恰好达阈值 / 差一笔）判定正确；基线样本不足的新开户不被判为无穷倍偏离；活跃大额但符合自身历史的账户不命中基线规则；每条命中都带 citation
- **测试方法**：`pytest tests/unit/test_rule_engine.py tests/unit/test_baseline.py`

#### 子任务 4.2：规则引擎作为 MCP 工具

- **修改文件**：`mcp_server/server.py`
- **实现**：注册 `run_rule_engine(account, window_days)`，让 Executor 在取证途中即可获得规则命中作为证据
- **验收标准**：Executor 调用后 `rule_hits` 与 `evidence` 同步写入

#### 子任务 4.3：compliance_node 与报告生成

- **修改文件**：`core/agent.py`, `core/report.py`, `rules/report.schema.json`, `prompt/prompt.py`
- **实现**：
  - `compliance_node()`：规则路全量复跑 + LLM 路（`prompt_judge`）情境研判，两路结论比对
  - 一致 -> 输出结论；不一致 -> `conclusion=needs_human_review`，`divergence` 记录双方结论与依据
  - `build_report()` 组装 findings（每条含 `evidence_refs` / `rule_refs`），`validate_report()` 经 JSON Schema 校验，失败则归因 `hallucination`
  - `render_markdown()` 输出人类可读研判报告
  - 图接线：`verifier --success--> compliance --> memorize`
- **验收标准**：Mock 双路一致场景出报告；Mock 不一致场景产出 needs_human_review 且 divergence 完整；构造缺失 evidence_refs 的 finding 被 Schema 拒绝
- **测试方法**：`pytest tests/integration/test_compliance.py tests/unit/test_report.py`

**进度追踪**：
- [ ] 4.1 规则引擎
- [ ] 4.2 规则引擎作为 MCP 工具
- [ ] 4.3 compliance_node 与报告生成

---

### Phase 5：双层记忆与审查留痕（预计 3 天）

**目标**：短期阈值摘要 + 长期调查路径蒸馏；JSONL 审查轨迹 + 失败归因 + 回放

#### 子任务 5.1：长期记忆与路径蒸馏

- **修改文件**：`core/memory_manager.py`（新建）, `prompt/prompt.py`
- **实现**：
  - `MemoryManager` — SQLite 建表 / CRUD，表结构见第 5 节
  - `distill_investigation_path(trace)` — 调用 Qwen，输入完整轨迹，输出剔除试错分支后的有效取证序列
  - `retrieve_relevant(alert_type, case_features)` — 按预警类型检索 + Qwen 相关性过滤
  - 接入 `memorize_node`，替换 Phase 1 的空实现桩
- **验收标准**：同类案件调查两次，第二次命中记忆且步骤数明显减少（目标降幅 >=30%）；蒸馏结果不含失败分支
- **测试方法**：`pytest tests/unit/test_memory_manager.py`（内存 SQLite `:memory:`）

#### 子任务 5.2：短期记忆接入

- **修改文件**：`core/history_manager.py`, `core/executor.py`
- **实现**：Executor 消息超 6 轮触发 Qwen 摘要，保留最近 2 轮完整记录；明确 `evidence` 不参与压缩
- **验收标准**：长调查（>10 步、含大对手方展开）不触发 token 超限，且报告引用仍可全部解析

#### 子任务 5.3：哈希链审查日志与回放

- **修改文件**：`core/logger.py`, `main.py`
- **实现**：
  - `AuditLogger.log_step(step_type, content)` — 逐事件追加写 JSONL，写入 `seq` / `timestamp` / `prev_hash` / `entry_hash`；数据访问事件记录访问对象与范围
  - 哈希链：`entry_hash = sha256(canonical_json({seq, step_type, content, timestamp, prev_hash}))`，`canonical_json` 用 `sort_keys=True` + 紧凑分隔符保证跨机器一致；首条 `prev_hash = sha256(case_id + ruleset_version)`
  - `AuditLogger.verify_chain(path) -> {ok, broken_at_seq, expected, actual}` — 逐条重算比对
  - 报告落盘时把链尾 `entry_hash` 写入报告尾部作为锚点
  - `main.py --replay <audit.jsonl>` — 按时间序回放调查轨迹
  - `main.py --verify-audit <audit.jsonl>` — 校验完整性，断裂时打印首个失配条目及上下文
- **验收标准**：任一次调查的轨迹可完整回放；对轨迹做改字段 / 插入一行 / 删除一行三种篡改，`verify_chain` 均检出且 `broken_at_seq` 定位到首个受影响条目；失败案例报告中含归因类别
- **测试方法**：`pytest tests/unit/test_audit_chain.py`

**进度追踪**：
- [ ] 5.1 长期记忆与路径蒸馏
- [ ] 5.2 短期记忆接入
- [ ] 5.3 哈希链审查日志与回放

---

### Phase 6：测试 + Evals 评测体系 + 工程打磨（预计 3 天）

**目标**：覆盖核心路径，建立约 200 条标注 benchmark，全量 Type Hints

#### 子任务 6.1：单元 + 集成测试补全

- **覆盖内容**：见第 4 节测试层次
- **验收标准**：`pytest tests/ --cov` 覆盖率 >70%，Mock 不调用真实 API

#### 子任务 6.2：Evals 评测体系

- **修改文件**：`eval/benchmark.jsonl`, `eval/run_eval.py`（新建）
- **实现**：
  - 使用 2.2 基于公开反洗钱数据集构建的约 200 条标注案件（固定 seed 分层抽样，标签由原始交易级标签聚合），按可疑模式（拆分 / 高频跨境 / 快进快出 / 集中收付 / 名单关联 / 行为突变）分层统计，含正常样本对照
  - 评测报告头部记录 seed、原始数据集版本与 SHA256、模型版本与 `temperature=0`，保证数字可复算
  - 批量运行，统计端到端准确率、误报率、漏报率、平均步骤数，以及四类失败归因分布，输出 Markdown 报告
- **验收标准**：端到端准确率 >=75%，报告含四类失败分布与典型案例

#### 子任务 6.3：Type Hints + Retry + 安全审查

- **实现**：
  - 所有公共函数完整 Type Hints
  - `tenacity.retry`：`wait_exponential(min=1, max=10)`, `stop_after_attempt(3)`，仅重试网络/超时异常
  - 部署前安全审查：确认无硬编码密钥、日志不落敏感明文、SQL 全部参数化
- **验收标准**：`mypy core/ mcp_server/ utils/ --ignore-missing-imports` 无 error；安全审查项逐条通过

**进度追踪**：
- [ ] 6.1 单元 + 集成测试补全
- [ ] 6.2 Evals 评测体系
- [ ] 6.3 Type Hints + Retry + 安全审查

---

### 改进优先级总览

| 优先级 | 改进点 | 涉及文件 | Phase |
|--------|--------|----------|-------|
| P0 | 安装场景遗留代码清理（shell 执行 / Kimi / 主机采集）+ 骨架异常加固 | `utils/`, `core/executor.py`, `core/agent.py`, `config/` | 2 |
| P0 | 领域建模重构（案件 / 证据链 / prompt / 接口） | `core/plan.py`, `core/evidence.py`, `prompt/`, `core/investigator.py` | 2 |
| P0 | 公开反洗钱数据集接入 + 固定 seed 抽样与补全（保证评测可复现） | `data/` | 2 |
| P0 | MCP Server 模块化（调单/档案/规则/名单/负面信息） | `mcp_server/` | 3 |
| P0 | 受控数据访问（条数上限/脱敏/审计） | `mcp_server/guard.py` | 3 |
| P0 | 规则引擎（绝对阈值 + 账户基线偏离）+ 条款引用 | `core/rule_engine.py`, `rules/` | 4 |
| P0 | 双路合规校验 + 结构化报告 | `core/agent.py`, `core/report.py` | 4 |
| P0 | 长期记忆 + 调查路径蒸馏 | `core/memory_manager.py` | 5 |
| P0 | 哈希链审查日志 + 完整性校验 + 失败归因 + 回放 | `core/logger.py`, `main.py` | 5 |
| P0 | 约 200 条标注 Benchmark 评测 | `eval/` | 6 |
| P1 | 短期记忆阈值摘要正式接入 | `core/history_manager.py` | 5 |
| P1 | 全量 Type Hints + tenacity 重试 + 安全审查 | `core/`, `mcp_server/`, `utils/` | 6 |
| P1 | Streaming 输出 | `utils/deepseek.py` | 6 |
| P2 | 未来规划项 | 见第 7 节 | 后续 |

---

## 7. 未来规划

以下为 Phase 6 之后的候选方向（P2 优先级），评估范围或扩展功能时参考：

### 7.1 提升端到端准确率（75% -> 85%+）

- 基于四类失败归因定向优化：planning 类补充按预警类型的调查模板；tool 类加强查询参数约束与结果解析容错；hallucination 类收紧报告 Schema 与引用校验
- 对弱信号组合场景引入多轮自省（结论生成后强制反向论证一轮）
- 涉及：全局，以 `eval/report.md` 归因数据驱动

### 7.2 向量检索长期记忆

- 当前按预警类型检索 + LLM 相关性过滤在记录量大时召回不足
- 引入 embedding 检索（案件特征向量化），SQLite 侧可用 sqlite-vec
- 涉及：`core/memory_manager.py`

### 7.3 基线建模演进

- 当前基线为账户自身历史的均值 / 标准差，对季节性经营（如年节前后集中收付）会产生误报
- 可演进方向：同业同规模账户群体的横向基线（peer-group baseline）、按月季调整的时序基线
- 涉及：`core/rule_engine.py` 的 `compute_baseline()`

### 7.4 资金链路可视化

- 将 networkx 构建的对手方图导出为可交互视图，报告中嵌入资金流向图，辅助人工复核
- 涉及：`core/report.py`, `mcp_server/transactions.py`

### 7.5 更多候选方向

- **规则库热更新**：监管规则变更后无需重启即可加载新版本（规则版本已随哈希链创世值绑定进轨迹，历史报告可按当时规则复算，此项只需补热加载）
- **多辖区支持**：规则库按辖区分目录（境内 / 香港 / 欧盟），案件上下文决定加载哪套规则
- **人工反馈闭环**：复核人员对报告的修正回流为长期记忆的负样本，用于调整调查路径
- **批量预警处理**：eval 与生产批处理并行化，支持一次调查一批预警并按风险排序输出
- **HTTP transport**：MCP Server 增加 SSE/HTTP 传输，支持行内多系统远程复用
