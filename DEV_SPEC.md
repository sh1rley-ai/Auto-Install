# DEV_SPEC.md — Auto-Install 开发规范

> 本文档是项目的唯一技术权威参考。所有架构决策、模块设计、开发规范均以本文档为准。
> 章节结构与 auto-coder skill 的 references 映射一一对应（1 概述 / 2 特性 / 3 技术选型 / 4 测试 / 5 架构 / 6 排期 / 7 未来规划），修改章节标题或顺序前须同步更新 `.claude/skills/auto-coder/scripts/sync_spec.py` 的映射。

---

## 1. 项目概述

### 设计理念

Auto-Install 是一个基于 LangGraph 的多 Agent 系统，能够自动化安装 CLI 工具与开源项目，面向 Linux/macOS 环境。

**目标**：在命令行直接输入想要安装的工具，系统自动完成搜索、规划、安装与可用性验证。

**核心理念**：将软件安装建模为 Plan-and-Execute 双 Agent 协作过程。Planner 负责生成并维护一份可增删改的结构化计划（Plan State）；Executor 按步执行，每步内部走「CoT 推理决策 -> 工具调用 -> 结果反馈驱动下一步」的闭环；执行结果回传 Planner，失败时先重试，连续失败触发动态重规划。

**背景**：当下技术迭代日益增长的时代，每天都有很多新技术的产生，比如刚出现的 deepseek-ocr，很多人都想快速尝鲜。但这个过程最重要的是配置环境安装该项目，费时且对新手复杂。而安装本质上是一个确定性过程：只要安装方案正确，大模型可以通过搜索找到合适路径并正确执行，大幅提升环境安装效率。

**设计原则**：

- **Plan-and-Execute 双 Agent**：Planner 先生成全局计划并全程维护计划状态（可增/删/改步骤），Executor 逐步执行；相比单步 ReAct 循环，全局计划显著降低方向性错误
- **执行闭环 + 动态重规划**：每步执行结果（含错误输出）反馈给 Executor 自我修正重试；连续失败超过阈值时上报 Planner 重规划，而非无限重试
- **环境感知**：启动时自动探测 OS / 包管理器 / conda / sudo 权限 / GPU 等，注入规划与执行上下文，动态生成跨环境自适应安装方案
- **工具层标准化**：环境探测、联网搜索、受控 shell 执行封装为独立 MCP Server，与 Agent 编排层解耦，可被任意 MCP 客户端复用
- **可观测性**：全流程结构化日志（步骤类型 / 内容 / 时间戳），支持失败归因与执行轨迹回放

### 项目定位

面向求职实战的 AI Agent 工程项目，核心展示能力：

- 基于 LangGraph 的 Plan-and-Execute 多 Agent 架构（Planner + Executor + Verifier，规划 / 执行 / 验证三权分离）
- Agent 执行闭环：CoT 推理 -> 结构化 Tool Calling -> 结果反馈 -> 重试 / 重规划
- 模块化 MCP Server（环境探测 / 联网搜索 / 受控 shell 执行）
- 短期 + 长期双层记忆：阈值触发 LLM 摘要 + 成功路径 LLM 蒸馏入库
- 系统级自动化与工程质量：环境感知、结构化日志、失败归因、轨迹回放
- 量化评估：150 个真实 GitHub 工具测试集，端到端成功率 72%

---

## 2. 核心特点

| 特点 | 说明 |
|------|------|
| **Plan-and-Execute 架构** | Planner 生成结构化计划并维护计划状态（每步含 id / 描述 / 状态），Executor 按步执行；执行结果驱动 Planner 对计划增删改，动态重规划 |
| **Agent 执行闭环** | Executor 每步内部：CoT 推理决策 -> Tool Calling（search / shell / finish_step）-> 结果反馈驱动下一步；失败自动重试，连续失败触发重规划 |
| **独立 Verifier Agent** | 验证与执行分离（Generator-Critic）：Verifier 以空白上下文、对抗性立场验证安装可用性，复用 Executor 子图代码，只换 prompt 与工具面（只读 shell），输出结构化裁决 passed / evidence / failure_reason |
| **环境感知** | 启动时自动探测 OS / 包管理器（brew / apt / yum）/ conda / sudo 权限 / GPU / CPU，注入规划上下文，同一软件在不同环境生成不同安装方案 |
| **模块化 MCP Server** | 环境探测、联网搜索、受控 shell 执行封装为标准 MCP 工具，通过 stdio 暴露，可被 Claude Desktop 等任意 MCP 客户端直接复用 |
| **双层记忆机制** | 短期：会话内历史超阈值自动触发 LLM 总结压缩；长期：安装成功后 LLM 蒸馏成功路径（剔除试错分支）存入 SQLite，跨会话复用 |
| **结构化日志与回放** | 每步记录 step_type / content / timestamp 的 JSONL 轨迹，支持失败归因分析与执行轨迹回放；同时输出人类可读 Markdown 报告 |
| **受控代码执行** | shell 命令经受控执行器运行：黑名单拦截、超时控制、stdout/stderr 全量捕获回传 |
| **量化评估** | 150 个真实 GitHub 工具测试集，端到端安装成功率 72% |

