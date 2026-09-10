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
