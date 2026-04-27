# DEV_SPEC.md — Auto-Install v2 开发规范

> 本文档是项目的唯一技术权威参考。所有架构决策、模块设计、开发规范均以本文档为准。

---

## 1. 项目概述

### 设计理念

Auto-Install 是一个LLM智能体(Agent)系统，他能够自动化软件安装 CLI 工具，面向 Linux/macOS 环境。

**目标**：在命令行直接输入想要安装的工具，模型就能自动完成安装，并测试可用性。

**核心理念**：将软件安装过程建模为一个有状态的 Agent 决策循环。Agent 在每一步感知环境（系统信息、执行结果）、规划下一步行动（搜索 or 执行），直到安装完成或达到步数上限。

**背景**：当下技术迭代日益增长的时代，每天都有很多新技术的产生，比如刚出现的deepseek-ocr，很多人都想快速尝鲜。但是这个过程，最重要的是你需要配置环境安装该项目，该过程费时间且对于很多新手折腾环境是一件很复杂的事情，但是该过程是一个确定性的过程，只要安装方案是确定的，大模型可以通过搜索找到合适的路径并安装正确，大幅度的提升环境安装的效率，提升人们的工作效率。

**设计原则**：

- **Plan-and-Execute 模式**：先通过 Web 搜索获取正确的安装方式，再逐步执行，显著降低错误率
- **上下文感知**：每次 AI 决策都携带完整的历史执行记录和系统环境信息
- **容错优先**：每步执行结果（包括错误输出）都反馈给 AI，允许自我修正和重试
- **可观测性**：所有执行步骤持久化为结构化 Markdown 日志，便于调试和分析

### 项目定位

面向求职实战的 AI Agent 工程项目，核心展示能力：

- 多模型 AI Pipeline 编排（Deepseek + Kimi + Qwen）
- LangGraph 状态机 Agent 架构（Plan-and-Execute）
- 结构化 Tool Calling（Function Calling）替代 Regex 解析
- 短期 + 长期双记忆管理系统
- 系统级自动化（subprocess 安全执行 + 环境感知）

---

## 2. 核心特点

| 特点 | 说明 |
|------|------|
| **LangGraph Agent 编排** | 使用 StateGraph 定义 Plan → Search/Execute → Check 的循环状态机，条件分支路由，比手写 while 循环更清晰可控 |
| **结构化 Tool Calling** | AI 通过 Function Calling 选择工具（search/execute/finish），而非文本正则解析，稳定性大幅提升 |
| **双记忆系统** | 短期记忆（LangGraph Checkpointer，会话内状态持久化）+ 长期记忆（SQLite，跨会话复用历史安装教程） |
| **系统环境感知** | 启动时自动检测 OS/包管理器/GPU/CPU/sudo 权限，注入每次 AI 决策上下文 |
| **自适应历史压缩** | 超过 6 轮后自动 AI 摘要，防止 token 超限，保留最近 2 轮完整记录 |
| **安全代码执行** | AI 生成 Python 代码，通过 subprocess.Popen 执行，stdout/stderr 全量捕获并回传 AI |
| **结构化日志** | 每次安装生成 Markdown 日志，记录搜索/计划/执行/结果完整链路 |

---

## 3. 技术选型

### AI 模型

| 模型 | 用途 | 选型理由 |
|------|------|----------|
| **Deepseek-reasoner** | 主规划模型 | 推理能力强，支持 thinking 输出，适合复杂多步安装决策 |
| **Kimi (moonshot-v1-128k)** | Web 搜索 | 内置 `$web_search` 工具，128k 上下文可处理完整搜索结果页 |
| **Qwen-plus** (DashScope) | 历史摘要 / 相关性判断 | 成本低，摘要和分类任务不需要最强模型 |

### 框架与库

| 库 | 版本 | 用途 |
|----|------|------|
| `langgraph` | >=0.2 | Agent 状态机编排 |
| `langchain-core` | >=0.3 | Tool 定义、消息类型（AIMessage、ToolMessage） |
| `openai` | >=1.0 | Deepseek/Kimi API 客户端（OpenAI 兼容协议） |
| `dashscope` | >=1.14 | Qwen API 客户端 |
| `tenacity` | >=8.0 | API 调用指数退避重试 |
| `psutil` | >=5.9 | 系统信息（CPU/内存） |
| `GPUtil` | >=1.4 | GPU 信息 |
| `sqlite3` | stdlib | 长期记忆存储 |
| `pytest` | >=7.0 | 测试框架 |

