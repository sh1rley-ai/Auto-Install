from unittest.mock import MagicMock, patch

import core.installer
from core.installer import EXECUTOR_MODEL, PLANNER_MODEL, DeployBot


def make_final_state(passed=True):
    return {
        "goal": "cmake",
        "system_info": "",
        "plan": [{"id": 1, "description": "brew install cmake", "status": "done", "result_summary": "installed"}],
        "current_step_id": 1,
        "executor_messages": [],
        "verdict": (
            {"passed": True, "evidence": "cmake version 3.30.0", "failure_reason": ""}
            if passed
            else {"passed": False, "evidence": "", "failure_reason": "verification failed"}
        ),
        "consecutive_failures": 0,
        "replan_count": 0,
        "step_count": 1,
    }


def test_install_software_delegates_to_build_graph_and_returns_true_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    fake_compiled_graph = MagicMock()
    fake_compiled_graph.invoke.return_value = make_final_state(passed=True)

    installer = DeployBot({"deepseek_api_key": "x"})

    with patch("core.agent.build_graph", return_value=fake_compiled_graph) as fake_build_graph:
        success = installer.install_software("cmake")

    assert success is True
    fake_build_graph.assert_called_once()
    _, kwargs = fake_build_graph.call_args
    assert kwargs["planner_llm"] is installer.planner_llm
    assert kwargs["executor_llm"] is installer.executor_llm
    assert kwargs["executor_tools"] is installer.executor_tools
    assert kwargs["verifier_tools"] is installer.verifier_tools

    status = installer.get_installation_status()
    assert status["completed"] is True
    assert status["current_step"] == 1
    assert status["history_entries"] >= 1


def test_install_software_returns_false_when_verdict_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    fake_compiled_graph = MagicMock()
    fake_compiled_graph.invoke.return_value = make_final_state(passed=False)

    installer = DeployBot({"deepseek_api_key": "x"})

    with patch("core.agent.build_graph", return_value=fake_compiled_graph):
        success = installer.install_software("cmake")

    assert success is False
    assert installer.get_installation_status()["completed"] is False


def test_models_follow_tech_stack_roles():
    installer = DeployBot({"deepseek_api_key": "x"})

    assert installer.planner_llm.model == PLANNER_MODEL == "deepseek-reasoner"
    assert installer.executor_llm.model == EXECUTOR_MODEL == "deepseek-chat"


def test_no_shell_or_web_search_tools_and_verifier_does_not_share_executor_tool_set():
    installer = DeployBot({"deepseek_api_key": "x"})

    assert installer.executor_tools == {}
    assert installer.verifier_tools == {}
    assert installer.executor_tools is not installer.verifier_tools
    assert not hasattr(installer, "_run_shell_tool")
    assert not hasattr(installer, "_web_search_tool")
    assert not hasattr(core.installer, "subprocess")
