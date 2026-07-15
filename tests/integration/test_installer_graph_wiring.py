from unittest.mock import MagicMock, patch

from core.installer import AutoInstaller


def make_final_state(passed=True):
    return {
        "goal": "cmake",
        "system_info": "macos",
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

    installer = AutoInstaller({"deepseek_api_key": "x", "kimi_api_key": "y"})

    with patch("core.agent.build_graph", return_value=fake_compiled_graph) as fake_build_graph:
        success = installer.install_software("cmake")

    assert success is True
    fake_build_graph.assert_called_once()
    _, kwargs = fake_build_graph.call_args
    assert kwargs["executor_tools"] is installer.tools
    assert kwargs["verifier_tools"] is installer.tools

    status = installer.get_installation_status()
    assert status["completed"] is True
    assert status["current_step"] == 1
    assert status["history_entries"] >= 1


def test_install_software_returns_false_when_verdict_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    fake_compiled_graph = MagicMock()
    fake_compiled_graph.invoke.return_value = make_final_state(passed=False)

    installer = AutoInstaller({"deepseek_api_key": "x", "kimi_api_key": "y"})

    with patch("core.agent.build_graph", return_value=fake_compiled_graph):
        success = installer.install_software("cmake")

    assert success is False
    assert installer.get_installation_status()["completed"] is False


def test_run_shell_tool_captures_returncode_stdout_stderr():
    installer = AutoInstaller.__new__(AutoInstaller)  # skip __init__, avoid constructing real clients
    output = installer._run_shell_tool("echo hello")

    assert "returncode: 0" in output
    assert "hello" in output