### 为什么选 LangGraph 而非 LangChain AgentExecutor

LangGraph 的 StateGraph 完全匹配本项目的循环结构：

- 每个节点对应一个 Agent 行为（plan / search / execute / check）
- 条件边对应工具路由（搜索 or 执行 or 完成）
- 内置 MemorySaver/SqliteSaver 直接解决会话内历史管理
- 可视化状态图便于调试和面试展示

LangChain AgentExecutor 的局限：不适合需要精细控制循环步骤、中间状态和条件分支的场景。

```python
# 状态机结构示意
graph = StateGraph(AgentState)
graph.add_node("planner", plan_node)
graph.add_node("search", search_node)
graph.add_node("execute", execute_node)
graph.add_node("checker", checker_node)

graph.add_conditional_edges("planner", route_action, {
    "search": "search",
    "execute": "execute",
    "finish": END
})
graph.add_edge("search", "planner")
graph.add_edge("execute", "checker")
graph.add_conditional_edges("checker", check_result, {
    "continue": "planner",
    "done": END,
    "error": "planner"
})
```

---

## 4. 测试方案

### 测试层次

```
tests/
├── unit/
│   ├── test_text_processors.py     # TextProcessor 各提取方法
│   ├── test_history_manager.py     # 历史摘要逻辑、轮数边界条件
│   ├── test_system_summary.py      # 系统信息检测
│   └── test_memory_manager.py      # 长期记忆 CRUD + 检索
├── integration/
│   ├── test_agent_loop.py          # Mock AI 响应，跑完整 Agent 循环
│   └── test_tool_calling.py        # Mock Deepseek，验证 Tool Call 路由逻辑
└── e2e/
    └── test_install_cmake.py       # 端到端：真实安装 cmake（CI 环境执行）
```

### 验收标准

| 层次 | 覆盖率目标 | 说明 |
|------|-----------|------|
| Unit | >80% | 核心工具类全覆盖 |
| Integration | 关键路径 | search/execute/finish 三条路由各有完整测试用例 |
| E2E | 手动 + CI | cmake、git 等常用软件安装成功率 >90% |

### 运行命令

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v --timeout=30
pytest tests/ --cov=core --cov=utils --cov-report=term-missing
```

---

## 5. 系统架构与模块设计

### 整体架构图

```
+------------------------------------------------------------------+
|                          CLI (main.py)                           |
|          python main.py --install "docker" --verbose             |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                       EnhancedConfig                            |
|          CLI Args > config/user_config.json > ENV vars           |
+-----------------------------+------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                  LangGraph Agent (core/agent.py)                 |
|                                                                  |
|  [START] --> planner_node --+--> search_node --> planner_node   |
|                             |                                    |
|                             +--> execute_node --> checker_node  |
|                             |         |                          |
|                             |         +--> planner_node (retry) |
|                             |                                    |
|                             +--> [END]                           |
+------+-------------------------------------------+--------------+
       |                                           |
       v                                           v
+---------------+                      +---------------------+
| Short-term    |                      | Long-term Memory    |
| Memory        |                      | (SQLite)            |
| (LangGraph    |                      | core/memory_        |
|  Checkpointer)|                      | manager.py          |
+---------------+                      +---------------------+
       |
       v
+------------------------------------------------------------------+
|                      AI Models (utils/)                          |
|    Deepseek (planner)  |  Kimi (search)  |  Qwen (summarizer)   |
+------------------------------------------------------------------+
       |
       v