---

## 3. 技术选型

### AI 模型

| 模型 | 用途 | 选型理由 |
|------|------|----------|
| **Deepseek-reasoner** | Planner（规划 / 重规划） | 推理能力强，支持 thinking 输出，适合全局多步规划决策 |
| **Deepseek-chat** | Executor（单步执行决策）/ Verifier（可用性验证） | Tool Calling 稳定，单步决策与验证不需要 reasoner 的成本 |
| **Kimi (moonshot-v1-128k)** | Web 搜索 | 内置 `$web_search` 工具，128k 上下文可处理完整搜索结果页 |
| **Qwen-plus** (DashScope) | 历史摘要 / 成功路径蒸馏 / 相关性判断 | 成本低，摘要和蒸馏任务不需要最强模型 |

### 框架与库

| 库 | 版本 | 用途 |
|----|------|------|
| `langgraph` | >=0.2 | 多 Agent 状态机编排（父图 + Executor 子图） |
| `langchain-core` | >=0.3 | Tool 定义、消息类型（AIMessage、ToolMessage） |
| `mcp` | >=1.0 | MCP Server 实现（FastMCP，stdio transport） |
| `langchain-mcp-adapters` | >=0.1 | Agent 侧加载 MCP 工具为 LangChain Tool |
| `openai` | >=1.0 | Deepseek/Kimi API 客户端（OpenAI 兼容协议） |
| `dashscope` | >=1.14 | Qwen API 客户端 |
| `tenacity` | >=8.0 | API 调用指数退避重试 |
| `psutil` | >=5.9 | 系统信息（CPU/内存） |
| `GPUtil` | >=1.4 | GPU 信息 |
| `sqlite3` | stdlib | 长期记忆存储 |
| `pytest` | >=7.0 | 测试框架 |

### 为什么选 LangGraph 而非 LangChain AgentExecutor

LangGraph 的 StateGraph 完全匹配 Plan-and-Execute 结构：

- 计划状态（plan: list[PlanStep]）就是图的一等公民 State 字段，Planner 对它的增删改天然可追踪
- 父图（Planner 循环）+ 子图（Executor 闭环）的嵌套结构直接表达双 Agent 协作
- 条件边表达「重试 / 重规划 / 完成」的路由，比手写 while 循环清晰可控
- 内置 Checkpointer 直接解决会话内状态持久化（短期记忆的载体）
- 可视化状态图便于调试和面试展示

LangChain AgentExecutor 的局限：单 Agent ReAct 循环，无法表达显式计划状态和双层循环结构。

### 为什么工具层用 MCP 而非普通函数

- **复用性**：环境探测、联网搜索、受控 shell 是通用能力，封装为 MCP Server 后，Claude Desktop、Cursor 等任意 MCP 客户端可直接复用，不与本项目耦合
- **边界清晰**：Agent 编排层（决策）与工具层（能力）通过标准协议隔离，工具可独立测试、独立演进
- **安全收口**：所有 shell 执行必须经过 MCP Server 的受控执行器，黑名单 / 超时 / 审计日志在协议边界统一实施

---

## 4. 测试与评估方案

### 测试层次

```
tests/
├── unit/
│   ├── test_plan.py                 # 计划增删改、重规划 patch 应用
│   ├── test_history_manager.py      # 阈值触发摘要、轮数边界条件
│   ├── test_memory_manager.py       # 长期记忆 CRUD + 检索 + 蒸馏结果入库
│   └── test_shell_guard.py          # 受控执行：黑名单拦截、超时、输出捕获
├── integration/
│   ├── test_agent_loop.py           # Mock LLM，跑完整 Plan-and-Execute 循环
│   ├── test_replan.py               # 连续失败触发重规划、重规划次数上限
│   ├── test_verifier.py             # Verifier 空白上下文、只读约束、裁决路由
│   └── test_mcp_server.py           # MCP 工具经 stdio 端到端调用
└── e2e/
    └── test_install_cmake.py        # 端到端：真实安装 cmake（CI 环境执行）
```

### 测试约定

- 单元测试 Mock 所有外部依赖（LLM API / 网络 / subprocess），不调用真实 API
- 长期记忆测试使用内存 SQLite（`:memory:`）
- 集成测试对三条路由（正常执行 / 重试 / 重规划）各建完整用例

### 端到端评估（Benchmark）

- **测试集**：`eval/benchmark.jsonl`，150 个真实 GitHub 工具（覆盖 pip / brew / apt / 源码编译 / conda 等多种安装形态）
- **指标**：端到端成功率（安装完成且可用性验证通过）；当前结果 **72%**
- **失败归因分布**：评估脚本按 `attribute_failure()` 结果统计失败类别，指导后续优化方向
- **运行**：`python eval/run_eval.py --benchmark eval/benchmark.jsonl --report eval/report.md`

### 验收标准

