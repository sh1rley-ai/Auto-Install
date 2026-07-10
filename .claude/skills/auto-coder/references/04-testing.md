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
