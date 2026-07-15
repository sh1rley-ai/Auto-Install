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
- [ ] 1.5 接口兼容

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