| 层次 | 覆盖率目标 | 说明 |
|------|-----------|------|
| Unit | >80% | 计划操作、记忆、受控执行全覆盖 |
| Integration | 关键路径 | 正常执行 / 重试 / 重规划三条路由各有完整测试用例 |
| E2E | Benchmark | 150 工具测试集端到端成功率 >=72%，常用软件（cmake/git）>90% |

### 运行命令

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v --timeout=30
pytest tests/ --cov=core --cov=mcp_server --cov=utils --cov-report=term-missing
python eval/run_eval.py --benchmark eval/benchmark.jsonl
```

---

## 5. 系统架构与模块设计

### 多 Agent 架构设计

#### 为什么是这三个 Agent

多 Agent 的拆分边界应当跟随「决策职责」而非「工具种类」：

- **Planner Agent**（Deepseek-reasoner）：唯一职责是维护计划——初始规划、根据执行反馈重规划（增 / 删 / 改步骤）。它看到的是全局：安装目标、环境信息、长期记忆、各步骤执行摘要
- **Executor Agent**（Deepseek-chat + Tool Calling）：唯一职责是完成当前步骤——CoT 推理后选择工具（搜索 / shell 执行），观察结果决定重试或宣告本步完成 / 失败。它看到的是局部：当前步骤描述、本步内的执行历史
- **Verifier Agent**（Deepseek-chat + Tool Calling）：唯一职责是验证安装可用性。与 Executor 共用同一套子图代码，差异只在三处配置：
  - **空白上下文**：只拿到「装了什么 + 环境信息」，不带安装过程的消息历史。这是为了消除自评偏差（self-grading）——装的人给自己打分倾向打高分，典型漏网案例：命令都返回 0，但装错了 conda 环境、二进制不在 PATH、daemon 没起来
  - **对抗性 prompt**（`prompt_verify`）：默认立场是「假设安装可能失败，用命令证明它可用」（查版本、跑最小示例），而非顺着执行记录确认成功
  - **只读工具面**：仅允许 `run_shell` 的只读类命令（查版本 / 查路径 / 跑示例），不授予改系统的能力
  - 输出结构化裁决 `{passed, evidence, failure_reason}`，写入 `AgentState.verdict`；failed 时 `failure_reason` 注入 Planner 的重规划上下文，驱动补救循环
- 搜索、环境探测、shell 执行是**工具**（MCP Tools），不是 Agent——它们没有决策职责，拆成独立 Agent 只会增加通信开销和不确定性

这种拆分的收益：Planner 的上下文不被每步的 stdout/stderr 噪音污染，Executor 的上下文不需要携带完整全局历史，token 消耗和错误率同时下降；Executor 与 Verifier 构成 Generator-Critic（生成者-批判者）分离，验证结论不受安装过程叙述的诱导。Verifier 的新增成本约等于一个新 prompt——子图代码完全复用。

#### 状态与协作协议

```python
class PlanStep(TypedDict):
    id: int
    description: str        # 步骤描述，如 "使用 brew 安装 cmake"
    status: str             # pending / running / done / failed / skipped
    result_summary: str     # Executor 回传的执行结果摘要

class AgentState(TypedDict):
    goal: str                     # 用户安装目标
    system_info: str              # 环境探测结果
    memory_context: str           # 长期记忆检索结果
    plan: list[PlanStep]          # Planner 维护的计划状态
    current_step_id: int
    executor_messages: list       # 子图局部消息（Executor 步骤间清空，Verifier 进入时置空）
    verdict: dict                 # Verifier 裁决 {passed, evidence, failure_reason}
    consecutive_failures: int     # 连续失败步数，触发重规划
    replan_count: int             # 重规划次数上限保护
    step_count: int               # 全局步数上限保护
```

#### 状态机结构

```python
graph = StateGraph(AgentState)
graph.add_node("planner", plan_node)          # 生成 / 修订计划
graph.add_node("executor", executor_subgraph) # 执行当前步骤（内部闭环）
graph.add_node("verifier", verifier_subgraph) # Verifier Agent（复用 Executor 子图，独立 prompt + 空白上下文）
graph.add_node("memorize", memorize_node)     # 蒸馏成功路径入库

graph.add_edge(START, "planner")
graph.add_conditional_edges("planner", route_plan, {
    "execute": "executor",     # 有 pending 步骤
    "verify": "verifier",      # 全部 done
    "abort": END               # 重规划超限，放弃
})
graph.add_conditional_edges("executor", route_step_result, {
    "next_step": "executor",   # 本步 done，取下一步
    "replan": "planner",       # 本步 failed 且连续失败达阈值
    "retry": "executor"        # 本步 failed，未达阈值，重试
})
graph.add_conditional_edges("verifier", route_verify, {
    "success": "memorize",
    "failed": "planner"        # 验证不通过，回 Planner 补救
})
graph.add_edge("memorize", END)
```

Executor 内部是一个子图（executor_subgraph），实现单步闭环。子图由参数化工厂 `build_executor(prompt, tools, fresh_context)` 装配——换上 `prompt_verify`、只读工具面和空白上下文，同一套代码即得到 verifier_subgraph：

```
reason_node (CoT 推理 + Tool Call)
    |
    +--> tool_node (调用 MCP 工具: web_search / run_shell)
    |        |
    |        v
    |    observe: ToolMessage 写回 executor_messages
    |        |
    |        +--> reason_node (结果反馈驱动下一步决策)
    |
    +--> finish_step (宣告本步 done / failed，产出 result_summary)
