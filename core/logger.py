"""
Installation Logger Module
Generates detailed markdown logs for each installation step.
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


class InstallationLogger:
    """
    Logs installation process to markdown files with structured format.
    """
    
    def __init__(self, log_dir: str = "logs", session_name: Optional[str] = None):
        """
        Initialize installation logger.
        
        Args:
            log_dir: Directory to store log files
            session_name: Custom session name, defaults to timestamp
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        if session_name is None:
            session_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        self.session_name = session_name
        self.log_file = self.log_dir / f"installation_{session_name}.md"
        self.step_counter = 0
        
        # Initialize log file
        self._initialize_log_file()
    
    def _initialize_log_file(self):
        """Initialize the markdown log file with header."""
        header = f"""# 软件安装日志

**会话名称**: {self.session_name}  
**开始时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**日志文件**: {self.log_file.name}

---

## 安装概览

本日志记录了自动化软件安装过程的详细步骤，包括：
- 用户需求分析
- 系统环境检测
- 搜索和规划过程
- 命令执行结果
- 错误处理和解决方案

---

## 安装步骤

"""
        
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write(header)
    
    def log_user_request(self, request: str, system_info: str):
        """Log initial user request and system information."""
        self.step_counter += 1
        
        content = f"""### 步骤 {self.step_counter}: 用户需求和系统信息

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: 用户需求

#### 用户安装需求
```
{request}
```

#### 系统环境信息
```
{system_info}
```

---

"""
        self._append_to_log(content)
    
    def log_search_query(self, query: str, reason: str = ""):
        """Log search query generation."""
        self.step_counter += 1
        
        content = f"""### 步骤 {self.step_counter}: 搜索查询生成

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: 搜索查询

#### 搜索查询
```
{query}
```

#### 生成原因
{reason if reason else "基于用户需求和系统环境生成搜索查询"}

---

"""
        self._append_to_log(content)
    
    def log_search_result(self, query: str, result: str):
        """Log search results."""
        self.step_counter += 1
        
        content = f"""### 步骤 {self.step_counter}: 搜索结果

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: 搜索结果

#### 搜索查询
```
{query}
```

#### 搜索结果
```
{result}
```

---

"""
        self._append_to_log(content)
    
    def log_installation_plan(self, plan: str, step_number: int):
        """Log installation plan generation."""
        self.step_counter += 1
        
        content = f"""### 步骤 {self.step_counter}: 安装计划 (第{step_number}步)

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: 安装计划

#### 生成的计划
```
{plan}
```

---

"""
        self._append_to_log(content)
    
    def log_code_execution(self, code: str, stdout: str, stderr: str, step_number: int):
        """Log code execution and results."""
        self.step_counter += 1
        
        # Truncate long outputs for readability
        stdout_display = stdout[-500:] if len(stdout) > 500 else stdout
        stderr_display = stderr[-500:] if len(stderr) > 500 else stderr
        
        content = f"""### 步骤 {self.step_counter}: 代码执行 (第{step_number}步)

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: 代码执行

#### 执行的代码
```python
{code}
```

#### 执行输出 (stdout)
```
{stdout_display}
{f"... (输出被截断，完整输出长度: {len(stdout)} 字符)" if len(stdout) > 500 else ""}
```

#### 错误输出 (stderr)
```
{stderr_display}
{f"... (错误输出被截断，完整输出长度: {len(stderr)} 字符)" if len(stderr) > 500 else ""}
```

#### 执行状态
{self._get_execution_status(stdout, stderr)}

---

"""
        self._append_to_log(content)
    
    def log_error(self, error_msg: str, context: str = ""):
        """Log error occurrence."""
        self.step_counter += 1
        
        content = f"""### 步骤 {self.step_counter}: 错误记录

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: 错误

#### 错误信息
```
{error_msg}
```

#### 错误上下文
{context if context else "无额外上下文信息"}

---

"""
        self._append_to_log(content)
    
    def log_completion(self, success: bool, final_message: str):
        """Log installation completion."""
        self.step_counter += 1
        
        status = "✅ 成功" if success else "❌ 失败"
        
        content = f"""### 步骤 {self.step_counter}: 安装完成

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: 安装完成  
**状态**: {status}

#### 最终消息
```
{final_message}
```

---

## 安装总结

**总步骤数**: {self.step_counter}  
**完成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**最终状态**: {status}

"""
        self._append_to_log(content)
    
    def log_custom_step(self, title: str, content: str, step_type: str = "自定义"):
        """Log custom step with flexible content."""
        self.step_counter += 1
        
        log_content = f"""### 步骤 {self.step_counter}: {title}

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**类型**: {step_type}

{content}

---

"""
        self._append_to_log(log_content)
    
    def _get_execution_status(self, stdout: str, stderr: str) -> str:
        """Determine execution status based on output."""
        if stderr and "error" in stderr.lower():
            return "❌ 执行出现错误"
        elif stderr and "warning" in stderr.lower():
            return "⚠️ 执行有警告"
        elif stdout or not stderr:
            return "✅ 执行成功"
        else:
            return "❓ 执行状态未知"
    
    def _append_to_log(self, content: str):
        """Append content to log file."""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(content)
    
    def get_log_file_path(self) -> str:
        """Get the path to the current log file."""
        return str(self.log_file)
    
    def create_summary_section(self, summary_data: Dict[str, Any]):
        """Add a summary section to the log."""
        content = f"""
## 详细统计

**总执行时间**: {summary_data.get('total_time', '未知')}  
**成功步骤**: {summary_data.get('successful_steps', 0)}  
**失败步骤**: {summary_data.get('failed_steps', 0)}  
**搜索次数**: {summary_data.get('search_count', 0)}  
**代码执行次数**: {summary_data.get('execution_count', 0)}

### 关键文件位置
- 日志文件: `{self.log_file}`
- 历史记录: `{summary_data.get('history_file', '未保存')}`

### 建议和注意事项
{summary_data.get('recommendations', '无特殊建议')}

---

*日志生成完成于 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""
        self._append_to_log(content)