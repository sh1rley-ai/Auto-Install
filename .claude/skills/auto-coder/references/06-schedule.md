## 6. 项目排期

### 阶段划分

```
Phase 0 (完成) -> Phase 1 (完成) -> Phase 2 -> Phase 3 -> Phase 4 -> Phase 5 -> Phase 6
基础功能          Plan-and-Execute   领域建模   MCP Server  规则引擎   双记忆 +   测试 +
                  编排骨架           + 固定     模块化      + 双路合规  哈希链     Evals
                  [领域无关]         seed 数据                          审查留痕
                  [领域无关]         [P0]       [P0]        [P0]       [P0]      [P1]
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

**目标**：把领域无关骨架迁移到 AML 调查语义，建立案件模型、证据链与演示数据集

#### 子任务 2.1：状态与数据结构领域化

- **修改文件**：`core/plan.py`, `core/evidence.py`（新建）
- **实现**：
  - `PlanStep` 更名 `InvestigationStep`（字段不变，保留旧别名一版以便平滑迁移）
  - `AgentState`：`goal` -> `case: dict`，`system_info` -> `case_context: str`；新增 `evidence` / `rule_hits` / `report` 三个字段
  - `core/evidence.py`：`append_evidence(state, tool, args, result)` 分配 `E-XXX` id 并写入证据链；`resolve_refs(evidence, refs)` 解析引用；`check_closure(report, evidence)` 校验引用闭合
- **验收标准**：证据 id 单调递增不重复；引用不存在的 id 时 `check_closure` 返回失败明细
- **测试方法**：`pytest tests/unit/test_plan.py tests/unit/test_evidence.py`

#### 子任务 2.2：固定 seed 合成数据集

- **修改文件**：`data/schema.sql`, `data/generate_dataset.py`, `data/seed.json`, `data/DATASET.md`（均新建）
- **实现**：
  - SQLite 表：`transactions`（流水）/ `accounts`（账户档案）/ `watchlist`（名单）/ `adverse_media`（负面信息语料）/ `alerts`（预警线索）
  - `generate_dataset.py --seed <n>`：单一 seed 驱动全部随机源（`random.Random(seed)` + `numpy.random.default_rng(seed)`，不使用全局随机状态），生成正常账户群体后按比例注入可疑模式（拆分、高频跨境、快进快出、集中收付、名单关联、基线突变），每个注入模式同时写入 ground truth 标签
  - 为基线偏离规则专门构造两类样本：金额相对自身历史暴增但绝对值不触阈值的账户（考察漏报）、绝对流水大但符合自身历史的活跃账户（考察误报）
  - 生成产物 `aml_dataset.sqlite` 与 `eval/benchmark.jsonl` **提交进仓库**；`DATASET.md` 记录数据字典、各模式构造逻辑与文件 SHA256
  - 交易表建 `(account, timestamp)` 与 `(counterparty)` 索引，保证 90 天窗口调单与 180 天基线计算响应在秒级
  - `--verify` 模式：重新生成到临时库并与仓库内文件比对校验和
- **验收标准**：同一 seed 两次生成校验和一致；`--verify` 通过；抽样案件的 ground truth 与注入模式对得上
- **测试方法**：`pytest tests/unit/test_data_layer.py`

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
- [ ] 2.1 状态与数据结构领域化
- [ ] 2.2 固定 seed 合成数据集
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
  - 基于公开反洗钱数据集构建约 200 条标注案件，按可疑模式（拆分 / 高频跨境 / 快进快出 / 集中收付 / 名单关联）分层抽样，含正常样本对照
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
| P0 | 领域建模重构（案件 / 证据链 / prompt / 接口） | `core/plan.py`, `core/evidence.py`, `prompt/`, `core/investigator.py` | 2 |
| P0 | 固定 seed 合成数据集（提交进仓库，保证评测可复现） | `data/` | 2 |
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