+------------------------------------------------------------------+
|               InstallationLogger (core/logger.py)               |
|               logs/installation_YYYYMMDD_HHMMSS.md              |
+------------------------------------------------------------------+
```

### 完整目录结构

```
auto_install_v2/
├── main.py                          # CLI 入口
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
│   ├── agent.py                     # [NEW] LangGraph StateGraph Agent 主体
│   ├── installer.py                 # [REFACTOR] 对外接口，内部委托给 agent.py
│   ├── history_manager.py           # 短期历史管理（auto-summarize at 6 rounds）
│   ├── memory_manager.py            # [NEW] 长期记忆（SQLite CRUD + 相关性检索）
│   └── logger.py                    # Markdown 日志生成
│
├── utils/
│   ├── __init__.py
│   ├── deepseek.py                  # Deepseek API 封装（streaming + retry）
│   ├── qwen.py                      # Qwen API 封装（用于历史摘要 + 相关性判断）
│   ├── kimi_search.py               # Kimi Web 搜索封装
│   ├── text_processors.py           # 文本提取工具（辅助用）
│   └── get_system_summary.py        # 系统环境检测
│
├── prompt/
│   └── prompt.py                    # 所有 prompt 模板集中管理
│
├── tools/
│   ├── __init__.py
│   └── install_tools.py             # [NEW] LangChain Tool 定义（search/execute/finish）
│
├── tests/
│   ├── unit/
│   │   ├── test_text_processors.py
│   │   ├── test_history_manager.py
│   │   └── test_memory_manager.py
│   └── integration/
│       ├── test_agent_loop.py
│       └── test_tool_calling.py
│
└── logs/                            # 运行时生成，不提交 git
    ├── installation_*.md
    └── history_*.json
```

### 模块职责说明

| 模块 | 职责 | 关键类/函数 |
|------|------|------------|
| `main.py` | CLI 参数解析、配置加载、启动入口 | `main()`, `interactive_config()` |
| `config/enhanced_config.py` | 三优先级配置加载、字段校验、序列化 | `EnhancedConfig`, `AIModelConfig` |
| `core/agent.py` | LangGraph StateGraph 定义，节点函数，条件路由 | `build_graph()`, `plan_node()`, `execute_node()`, `AgentState` |
| `core/installer.py` | 对外接口，兼容旧调用方式，委托给 agent.py | `AutoInstaller.install_software()` |
| `core/history_manager.py` | 会话内历史管理，超 6 轮自动 AI 摘要，保留最近 2 轮 | `HistoryManager`, `summarize_old_entries()` |
| `core/memory_manager.py` | 跨会话长期记忆，安装成功后入库，启动前检索相关记录 | `MemoryManager`, `save_installation()`, `retrieve_relevant()` |
| `core/logger.py` | 结构化 Markdown 日志输出 | `InstallationLogger` |
| `tools/install_tools.py` | LangChain Tool 定义（search/execute/finish） | `SearchTool`, `ExecuteTool`, `FinishTool` |
| `utils/deepseek.py` | Deepseek API 调用，支持 streaming 和指数退避重试 | `Deepseek.chat()`, `Deepseek.stream_chat()` |
| `utils/kimi_search.py` | Kimi Web 搜索，tool_calls 循环处理 | `KimiSearch.get_search_res()` |
| `utils/qwen.py` | Qwen API，用于低成本摘要和相关性判断 | `QueryTongyi.chat()` |
| `utils/get_system_summary.py` | OS/GPU/CPU/包管理器检测，返回格式化字符串 | `get_system_summary()` |
| `utils/text_processors.py` | 正则提取辅助工具（主流程已改用 Tool Calling） | `TextProcessor`（静态方法） |
| `prompt/prompt.py` | 所有 prompt 模板集中管理 | `prompt_plan`, `prompt_summarize` |

### 数据流说明

```
用户输入: python main.py --install "docker"
    |
    v
[1] 系统环境检测 get_system_summary()
    -> OS: macOS 14, pkg: brew, conda, sudo: yes, GPU: None

[2] 长期记忆检索 memory_manager.retrieve_relevant("docker")
    -> 返回历史安装记录（若有），注入 AgentState.memory_context

[3] LangGraph 启动 graph.invoke({messages, system_info, memory_context})

[4] planner_node: Deepseek.chat(prompt_plan.format(...))
    -> Tool Call: {tool: "search", query: "docker install macOS brew 2024"}

[5] search_node: KimiSearch.get_search_res(query)
    -> 返回安装文档摘要，写回 AgentState.messages

[6] planner_node: Deepseek.chat(prompt + search_result)
    -> Tool Call: {tool: "execute", code: "import subprocess\n...brew install docker..."}

[7] execute_node: subprocess.Popen(code)
    -> stdout: "==> Installing docker...", returncode: 0

