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
