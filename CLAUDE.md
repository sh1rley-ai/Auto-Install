# CLAUDE.md

## 快速启动

```bash
pip install -r requirements.txt
python main.py --install "cmake"
python main.py --show-config
```

## 开发规范

- **禁止硬编码 API Key**：所有密钥只能从 `config/user_config.json` 或环境变量（`DEEPSEEK_API_KEY`、`KIMI_API_KEY`）读取，不得出现在任何源代码文件中
- **禁止使用 emoji**：代码、注释、日志输出、文档均不得出现 emoji 字符
- **部署前主动进行安全审查**：检查代码中的漏洞

详细架构、技术选型、模块设计、项目排期见 [DEV_SPEC.md](DEV_SPEC.md)