```

### 整体架构图

```
+------------------------------------------------------------------+
|                          CLI (main.py)                           |
|          python main.py --install "docker" --verbose             |
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
|  [START] -> planner ----------> executor 子图 -----> verifier    |
|               ^   (维护 plan)   (单步闭环:           |            |
|               |                  CoT -> tool -> 反馈) |           |
|               +---- replan <---- 连续失败 ------------+           |
|               |                                       |           |
|             [END abort]                       memorize -> [END]  |
+------+------------------------+----------------------------------+
       |                        |
       v                        v
+---------------+    +------------------------------+
| Short-term    |    | MCP Server (mcp_server/)     |
| Memory        |    |  - probe_environment          |
| (Checkpointer |    |  - web_search (Kimi)          |
|  + 阈值摘要)  |    |  - run_shell (受控执行)       |
+---------------+    +------------------------------+
       |
       v
+---------------+    +------------------------------+
| Long-term     |    | TraceLogger (core/logger.py) |
| Memory        |    |  logs/trace_*.jsonl (回放)    |
| (SQLite +     |    |  logs/installation_*.md      |
|  成功路径蒸馏)|    |  (人类可读报告)               |
+---------------+    +------------------------------+
```

### 完整目录结构

```
auto_install_v2/
├── main.py                          # CLI 入口（含 --replay 轨迹回放）
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
│   ├── agent.py                     # [NEW] LangGraph 父图（Planner/Verifier/Memorize 节点 + 路由）
│   ├── executor.py                  # [NEW] 参数化子图工厂（Executor/Verifier 共用: reason -> tool -> observe）
│   ├── plan.py                      # [NEW] PlanStep/AgentState 定义 + 计划增删改操作
│   ├── installer.py                 # [REFACTOR] 对外接口，内部委托给 agent.py
│   ├── history_manager.py           # 短期记忆（阈值触发 LLM 摘要压缩）
│   ├── memory_manager.py            # [NEW] 长期记忆（SQLite CRUD + 成功路径蒸馏 + 检索）
│   └── logger.py                    # [REFACTOR] 结构化 JSONL 轨迹 + Markdown 报告
│
├── mcp_server/
│   ├── __init__.py
│   ├── server.py                    # [NEW] FastMCP Server 入口（stdio）
│   ├── env_probe.py                 # [NEW] 环境探测工具（OS/包管理器/conda/sudo/GPU）
│   ├── search.py                    # [NEW] 联网搜索工具（封装 Kimi $web_search）
│   └── shell.py                     # [NEW] 受控 shell 执行（黑名单/超时/输出捕获）
│
├── utils/
│   ├── __init__.py
│   ├── deepseek.py                  # Deepseek API 封装（streaming + retry）
│   ├── qwen.py                      # Qwen API 封装（摘要 / 蒸馏 / 相关性判断）
│   ├── kimi_search.py               # Kimi Web 搜索封装（被 mcp_server/search.py 复用）
│   └── get_system_summary.py        # 系统环境检测（被 mcp_server/env_probe.py 复用）
│
├── prompt/
│   └── prompt.py                    # 所有 prompt 模板集中管理（规划/执行/重规划/验证/蒸馏）
│
├── eval/
│   ├── benchmark.jsonl              # [NEW] 150 个真实 GitHub 工具测试集
│   └── run_eval.py                  # [NEW] 批量评估脚本，统计端到端成功率
│
├── tests/
│   ├── unit/
│   │   ├── test_plan.py             # 计划增删改操作
│   │   ├── test_history_manager.py
│   │   ├── test_memory_manager.py
│   │   └── test_shell_guard.py      # 受控执行黑名单/超时
│   └── integration/
│       ├── test_agent_loop.py       # Mock LLM 跑完整 Plan-and-Execute 循环
│       ├── test_replan.py           # 连续失败触发重规划
│       ├── test_verifier.py         # Verifier 空白上下文与裁决路由
│       └── test_mcp_server.py       # MCP 工具端到端调用
│
└── logs/                            # 运行时生成，不提交 git
    ├── trace_*.jsonl                # 结构化轨迹（回放用）
    └── installation_*.md            # 人类可读报告