[8] checker_node: 检查执行结果
    -> returncode == 0 -> 继续或完成
    -> returncode != 0 -> 返回 planner 重试

[9] planner_node: Tool Call: {tool: "finish"}
    -> 触发 END，退出循环

[10] 安装成功后:
    memory_manager.save_installation(software="docker", steps=history, success=True)
    logger.log_completion()
```

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
        "code_execution_timeout_seconds": 120
    },
    "logging": {
        "log_directory": "logs",
        "enable_markdown_logs": true
    }
}
```

---

## 6. 项目排期

### 阶段划分

```
Phase 0 (完成) --> Phase 1 --> Phase 2 --> Phase 3
基础功能已实现   LangGraph    长期记忆    测试 + 打磨
  [当前状态]      重构         系统        工程质量
                 [P0 核心]   [P0 亮点]   [P1 加分]
```

---

### Phase 1：LangGraph + Tool Calling 重构（预计 3 天）

**目标**：用 LangGraph StateGraph + Function Calling 替代手写 while 循环 + regex 解析

#### 子任务 1.1：定义 LangChain Tools

- **修改文件**：`tools/install_tools.py`（新建）
- **实现类/函数**：
  - `SearchTool(BaseTool)` — 调用 KimiSearch，输入为搜索词字符串
  - `ExecuteTool(BaseTool)` — 接收 Python 代码字符串，通过 subprocess 执行并返回结果
  - `FinishTool(BaseTool)` — 触发安装完成，输入为安装总结字符串
- **验收标准**：每个 Tool 可独立调用并返回预期格式，无副作用
- **测试方法**：`pytest tests/unit/test_tools.py`

#### 子任务 1.2：构建 LangGraph StateGraph

- **修改文件**：`core/agent.py`（新建）
- **实现类/函数**：
  - `AgentState(TypedDict)` — 状态字段：`messages`, `step_count`, `system_info`, `memory_context`, `last_tool_result`
  - `plan_node(state: AgentState) -> AgentState` — 调用 Deepseek，返回包含 tool_call 的 AIMessage
  - `route_action(state: AgentState) -> str` — 条件路由，返回 "search" / "execute" / "finish"
  - `search_node(state: AgentState) -> AgentState` — 执行搜索，ToolMessage 写回 messages
  - `execute_node(state: AgentState) -> AgentState` — 执行代码，结果写回 last_tool_result
  - `checker_node(state: AgentState) -> AgentState` — 检查执行结果，决定继续/完成/报错
  - `build_graph() -> CompiledGraph` — 组装并编译 StateGraph
- **验收标准**：`graph.invoke({"messages": [...], "system_info": "..."})` 能完整跑通 search -> execute -> finish 路径
- **测试方法**：Mock Deepseek 返回固定 tool_call，验证路由和状态转移

#### 子任务 1.3：接口兼容

- **修改文件**：`core/installer.py`
- **实现**：`install_software()` 内部改为调用 `build_graph().invoke()`，保持对 `main.py` 的接口不变
- **验收标准**：`python main.py --install "cmake"` 仍可正常运行，日志格式不变

**进度追踪**：
- [ ] 1.1 Tool 定义
- [ ] 1.2 StateGraph 构建
- [ ] 1.3 接口兼容

---

### Phase 2：长期记忆系统（预计 2 天）

**目标**：跨会话记忆成功的安装方法，下次安装同类软件时直接复用，减少重复搜索成本

#### 子任务 2.1：SQLite 存储设计

- **修改文件**：`core/memory_manager.py`（新建）
- **实现类/函数**：
  - `MemoryManager.__init__(db_path: str)` — 初始化 SQLite 连接，建表（若不存在）
  - `save_installation(software_name, computer_environment, user_query, installation_steps, success, error_message, session_id)` — 安装成功后入库
  - `retrieve_relevant(query: str, env: str, limit: int = 3) -> list[dict]` — 按软件名 LIKE 检索，按时间降序
  - `get_relevant_with_llm(query: str, candidates: list[dict]) -> list[dict]` — 调用 Qwen 判断候选记录相关性，过滤误匹配

- **数据表结构**：

