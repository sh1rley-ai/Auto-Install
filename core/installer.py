"""
Main Installation Orchestrator
Coordinates the entire automated software installation process.
"""

import re
import json
import io
import sys
import subprocess
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

from .history_manager import HistoryManager
from .logger import InstallationLogger


class AutoInstaller:
    """
    Main class that orchestrates the automated software installation process.
    
    Integrates history management, logging, AI models, and search capabilities
    to provide a complete installation experience.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the auto installer.
        
        Args:
            config: Configuration dictionary containing API keys and settings
        """
        self.config = config
        
        # Initialize AI models and search
        self._initialize_models()
        
        # Initialize history and logging
        self.history_manager = HistoryManager(summarizer=self.deepseek)
        self.logger = InstallationLogger()
        
        # Installation state
        self.max_steps = 30
        self.current_step = 0
        self.installation_complete = False
        
    def _initialize_models(self):
        """Initialize AI models and search capabilities."""
        # Import here to avoid circular imports
        from utils.deepseek import Deepseek
        from utils.qwen import QueryTongyi
        from utils.kimi_search import KimiSearch
        from utils.get_system_summary import get_system_summary
        from prompt.prompt import prompt_search, prompt_plan
        
        self.deepseek = Deepseek(self.config['deepseek_api_key'])
        self.qwen = QueryTongyi()
        self.kimi_search = KimiSearch(self.config['kimi_api_key'])
        self.get_system_summary = get_system_summary
        self.prompt_search = prompt_search
        self.prompt_plan = prompt_plan
    
    def install_software(self, user_request: str) -> bool:
        """
        Main method to install software based on user request.
        
        Args:
            user_request: User's software installation request
            
        Returns:
            True if installation completed successfully, False otherwise
        """
        try:
            # Get system information
            system_info = self.get_system_summary()
            
            # Log initial request
            self.logger.log_user_request(user_request, system_info)
            self.history_manager.add_entry(
                "user_request", 
                user_request,
                {"system_info": system_info}
            )
            
            print(f"开始安装: {user_request}")
            print("=" * 50)
            print("系统信息:")
            print(system_info)
            print("=" * 50)
            
            # Main installation loop
            current_step_result = ""
            
            while self.current_step < self.max_steps and not self.installation_complete:
                self.current_step += 1
                
                # Get installation plan from AI
                plan_result = self._get_installation_plan(
                    user_request, 
                    current_step_result, 
                    system_info
                )
                
                if not plan_result:
                    self.logger.log_error("无法生成安装计划", f"步骤 {self.current_step}")
                    break
                
                plan, reasoning = plan_result
                
                # Log the plan
                self.logger.log_installation_plan(plan, self.current_step)
                self.history_manager.add_entry(
                    "installation_plan",
                    plan,
                    {"step": self.current_step, "reasoning": reasoning}
                )
                
                print(f"\n--- 第 {self.current_step} 步安装计划 ---")
                print(plan)
                
                # Check if installation is complete
                if "<安装完成>" in plan:
                    self.installation_complete = True
                    self.logger.log_completion(True, "安装成功完成")
                    print("\n✅ 安装完成！")
                    break
                
                # Execute the plan
                current_step_result = self._execute_plan(plan)
                
                print(f"\n--- 第 {self.current_step} 步执行结果 ---")
                print(current_step_result)
            
            # Handle max steps reached
            if self.current_step >= self.max_steps and not self.installation_complete:
                error_msg = f"达到最大步骤数 ({self.max_steps})，安装可能未完成"
                self.logger.log_error(error_msg)
                print(f"\n⚠️ {error_msg}")
                return False
            
            return self.installation_complete
            
        except Exception as e:
            error_msg = f"安装过程中发生错误: {str(e)}"
            self.logger.log_error(error_msg)
            print(f"\n❌ {error_msg}")
            return False
        
        finally:
            self._finalize_installation()
    
    def _get_installation_plan(self, user_request: str, step_result: str, system_info: str) -> Optional[Tuple[str, str]]:
        """
        Get installation plan from AI model.
        
        Args:
            user_request: Original user request
            step_result: Result from previous step
            system_info: System information
            
        Returns:
            Tuple of (plan, reasoning) or None if failed
        """
        try:
            # Get history context for AI
            history_context = self.history_manager.get_context_for_ai()
            
            # Format prompt
            prompt_formatted = self.prompt_plan.format(
                info=user_request,
                history=history_context,
                cur_step_res=step_result,
                env=system_info
            )
            
            # Get plan from AI
            result = self.deepseek.chat(prompt_formatted)
            
            if isinstance(result, tuple):
                plan, reasoning = result
            else:
                plan, reasoning = result, ""
            
            return plan, reasoning
            
        except Exception as e:
            print(f"获取安装计划失败: {e}")
            return None
    
    def _execute_plan(self, plan: str) -> str:
        """
        Execute the installation plan.
        
        Args:
            plan: Installation plan from AI
            
        Returns:
            Execution result string
        """
        try:
            # Check if plan contains search query
            search_queries = self._extract_search_queries(plan)
            if search_queries:
                return self._execute_search(search_queries[0])
            
            # Check if plan contains Python code
            python_code = self._extract_python_code(plan)
            if python_code:
                return self._execute_python_code(python_code)
            
            # If no specific action found, return the plan as context
            return f"计划内容: {plan}"
            
        except Exception as e:
            error_msg = f"执行计划时出错: {str(e)}"
            self.logger.log_error(error_msg, plan)
            return error_msg
    
    def _execute_search(self, query: str) -> str:
        """
        Execute search query.
        
        Args:
            query: Search query string
            
        Returns:
            Search results
        """
        try:
            self.logger.log_search_query(query)
            self.history_manager.add_entry("search_query", query, {"step": self.current_step})
            
            print(f"🔍 搜索: {query}")
            
            # Perform search
            search_result = self.kimi_search.get_search_res(query)
            
            # Log search result
            self.logger.log_search_result(query, search_result)
            self.history_manager.add_entry(
                "search_result", 
                search_result, 
                {"query": query, "step": self.current_step}
            )
            
            return f"搜索结果:\n{search_result}"
            
        except Exception as e:
            error_msg = f"搜索执行失败: {str(e)}"
            self.logger.log_error(error_msg, f"查询: {query}")
            return error_msg
    
    def _execute_python_code(self, code: str) -> str:
        """
        Execute Python code safely.
        
        Args:
            code: Python code to execute
            
        Returns:
            Execution result
        """
        try:
            print(f"🐍 执行代码:\n{code}")
            
            # Execute code
            stdout_content, stderr_content = self._safe_execute_code(code)
            
            # Log execution
            self.logger.log_code_execution(code, stdout_content, stderr_content, self.current_step)
            self.history_manager.add_entry(
                "code_execution",
                f"代码: {code}\n输出: {stdout_content}\n错误: {stderr_content}",
                {"step": self.current_step}
            )
            
            # Format result
            result_parts = []
            if stdout_content:
                result_parts.append(f"执行输出:\n{stdout_content[-500:]}")
            if stderr_content:
                result_parts.append(f"执行错误:\n{stderr_content}")
            
            return "\n".join(result_parts) if result_parts else "代码执行完成，无输出"
            
        except Exception as e:
            error_msg = f"代码执行失败: {str(e)}"
            self.logger.log_error(error_msg, f"代码: {code}")
            return error_msg
    
    def _safe_execute_code(self, code: str) -> Tuple[str, str]:
        """
        Safely execute Python code with proper isolation.
        
        Args:
            code: Python code to execute
            
        Returns:
            Tuple of (stdout, stderr)
        """
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        
        # Create safe execution environment
        exec_globals = {
            '__builtins__': __builtins__,
            'subprocess': subprocess,
            'os': __import__('os'),
            'sys': sys,
            'Path': __import__('pathlib').Path
        }
        
        # Backup original stdout/stderr
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        
        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            exec(code, exec_globals)
        except Exception as e:
            print(f"执行代码时出错: {e}", file=sys.stderr)
        finally:
            # Restore original stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr
        
        return stdout_capture.getvalue(), stderr_capture.getvalue()
    
    def _extract_search_queries(self, text: str) -> List[str]:
        """Extract search queries from text."""
        pattern = r'<搜索词>(.*?)</搜索词>'
        return re.findall(pattern, text, re.DOTALL)
    
    def _extract_python_code(self, text: str) -> Optional[str]:
        """Extract Python code from text."""
        pattern = r'```python\s+(.*?)```'
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else None
    
    def _finalize_installation(self):
        """Finalize installation process with cleanup and summary."""
        try:
            # Save history
            history_file = f"logs/history_{self.logger.session_name}.json"
            self.history_manager.save_to_file(history_file)
            
            # Create summary
            summary_data = {
                'total_time': f"{self.current_step} 步骤",
                'successful_steps': self.current_step,
                'failed_steps': 0,  # Could be enhanced to track failures
                'search_count': len([h for h in self.history_manager.history if h['type'] == 'search_query']),
                'execution_count': len([h for h in self.history_manager.history if h['type'] == 'code_execution']),
                'history_file': history_file,
                'recommendations': '请检查日志文件以获取详细的安装过程记录。'
            }
            
            self.logger.create_summary_section(summary_data)
            
            print(f"\n📋 安装日志已保存到: {self.logger.get_log_file_path()}")
            print(f"📚 历史记录已保存到: {history_file}")
            
        except Exception as e:
            print(f"⚠️ 保存日志时出错: {e}")
    
    def get_installation_status(self) -> Dict[str, Any]:
        """Get current installation status."""
        return {
            'current_step': self.current_step,
            'max_steps': self.max_steps,
            'completed': self.installation_complete,
            'log_file': self.logger.get_log_file_path(),
            'history_entries': len(self.history_manager.history)
        }