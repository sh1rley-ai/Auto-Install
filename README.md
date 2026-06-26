# 自动化软件安装助手 (Auto-Installer)

一个智能的命令行自动化软件安装程序，支持在Linux服务器和Mac电脑上自动安装各种软件。具有智能历史管理和详细日志记录功能。

## ✨ 主要特性

### 🧠 智能历史管理
- **自动历史总结**: 当对话历史超过6轮时，自动调用AI模型进行总结
- **智能上下文保持**: 保留前面的总结和最近2轮对话，确保上下文连贯性
- **历史持久化**: 自动保存历史记录到JSON文件

### 📋 详细日志记录
- **Markdown格式日志**: 生成结构化的安装日志文件
- **步骤追踪**: 记录每个安装步骤的详细信息
- **错误记录**: 完整记录错误信息和解决过程
- **执行结果**: 保存所有命令执行的输出和错误信息

### 🤖 AI驱动的安装
- **多模型支持**: 集成Deepseek、Qwen、Kimi等AI模型
- **智能搜索**: 自动搜索最新的安装方法和解决方案
- **自适应执行**: 根据系统环境自动调整安装策略

### 🔧 系统兼容性
- **Linux支持**: 支持Ubuntu、CentOS、Fedora、Arch Linux等
- **Mac支持**: 完整支持macOS系统
- **包管理器检测**: 自动检测并使用合适的包管理器

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置API密钥

#### 方法1: 环境变量
```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
export KIMI_API_KEY="your_kimi_api_key"
```

#### 方法2: 配置文件
创建 `config/user_config.json`:
```json
{
  "ai_models": {
    "deepseek_api_key": "your_deepseek_api_key",
    "kimi_api_key": "your_kimi_api_key"
  }
}
```

#### 方法3: 交互式配置
首次运行时会自动提示进行配置。

### 基本使用

#### 交互式安装
```bash
python main.py
```

#### 直接安装指定软件
```bash
python main.py --install "cmake"
python main.py --install "docker"
python main.py --install "nodejs"
```

#### 使用自定义配置
```bash
python main.py --config config/my_config.json --install "python3.11"
```

#### 查看配置信息
```bash
python main.py --show-config
```

## 📁 项目结构

```
auto_install/
├── main.py                 # 主入口文件
├── requirements.txt        # 依赖列表
├── README.md              # 项目说明
├── core/                  # 核心模块
│   ├── __init__.py
│   ├── history_manager.py # 历史管理
│   ├── logger.py          # 日志记录
│   └── installer.py       # 安装协调器
├── config/                # 配置管理
│   ├── __init__.py
│   ├── config.py          # 原始配置(兼容)
│   └── enhanced_config.py # 增强配置管理
├── utils/                 # 工具模块
│   ├── __init__.py
│   ├── deepseek.py        # Deepseek AI集成
│   ├── qwen.py            # Qwen AI集成
│   ├── kimi_search.py     # Kimi搜索集成
│   ├── get_system_summary.py # 系统信息检测
│   └── text_processors.py # 文本处理工具
├── prompt/                # AI提示词
│   ├── __init__.py
│   └── prompt.py          # 提示词模板
├── logs/                  # 日志文件目录
│   ├── installation_*.md  # 安装日志
│   └── history_*.json     # 历史记录
└── src/                   # 原始代码(兼容)
    └── ...
```

## 🔧 配置选项

### 历史管理配置
```json
{
  "history": {
    "max_history_rounds": 6,      // 最大历史轮数
    "keep_recent_rounds": 2,      // 保留最近轮数
    "enable_summarization": true, // 启用自动总结
    "save_history_to_file": true  // 保存历史到文件
  }
}
```

### 日志配置
```json
{
  "logging": {
    "log_directory": "logs",           // 日志目录
    "enable_markdown_logs": true,     // 启用Markdown日志
    "log_file_prefix": "installation", // 日志文件前缀
    "max_log_file_size_mb": 50        // 最大日志文件大小
  }
}
```

### 安装配置
```json
{
  "installation": {
    "max_installation_steps": 30,        // 最大安装步骤
    "enable_code_execution": true,       // 启用代码执行
    "enable_web_search": true,           // 启用网络搜索
    "search_timeout_seconds": 30,        // 搜索超时时间
    "code_execution_timeout_seconds": 300 // 代码执行超时时间
  }
}
```

## 📊 使用示例