```

### 模块职责说明

| 模块 | 职责 | 关键类/函数 |
|------|------|------------|
| `main.py` | CLI 参数解析、配置加载、启动入口、轨迹回放 | `main()`, `replay_trace()` |
| `config/enhanced_config.py` | 三优先级配置加载、字段校验、序列化 | `EnhancedConfig`, `AIModelConfig` |
| `core/agent.py` | 父图定义：Planner / Memorize 节点、Verifier Agent 装配与条件路由 | `build_graph()`, `plan_node()`, `build_verifier()` |
| `core/executor.py` | 参数化子图工厂（Executor 与 Verifier 共用）：CoT 推理 -> 工具调用 -> 结果反馈闭环 | `build_executor(prompt, tools, fresh_context)`, `reason_node()`, `route_tool()` |
| `core/plan.py` | 计划数据结构与增删改操作，重规划 diff 计算 | `PlanStep`, `AgentState`, `apply_plan_patch()` |
| `core/installer.py` | 对外接口，兼容旧调用方式，委托给 agent.py | `AutoInstaller.install_software()` |
| `core/history_manager.py` | 短期记忆：历史超阈值触发 LLM 总结，保留最近 N 轮完整记录 | `HistoryManager`, `summarize_old_entries()` |
| `core/memory_manager.py` | 长期记忆：成功后蒸馏路径入库，启动前检索相关记录 | `MemoryManager`, `distill_success_path()`, `retrieve_relevant()` |
| `core/logger.py` | 结构化 JSONL 轨迹（step_type/content/timestamp）+ Markdown 报告 | `TraceLogger.log_step()`, `TraceLogger.attribute_failure()` |
| `mcp_server/server.py` | FastMCP Server 入口，注册三个工具，stdio 传输 | `mcp = FastMCP("auto-install")` |
| `mcp_server/env_probe.py` | 探测 OS / 包管理器 / conda / sudo / GPU / CPU | `probe_environment()` |
| `mcp_server/search.py` | 联网搜索安装文档 | `web_search(query)` |
| `mcp_server/shell.py` | 受控 shell 执行：黑名单拦截、超时、全量输出捕获 | `run_shell(cmd, timeout)` |
| `utils/deepseek.py` | Deepseek API 调用，streaming + 指数退避重试 | `Deepseek.chat()`, `Deepseek.stream_chat()` |
| `utils/kimi_search.py` | Kimi Web 搜索，tool_calls 循环处理 | `KimiSearch.get_search_res()` |
| `utils/qwen.py` | Qwen API：摘要、蒸馏、相关性判断 | `QueryTongyi.chat()` |
| `utils/get_system_summary.py` | 环境检测底层实现 | `get_system_summary()` |
| `prompt/prompt.py` | prompt 模板集中管理 | `prompt_plan`, `prompt_replan`, `prompt_execute`, `prompt_verify`, `prompt_distill` |
| `eval/run_eval.py` | 在 150 工具测试集上批量运行，统计成功率与失败归因分布 | `run_benchmark()` |

### 数据流说明

```
用户输入: python main.py --install "docker"
    |
    v
[1] 环境感知 probe_environment()（经 MCP）
    -> OS: macOS 14, pkg: brew, conda: yes(base), sudo: yes, GPU: None
    -> 注入 AgentState.system_info

[2] 长期记忆检索 memory_manager.retrieve_relevant("docker")
    -> 命中则返回蒸馏后的成功路径，注入 AgentState.memory_context

[3] planner: Deepseek-reasoner 生成结构化计划（结合环境 + 记忆 + 必要时先搜索）
    -> plan = [
         {id:1, desc:"web_search 确认 macOS brew 安装 docker 的最新方式", status:pending},
         {id:2, desc:"brew install --cask docker", status:pending},
         {id:3, desc:"启动 Docker.app 并等待 daemon 就绪", status:pending},
         {id:4, desc:"docker --version 验证", status:pending},
       ]

[4] executor 执行 step 1: CoT 推理 -> Tool Call web_search(...)
    -> 搜索结果写回 executor_messages -> 推理确认方案 -> finish_step(done)

[5] executor 执行 step 2: Tool Call run_shell("brew install --cask docker")
    -> returncode != 0, stderr: "Cask 'docker' requires sudo..."
    -> 结果反馈驱动下一步：推理后重试 run_shell("sudo brew install ...")
    -> 仍失败, consecutive_failures 达阈值(2) -> 路由回 planner

[6] planner 重规划: 依据失败反馈修改计划
    -> 将 step 2 改为 "下载 Docker.dmg 直接安装"，删除失效步骤，插入新步骤
    -> plan 状态更新（原 step 2 标记 failed，新增 step 2'）

[7] executor 继续执行修订后的计划 ... 全部 done

[8] verifier: 空白上下文启动（只给「目标: docker」+ system_info，不带安装历史）
    -> 对抗性验证: run_shell("docker --version") + run_shell("docker run hello-world")
    -> 裁决 {passed: true, evidence: "Docker version 27.x; hello-world 运行成功"} -> success

[9] memorize:
    qwen.distill_success_path(trace) -> 剔除试错分支，仅保留有效步骤序列
    memory_manager.save_installation(software="docker", distilled_steps=..., success=True)

[10] 全程 TraceLogger 逐步落盘:
    {"step_type": "plan",    "content": {...}, "timestamp": "2026-07-09T10:00:01"}
    {"step_type": "tool_call", "content": {"tool": "run_shell", ...}, "timestamp": ...}
    {"step_type": "replan",  "content": {"patch": [...]}, "timestamp": ...}
    -> 支持 python main.py --replay logs/trace_xxx.jsonl 回放
