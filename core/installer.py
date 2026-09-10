"""
Main Investigation Orchestrator
Coordinates one end-to-end run of the Plan-and-Execute agent graph.
"""

from typing import Any, Dict

from .history_manager import HistoryManager
from .logger import InstallationLogger

PLANNER_MODEL = "deepseek-reasoner"
EXECUTOR_MODEL = "deepseek-chat"


class DeployBot:
    """
    Main class that orchestrates one agent run.

    Delegates the actual Plan-and-Execute-and-Verify loop to the LangGraph
    parent graph (core.agent.build_graph); this class adapts that graph to the
    stable interface main.py expects (install_software / get_installation_status).
    Renamed to AMLGuard.investigate() in task 2.3.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize DeployBot.

        Args:
            config: Configuration dictionary containing API keys and settings
        """
        self.config = config

        # Initialize AI models and the agent tool sets
        self._initialize_models()

        # Initialize history and logging
        self.history_manager = HistoryManager(summarizer=self.executor_llm)
        self.logger = InstallationLogger()

        # Installation state
        self.max_steps = config.get('max_steps', 30)
        self.current_step = 0
        self.installation_complete = False

    def _initialize_models(self):
        """Initialize model clients and the tool sets exposed to the agent graph."""
        # Import here to avoid circular imports
        from utils.deepseek import Deepseek

        self.planner_llm = Deepseek(self.config['deepseek_api_key'], model=PLANNER_MODEL)
        self.executor_llm = Deepseek(self.config['deepseek_api_key'], model=EXECUTOR_MODEL)

        # No tools until MCP tools are bound in Phase 3. Two distinct dicts so the
        # Verifier never shares the Executor's tool set object: once real tools
        # land, the Verifier gets only the read-only subset.
        self.executor_tools: Dict[str, Any] = {}
        self.verifier_tools: Dict[str, Any] = {}

    def install_software(self, user_request: str) -> bool:
        """
        Run the agent graph for one request.

        Args:
            user_request: User's request text

        Returns:
            True if the run passed verification, False otherwise
        """
        try:
            from core.agent import build_graph

            # Replaced by case_context in task 2.1
            system_info = ""

            # Log initial request
            self.logger.log_user_request(user_request, system_info)
            self.history_manager.add_entry("user_request", user_request)

            print(f"开始处理: {user_request}")
            print("=" * 50)

            graph = build_graph(
                planner_llm=self.planner_llm,
                executor_llm=self.executor_llm,
                executor_tools=self.executor_tools,
                verifier_llm=self.executor_llm,
                verifier_tools=self.verifier_tools,
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
                print("\n[OK] 已完成并通过校验")
            else:
                failure_reason = verdict.get("failure_reason") or "未通过校验或已放弃"
                self.logger.log_error(f"未完成: {failure_reason}")
                print(f"\n[FAILED] 未完成: {failure_reason}")

            return self.installation_complete

        except Exception as e:
            error_msg = f"执行过程中发生错误: {str(e)}"
            self.logger.log_error(error_msg)
            print(f"\n[ERROR] {error_msg}")
            return False

        finally:
            self._finalize_installation()

    def _finalize_installation(self):
        """Finalize the run with cleanup and summary."""
        try:
            # Save history
            history_file = f"logs/history_{self.logger.session_name}.json"
            self.history_manager.save_to_file(history_file)

            # Create summary
            summary_data = {
                'total_time': f"{self.current_step} 步骤",
                'successful_steps': self.current_step,
                'failed_steps': 0,  # Could be enhanced to track failures
                'search_count': 0,
                'execution_count': 0,
                'history_file': history_file,
                'recommendations': '请检查日志文件以获取详细的执行过程记录。'
            }

            self.logger.create_summary_section(summary_data)

            print(f"\n日志已保存到: {self.logger.get_log_file_path()}")
            print(f"历史记录已保存到: {history_file}")

        except Exception as e:
            print(f"[WARN] 保存日志时出错: {e}")

    def get_installation_status(self) -> Dict[str, Any]:
        """Get current run status."""
        return {
            'current_step': self.current_step,
            'max_steps': self.max_steps,
            'completed': self.installation_complete,
            'log_file': self.logger.get_log_file_path(),
            'history_entries': len(self.history_manager.history)
        }