### 安装CMake
```bash
$ python main.py --install "cmake"

🚀 开始安装: cmake
==================================================
系统信息:
操作系统: Darwin
节点名称: MacBook-Pro
操作系统版本: 23.1.0
机器类型: arm64
系统支持 Homebrew 包管理器
==================================================

--- 第 1 步安装计划 ---
<搜索词>macOS arm64 cmake 安装方法</搜索词>

🔍 搜索: macOS arm64 cmake 安装方法

--- 第 1 步执行结果 ---
搜索结果:
在macOS上安装CMake有几种方法...

--- 第 2 步安装计划 ---
```python
import subprocess
result = subprocess.run(['brew', 'install', 'cmake'], 
                       capture_output=True, text=True)
print(f"输出: {result.stdout}")
print(f"错误: {result.stderr}")
```

🐍 执行代码:
import subprocess
result = subprocess.run(['brew', 'install', 'cmake'], 
                       capture_output=True, text=True)
print(f"输出: {result.stdout}")
print(f"错误: {result.stderr}")

--- 第 2 步执行结果 ---
执行输出:
==> Downloading https://ghcr.io/v2/homebrew/core/cmake/manifests/3.27.7
==> Installing cmake
==> Pouring cmake--3.27.7.arm64_monterey.bottle.tar.gz
🍺  cmake was successfully installed!

--- 第 3 步安装计划 ---
<安装完成>

✅ 安装完成！

============================================================
📊 安装结果:
  - 状态: ✅ 成功
  - 总步骤数: 3
  - 日志文件: logs/installation_20240118_143022.md
  - 历史记录: 6 条
============================================================

🎉 软件 'cmake' 安装完成！
📋 详细安装日志已保存到: logs/installation_20240118_143022.md
```

### 生成的日志文件示例

```markdown
# 软件安装日志

**会话名称**: 20240118_143022  
**开始时间**: 2024-01-18 14:30:22  
**日志文件**: installation_20240118_143022.md

---

## 安装步骤

### 步骤 1: 用户需求和系统信息

**时间**: 2024-01-18 14:30:22  
**类型**: 用户需求

#### 用户安装需求
```
cmake
```

#### 系统环境信息
```
操作系统: Darwin
节点名称: MacBook-Pro
操作系统版本: 23.1.0
机器类型: arm64
系统支持 Homebrew 包管理器
```

### 步骤 2: 搜索查询生成

**时间**: 2024-01-18 14:30:23  
**类型**: 搜索查询

#### 搜索查询
```
macOS arm64 cmake 安装方法
```

### 步骤 3: 代码执行 (第2步)

**时间**: 2024-01-18 14:30:25  
**类型**: 代码执行

#### 执行的代码
```python
import subprocess
result = subprocess.run(['brew', 'install', 'cmake'], 
                       capture_output=True, text=True)
print(f"输出: {result.stdout}")
print(f"错误: {result.stderr}")
```

#### 执行输出 (stdout)
```
==> Downloading https://ghcr.io/v2/homebrew/core/cmake/manifests/3.27.7
==> Installing cmake
==> Pouring cmake--3.27.7.arm64_monterey.bottle.tar.gz
🍺  cmake was successfully installed!
```

#### 执行状态
✅ 执行成功
```

## 🛠️ 开发指南

### 添加新的AI模型

1. 在 `utils/` 目录下创建新的模型文件
2. 实现标准的 `chat()` 方法
3. 在 `core/installer.py` 中集成新模型

### 扩展文本处理功能

在 `utils/text_processors.py` 中添加新的提取方法:

```python
@staticmethod
def extract_custom_content(text: str) -> List[str]:
    """Extract custom content from text."""
    pattern = r'<custom>(.*?)</custom>'
    return re.findall(pattern, text, re.DOTALL)
```

### 自定义日志格式

继承 `InstallationLogger` 类并重写相关方法:

```python
from core.logger import InstallationLogger

class CustomLogger(InstallationLogger):
    def log_custom_step(self, content: str):
        # 自定义日志逻辑
        pass
```

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🙏 致谢

- [Deepseek](https://www.deepseek.com/) - AI模型支持
- [Kimi](https://kimi.moonshot.cn/) - 搜索功能支持
- [Qwen](https://tongyi.aliyun.com/) - AI模型支持


---

**注意**: 请确保您有足够的系统权限来安装软件，某些操作可能需要 `sudo` 权限。