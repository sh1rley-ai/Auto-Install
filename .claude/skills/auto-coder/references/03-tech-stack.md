## 3. 技术选型

### AI 模型

| 模型 | 用途 | 选型理由 |
|------|------|----------|
| **Deepseek-reasoner** | Planner（规划 / 重规划） | 推理能力强，支持 thinking 输出，适合全局多步规划决策 |
| **Deepseek-chat** | Executor（单步执行决策） | Tool Calling 稳定，单步决策不需要 reasoner 的成本 |
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