```sql
CREATE TABLE IF NOT EXISTS installation_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    software_name TEXT NOT NULL,
    computer_environment TEXT,
    user_query TEXT,
    installation_steps TEXT,
    success INTEGER DEFAULT 1,
    error_message TEXT DEFAULT '',
    session_id TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_software_name ON installation_records(software_name);
```

- **验收标准**：安装 cmake 后，`retrieve_relevant("cmake")` 能返回该记录；`retrieve_relevant("docker")` 不返回 cmake 记录
- **测试方法**：`pytest tests/unit/test_memory_manager.py`（使用内存 SQLite `:memory:`）

#### 子任务 2.2：接入主流程

- **修改文件**：`core/agent.py`, `core/installer.py`
- **实现**：
  - `installer.py` 启动前调用 `memory_manager.retrieve_relevant(query)` 注入 `AgentState.memory_context`
  - `plan_node` 中将 `memory_context` 拼入 prompt
  - 安装成功（checker_node 判定完成）后调用 `memory_manager.save_installation(...)`
- **验收标准**：安装 cmake 两次，第二次日志中出现「找到历史安装记录」相关提示，且安装步骤数减少

**进度追踪**：
- [ ] 2.1 SQLite 存储
- [ ] 2.2 接入主流程

---

### Phase 3：测试 + 工程质量打磨（预计 2 天）

**目标**：覆盖核心路径，全量 Type Hints，为面试代码展示做准备

#### 子任务 3.1：单元测试

- **修改文件**：`tests/unit/test_text_processors.py`, `tests/unit/test_history_manager.py`, `tests/unit/test_memory_manager.py`
- **覆盖内容**：
  - TextProcessor：正则提取、边界输入（空字符串、格式错误）
  - HistoryManager：6 轮触发摘要、保留最近 2 轮、JSON 序列化
  - MemoryManager：CRUD、LIKE 检索、相关性过滤
- **验收标准**：`pytest tests/unit/ --cov=core --cov=utils` 覆盖率 >70%

#### 子任务 3.2：集成测试

- **修改文件**：`tests/integration/test_agent_loop.py`
- **实现**：Mock `Deepseek.chat()` 和 `KimiSearch.get_search_res()`，测试三条路由：
  - 纯搜索完成：search -> planner -> finish
  - 搜索 + 执行完成：search -> execute -> checker -> finish
  - 执行失败重试：execute -> checker -> planner -> execute -> finish
- **验收标准**：三条路由各有通过的测试用例，Mock 不调用真实 API

#### 子任务 3.3：Type Hints + Retry

- **修改文件**：`utils/deepseek.py`, `utils/kimi_search.py`, `core/agent.py`, `core/memory_manager.py`
- **实现**：
  - 所有公共函数添加完整 Type Hints（参数 + 返回值）
  - `tenacity.retry` 装饰器：`wait_exponential(min=1, max=10)`, `stop_after_attempt(3)`, 仅重试网络/超时异常
- **验收标准**：`mypy core/ utils/ --ignore-missing-imports` 无 error 级别报错

**进度追踪**：
- [ ] 3.1 单元测试
- [ ] 3.2 集成测试
- [ ] 3.3 Type Hints + Retry

---

## 附：改进优先级总览

| 优先级 | 改进点 | 涉及文件 | Phase |
|--------|--------|----------|-------|
| P0 | LangGraph 重构 Agent 主循环 | `core/agent.py`（新建） | 1 |
| P0 | Structured Tool Calling 替代 Regex | `tools/install_tools.py`（新建） | 1 |
| P0 | 长期记忆（Long-term Memory）系统 | `core/memory_manager.py`（新建） | 2 |
| P0 | 添加测试（当前零测试文件） | `tests/`（新建） | 3 |
| P1 | 全量 Type Hints | 所有 `core/`, `utils/` | 3 |
| P1 | 重试机制（tenacity 指数退避） | `utils/deepseek.py`, `utils/kimi_search.py` | 3 |
| P1 | Qwen 正式接入摘要流程 | `core/history_manager.py` | 2 |
| P1 | Streaming 输出 | `utils/deepseek.py`, `core/agent.py` | 3 |
| P2 | Rich CLI 美化 | `main.py` | 后续 |
| P2 | 向量检索长期记忆 | `core/memory_manager.py` | 后续 |
| P2 | 评估框架（提升 72% 通过率） | `tests/e2e/` | 后续 |
