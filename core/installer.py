"""
Main Installation Orchestrator
Coordinates the entire automated software installation process.
"""

import subprocess
from typing import Any, Dict

from .history_manager import HistoryManager
from .logger import InstallationLogger

DEFAULT_SHELL_TIMEOUT_SECONDS = 120


class AutoInstaller:
    """
    Main class that orchestrates the automated software installation process.

    Delegates the actual Plan-and-Execute-and-Verify loop to the LangGraph
    parent graph (core.agent.build_graph); this class adapts that graph to the
    stable interface main.py expects (install_software / get_installation_status).
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
        """Initialize AI models, search, and the tool set exposed to the agent graph."""
        # Import here to avoid circular imports
        from utils.deepseek import Deepseek
        from utils.kimi_search import KimiSearch
        from utils.get_system_summary import get_system_summary

        self.deepseek = Deepseek(self.config['deepseek_api_key'])
        self.kimi_search = KimiSearch(self.config['kimi_api_key'])
        self.get_system_summary = get_system_summary

        # Plain-Python tool set for the Executor/Verifier subgraphs. Superseded
        # by mcp_server/ (Phase 2), which adds a shell command blacklist and
        # runs tools behind the MCP protocol instead of in-process callables.
        self.tools = {
            "web_search": self._web_search_tool,
            "run_shell": self._run_shell_tool,
        }

    def _web_search_tool(self, query: str) -> str:
        return self.kimi_search.get_search_res(query)

    def _run_shell_tool(self, command: str, timeout: int = DEFAULT_SHELL_TIMEOUT_SECONDS) -> str:
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return (
                f"returncode: {result.returncode}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        except subprocess.TimeoutExpired:
            return f"returncode: -1\nstdout:\nstderr:\ncommand timed out after {timeout}s"

    def install_software(self, user_request: str) -> bool:
        """
        Main method to install software based on user request.

        Args:
            user_request: User's software installation request

        Returns:
            True if installation completed successfully, False otherwise
        """
        try:
            from core.agent import build_graph

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

            graph = build_graph(
                planner_llm=self.deepseek,
                executor_llm=self.deepseek,
                executor_tools=self.tools,
                verifier_llm=self.deepseek,
                verifier_tools=self.tools,
            )

            initial_state = {
                "goal": user_request,
                "system_info": system_info,
                "memory_context": "",
                "plan": [],
                "current_step_id": 0,
                "executor_messages": [],
                "verdict": {},
                "consecutive_failures": 0,
                "replan_count": 0,
                "step_count": 0,
            }

            final_state = graph.invoke(initial_state, config={"recursion_limit": 100})

            plan = final_state.get("plan", [])
            self.current_step = len([step for step in plan if step["status"] in ("done", "failed")])

            for step in plan:
                self.logger.log_installation_plan(step["description"], self.current_step)
                self.history_manager.add_entry(
                    "installation_plan",
                    step["description"],
                    {"status": step["status"], "result_summary": step["result_summary"]}
                )

            verdict = final_state.get("verdict", {})
            self.installation_complete = bool(verdict.get("passed", False))

            if self.installation_complete:
                self.logger.log_completion(True, verdict.get("evidence", ""))
                print("\n✅ 安装完成！")
            else:
                failure_reason = verdict.get("failure_reason") or "未通过验证或已放弃"
                self.logger.log_error(f"安装未完成: {failure_reason}")
                print(f"\n❌ 安装未完成: {failure_reason}")

            return self.installation_complete

        except Exception as e:
            error_msg = f"安装过程中发生错误: {str(e)}"
            self.logger.log_error(error_msg)
            print(f"\n❌ {error_msg}")
            return False

        finally:
            self._finalize_installation()

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