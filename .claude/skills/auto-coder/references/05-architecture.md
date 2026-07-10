## 5. 系统架构与模块设计

### 多 Agent 架构设计

#### 为什么是双 Agent 而不是更多

多 Agent 的拆分边界应当跟随「决策职责」而非「工具种类」：

- **Planner Agent**（Deepseek-reasoner）：唯一职责是维护计划——初始规划、根据执行反馈重规划（增 / 删 / 改步骤）。它看到的是全局：安装目标、环境信息、长期记忆、各步骤执行摘要
- **Executor Agent**（Deepseek + Tool Calling）：唯一职责是完成当前步骤——CoT 推理后选择工具（搜索 / shell 执行），观察结果决定重试或宣告本步完成 / 失败。它看到的是局部：当前步骤描述、本步内的执行历史
- 搜索、环境探测、shell 执行是**工具**（MCP Tools），不是 Agent——它们没有决策职责，拆成独立 Agent 只会增加通信开销和不确定性

这种拆分的收益：Planner 的上下文不被每步的 stdout/stderr 噪音污染，Executor 的上下文不需要携带完整全局历史，两侧 token 消耗和错误率同时下降。

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
    executor_messages: list       # Executor 当前步骤内的消息（步骤间清空）
    consecutive_failures: int     # 连续失败步数，触发重规划
    replan_count: int             # 重规划次数上限保护
    step_count: int               # 全局步数上限保护
```

#### 状态机结构

```python
graph = StateGraph(AgentState)
graph.add_node("planner", plan_node)          # 生成 / 修订计划
graph.add_node("executor", executor_subgraph) # 执行当前步骤（内部闭环）
graph.add_node("verifier", verify_node)       # 全部步骤完成后验证可用性
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

Executor 内部是一个子图（executor_subgraph），实现单步闭环：

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
│   ├── executor.py                  # [NEW] Executor 子图（单步闭环: reason -> tool -> observe）
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
│   └── prompt.py                    # 所有 prompt 模板集中管理（规划/执行/重规划/蒸馏）
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
| `core/agent.py` | 父图定义：Planner / Verifier / Memorize 节点与条件路由 | `build_graph()`, `plan_node()`, `verify_node()` |
| `core/executor.py` | Executor 子图：CoT 推理 -> 工具调用 -> 结果反馈闭环，单步重试 | `build_executor()`, `reason_node()`, `route_tool()` |
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
| `prompt/prompt.py` | prompt 模板集中管理 | `prompt_plan`, `prompt_replan`, `prompt_execute`, `prompt_distill` |
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

[8] verifier: run_shell("docker --version") -> 输出版本号 -> success

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
