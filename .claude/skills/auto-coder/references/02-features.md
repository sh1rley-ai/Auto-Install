## 2. 核心特点

| 特点 | 说明 |
|------|------|
| **Plan-and-Execute 架构** | Planner 生成结构化计划并维护计划状态（每步含 id / 描述 / 状态），Executor 按步执行；执行结果驱动 Planner 对计划增删改，动态重规划 |
| **Agent 执行闭环** | Executor 每步内部：CoT 推理决策 -> Tool Calling（search / shell / finish_step）-> 结果反馈驱动下一步；失败自动重试，连续失败触发重规划 |
| **环境感知** | 启动时自动探测 OS / 包管理器（brew / apt / yum）/ conda / sudo 权限 / GPU / CPU，注入规划上下文，同一软件在不同环境生成不同安装方案 |
| **模块化 MCP Server** | 环境探测、联网搜索、受控 shell 执行封装为标准 MCP 工具，通过 stdio 暴露，可被 Claude Desktop 等任意 MCP 客户端直接复用 |
| **双层记忆机制** | 短期：会话内历史超阈值自动触发 LLM 总结压缩；长期：安装成功后 LLM 蒸馏成功路径（剔除试错分支）存入 SQLite，跨会话复用 |
| **结构化日志与回放** | 每步记录 step_type / content / timestamp 的 JSONL 轨迹，支持失败归因分析与执行轨迹回放；同时输出人类可读 Markdown 报告 |
| **受控代码执行** | shell 命令经受控执行器运行：黑名单拦截、超时控制、stdout/stderr 全量捕获回传 |
| **量化评估** | 150 个真实 GitHub 工具测试集，端到端安装成功率 72% |

---