```

### 双层记忆机制

**短期记忆（会话内）**：

- 载体：LangGraph Checkpointer + `HistoryManager`
- 触发：Executor 消息历史超过阈值（默认 6 轮）时，自动调用 Qwen 总结旧记录为摘要，保留最近 2 轮完整记录
- 目的：防止长安装流程 token 超限，同时不丢失关键上下文

**长期记忆（跨会话）**：

- 载体：SQLite（`installation_records` 表）
- 写入：安装成功后，调用 Qwen 对完整执行轨迹做**成功路径蒸馏**——剔除失败重试和试错分支，只保留最终有效的步骤序列，作为下次同类安装的高质量参考
- 读取：安装启动前按软件名检索，Qwen 做相关性过滤（防止 "docker" 命中 "docker-compose" 类误匹配），命中则注入 Planner 上下文

```sql
CREATE TABLE IF NOT EXISTS installation_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    software_name TEXT NOT NULL,
    computer_environment TEXT,
    user_query TEXT,
    distilled_steps TEXT,          -- LLM 蒸馏后的成功路径（JSON）
    raw_trace_path TEXT,           -- 原始轨迹文件路径（归因/回放用）
    success INTEGER DEFAULT 1,
    error_message TEXT DEFAULT '',
    session_id TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_software_name ON installation_records(software_name);
```

### 结构化日志与回放

- **格式**：JSONL，每行一个事件：`{"step_type": ..., "content": ..., "timestamp": ...}`；step_type 枚举：`plan / replan / reason / tool_call / tool_result / step_done / step_failed / verify / distill / abort`
- **失败归因**：安装失败时，`TraceLogger.attribute_failure()` 沿轨迹定位首个不可恢复错误（区分：搜索无结果 / 命令报错 / 权限不足 / 超时 / 重规划超限），写入报告与评估统计
- **轨迹回放**：`python main.py --replay logs/trace_xxx.jsonl` 按时间序重现每步决策与输出，便于调试与演示
- **人类可读报告**：同步生成 Markdown 版安装报告（计划、执行摘要、最终结果）

### 配置驱动设计示例

```json
{
    "ai_models": {
        "deepseek_api_key": "",
        "kimi_api_key": ""
    },
    "history": {
        "max_history_rounds": 6,
        "keep_recent_rounds": 2,
        "enable_summarization": true
    },
    "installation": {
        "max_installation_steps": 30,
        "max_step_retries": 2,
        "max_replans": 3,
        "code_execution_timeout_seconds": 120
    },
    "logging": {
        "log_directory": "logs",
        "enable_trace_jsonl": true,
        "enable_markdown_logs": true
    }
}
```

---

## 6. 项目排期

### 阶段划分

```
Phase 0 (完成) -> Phase 1 -> Phase 2 -> Phase 3 -> Phase 4
基础功能已实现   Plan-and-   MCP Server  双记忆 +   测试 + 评估
  [当前状态]     Execute     模块化      日志回放    工程打磨
                重构 [P0]    [P0]        [P0]       [P1]
```

---

### Phase 1：Plan-and-Execute 多 Agent 重构（预计 4 天）

**目标**：用 LangGraph 父图（Planner）+ 子图（Executor / Verifier）替代单循环，引入显式计划状态、动态重规划与独立验证

#### 子任务 1.1：计划状态与操作

- **修改文件**：`core/plan.py`（新建）
- **实现**：
  - `PlanStep(TypedDict)` / `AgentState(TypedDict)` — 见第 5 节定义
  - `apply_plan_patch(plan, patch) -> plan` — 应用 Planner 输出的增/删/改操作（JSON patch 形式）
- **验收标准**：patch 操作幂等、越界 id 报错；`pytest tests/unit/test_plan.py`

#### 子任务 1.2：Planner 节点与重规划

- **修改文件**：`core/agent.py`（新建）, `prompt/prompt.py`
- **实现**：
  - `plan_node()` — 首次调用生成完整计划；重入时依据失败反馈输出 plan patch
  - `route_plan()` — pending 步骤 -> executor；全部 done -> verifier；replan_count 超限 -> abort
- **验收标准**：Mock LLM 返回固定 patch，验证计划状态正确演进

#### 子任务 1.3：Executor 子图（单步执行闭环）

- **修改文件**：`core/executor.py`（新建）
- **实现**：
  - `reason_node()` — CoT 推理 + Tool Call（search / run_shell / finish_step）
  - `route_step_result()` — done -> 下一步；failed 且 consecutive_failures < 阈值 -> 重试；达阈值 -> replan
  - 步骤间清空 `executor_messages`，防止上下文污染
- **验收标准**：三条路由（正常 / 重试 / 重规划）各有集成测试；`pytest tests/integration/test_replan.py`

#### 子任务 1.4：Verifier Agent（复用子图）

- **修改文件**：`core/agent.py`, `prompt/prompt.py`
- **实现**：
  - `build_verifier()` — 调用 `build_executor(prompt=prompt_verify, tools=只读 run_shell, fresh_context=True)` 装配 verifier_subgraph
  - `prompt_verify` — 对抗性立场：假设安装可能失败，用命令证明可用；输出 `{passed, evidence, failure_reason}` 写入 `AgentState.verdict`
  - failed 时 `failure_reason` 注入 Planner 重规划上下文
- **验收标准**：Mock 场景「安装命令全部返回 0 但二进制不在 PATH」被判 failed 并路由回 planner
- **测试方法**：`pytest tests/integration/test_verifier.py`

#### 子任务 1.5：接口兼容

- **修改文件**：`core/installer.py`
- **实现**：`install_software()` 内部改为调用 `build_graph().invoke()`，保持 `main.py` 接口不变
- **验收标准**：`python main.py --install "cmake"` 正常运行

**进度追踪**：
- [x] 1.1 计划状态与操作 — 新增 core/plan.py（PlanStep/AgentState 定义 + apply_plan_patch 增删改操作），9 个单测覆盖
- [x] 1.2 Planner 节点与重规划 — 新增 core/agent.py（build_planner 工厂 + plan_node 首次规划/重规划 + route_plan 路由）；直接改造既有 prompt_plan 输出为结构化 JSON（不再新建 prompt_plan_structured），新增 prompt_replan；7 个单测（Mock LLM）覆盖。注意：prompt_plan 输出格式变更导致旧版 core/installer.py 的自由文本解析路径（main.py --install）暂时失效，待 1.5 接口兼容任务重构后恢复
- [x] 1.3 Executor 子图 — 新增 core/executor.py（build_executor 工厂 + reason_node CoT推理/工具调用 + route_tool + route_step_result 三路由）与 prompt_execute；6 单测 + 3 集成测试（正常/重试/重规划）覆盖，均用 Mock LLM + Mock 工具
- [x] 1.4 Verifier Agent — core/agent.py 新增 build_verifier（复用 build_executor，prompt_verify + 只读工具 + 空白上下文）+ route_verify；prompt/prompt.py 新增 prompt_verify（对抗性验证立场）；3 个集成测试覆盖通过/binary不在PATH判失败/空白上下文不泄露安装历史
- [x] 1.5 接口兼容 — core/agent.py 新增 build_graph（组装 planner/executor/verifier/memorize 全图）+ memorize_node（Phase 3 前的空实现桩）；core/installer.py 的 install_software 改为调用 build_graph().invoke()，恢复 main.py --install 接口；过程中发现并修复两处路由缺口：route_step_result 补充区分"pending"(推进到下一步)/"done"(all_done 交还 planner)两态，plan_node 补充 _needs_replan 判断避免每次重入误判为需要重规划；12 个新测试（含全链路 mock 集成测试 test_agent_loop.py 和 installer 接线测试）覆盖

---

### Phase 2：MCP Server 模块化（预计 2 天）

**目标**：环境探测 / 联网搜索 / 受控 shell 执行封装为标准 MCP Server，Agent 侧经 adapter 加载

#### 子任务 2.1：MCP Server 实现

- **修改文件**：`mcp_server/server.py`, `env_probe.py`, `search.py`, `shell.py`（均新建）
- **实现**：
  - FastMCP 注册三个工具：`probe_environment()`, `web_search(query)`, `run_shell(cmd, timeout)`
  - `run_shell` 受控执行：危险命令黑名单（`rm -rf /`、`mkfs` 等）、默认 120s 超时、stdout/stderr 全量捕获、执行审计写入日志
  - `probe_environment` 探测：OS / 包管理器（brew/apt/yum/dnf）/ conda（含当前环境名）/ sudo 可用性 / GPU（nvidia-smi）/ CPU / 内存
- **验收标准**：`mcp dev mcp_server/server.py` 可交互调用三个工具；Claude Desktop 挂载可用
- **测试方法**：`pytest tests/unit/test_shell_guard.py tests/integration/test_mcp_server.py`

#### 子任务 2.2：Agent 侧接入

- **修改文件**：`core/executor.py`, `core/agent.py`
- **实现**：`langchain-mcp-adapters` 经 stdio 加载 MCP 工具，绑定到 Executor 的 Tool Calling
- **验收标准**：完整安装流程中所有工具调用均经 MCP 协议完成

**进度追踪**：
- [ ] 2.1 MCP Server 实现
- [ ] 2.2 Agent 侧接入

---

### Phase 3：双记忆 + 结构化日志（预计 3 天）

**目标**：短期阈值摘要 + 长期成功路径蒸馏；JSONL 轨迹 + 失败归因 + 回放

#### 子任务 3.1：长期记忆与蒸馏

- **修改文件**：`core/memory_manager.py`（新建）, `prompt/prompt.py`
- **实现**：
  - `MemoryManager` — SQLite 建表 / CRUD，表结构见第 5 节
  - `distill_success_path(trace) -> list[dict]` — 调用 Qwen，输入完整轨迹，输出剔除试错分支后的有效步骤序列
  - `retrieve_relevant(query, env)` — LIKE 检索 + Qwen 相关性过滤
- **验收标准**：安装 cmake 两次，第二次命中记忆且步骤数明显减少；蒸馏结果不含失败步骤
- **测试方法**：`pytest tests/unit/test_memory_manager.py`（内存 SQLite `:memory:`）

#### 子任务 3.2：短期记忆接入

- **修改文件**：`core/history_manager.py`, `core/executor.py`
- **实现**：Executor 消息超 6 轮触发 Qwen 摘要，保留最近 2 轮完整记录
- **验收标准**：长流程安装（>10 步）不触发 token 超限

#### 子任务 3.3：结构化日志与回放

- **修改文件**：`core/logger.py`, `main.py`
- **实现**：
  - `TraceLogger.log_step(step_type, content)` — 逐事件写 JSONL（附时间戳）
  - `TraceLogger.attribute_failure(trace)` — 定位首个不可恢复错误并分类
  - `main.py --replay <trace.jsonl>` — 按时间序回放执行轨迹
- **验收标准**：任一次安装的轨迹可完整回放；失败案例报告中含归因类别

**进度追踪**：
- [ ] 3.1 长期记忆与蒸馏
- [ ] 3.2 短期记忆接入
- [ ] 3.3 结构化日志与回放

---

### Phase 4：测试 + 评估 + 工程打磨（预计 3 天）

**目标**：覆盖核心路径，建立 150 工具 benchmark，全量 Type Hints

#### 子任务 4.1：单元 + 集成测试

- **覆盖内容**：见第 4 节测试层次
- **验收标准**：`pytest tests/ --cov` 覆盖率 >70%，Mock 不调用真实 API

#### 子任务 4.2：Benchmark 评估

- **修改文件**：`eval/benchmark.jsonl`, `eval/run_eval.py`（新建）
- **实现**：
  - 从 GitHub 收集 150 个真实工具（pip / brew / apt / 源码编译 / conda 多形态分层抽样）
  - 批量运行，统计端到端成功率与失败归因分布，输出 Markdown 报告
- **验收标准**：端到端成功率 >=72%，报告含失败类别分布

#### 子任务 4.3：Type Hints + Retry

- **实现**：
  - 所有公共函数完整 Type Hints
  - `tenacity.retry`：`wait_exponential(min=1, max=10)`, `stop_after_attempt(3)`，仅重试网络/超时异常
- **验收标准**：`mypy core/ mcp_server/ utils/ --ignore-missing-imports` 无 error

**进度追踪**：
- [ ] 4.1 单元 + 集成测试
- [ ] 4.2 Benchmark 评估
- [ ] 4.3 Type Hints + Retry

---

### 改进优先级总览

| 优先级 | 改进点 | 涉及文件 | Phase |
|--------|--------|----------|-------|
| P0 | Plan-and-Execute 多 Agent 重构（计划状态 + 重规划） | `core/plan.py`, `core/agent.py`, `core/executor.py` | 1 |
| P0 | 独立 Verifier Agent（Generator-Critic 验证分离） | `core/agent.py`, `prompt/prompt.py` | 1 |
| P0 | MCP Server 模块化（探测/搜索/受控执行） | `mcp_server/` | 2 |
| P0 | 长期记忆 + 成功路径蒸馏 | `core/memory_manager.py` | 3 |
| P0 | 结构化 JSONL 日志 + 失败归因 + 回放 | `core/logger.py`, `main.py` | 3 |
| P0 | 测试体系（当前零测试文件） | `tests/` | 4 |
| P0 | 150 工具 Benchmark 评估 | `eval/` | 4 |
| P1 | 短期记忆阈值摘要正式接入 | `core/history_manager.py` | 3 |
| P1 | 全量 Type Hints + tenacity 重试 | `core/`, `mcp_server/`, `utils/` | 4 |
| P1 | Streaming 输出 | `utils/deepseek.py` | 4 |
| P2 | 未来规划项 | 见第 7 节 | 后续 |

---

## 7. 未来规划

以下为 Phase 4 之后的候选方向（P2 优先级），评估范围或扩展功能时参考：

### 7.1 提升 Benchmark 成功率（72% -> 80%+）

- 基于失败归因分布定向优化：搜索无结果类失败补充多引擎搜索；权限类失败增强 sudo 交互处理
- 对源码编译类安装引入依赖预检（编译器版本、系统库）
- 涉及：全局，以 `eval/report.md` 归因数据驱动

### 7.2 向量检索长期记忆

- 当前 LIKE + LLM 相关性过滤在记录量大时召回不足
- 引入 embedding 检索（软件名 + 环境描述向量化），SQLite 侧可用 sqlite-vec
- 涉及：`core/memory_manager.py`

### 7.3 Rich CLI 美化

- rich 库实现计划进度表格、执行日志高亮、streaming 输出渲染
- 涉及：`main.py`

### 7.4 更多候选方向

- **Windows 支持**：环境探测与包管理器（winget / choco）适配
- **沙箱执行**：run_shell 在 Docker 容器内执行后再落地宿主机，进一步降低风险
- **并发评估**：eval 批量运行并行化，缩短 benchmark 周期
- **HTTP transport**：MCP Server 增加 SSE/HTTP 传输，支持远程复用
