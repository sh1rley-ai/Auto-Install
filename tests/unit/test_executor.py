import pytest

from core.executor import reason_node, route_tool, build_executor


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def chat(self, prompt):
        response = self.responses[self.calls]
        self.calls += 1
        return response, ""


def test_reason_node_parses_tool_call_decision():
    llm = FakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "brew install cmake"}}</action_json>'
    ])
    decision = reason_node(llm, "{goal}{system_info}{step_description}{executor_messages}", "cmake", "macos", "brew install cmake", [])

    assert decision == {"type": "tool_call", "tool": "run_shell", "args": {"command": "brew install cmake"}}


def test_reason_node_parses_finish_step_decision():
    llm = FakeLLM([
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "ok"}</action_json>'
    ])
    decision = reason_node(llm, "{goal}{system_info}{step_description}{executor_messages}", "cmake", "macos", "brew install cmake", [])

    assert decision == {"type": "finish_step", "status": "done", "result_summary": "ok"}


def test_reason_node_raises_on_missing_tag():
    llm = FakeLLM(["no tags here"])

    with pytest.raises(ValueError):
        reason_node(llm, "{goal}{system_info}{step_description}{executor_messages}", "cmake", "macos", "brew install cmake", [])


def test_route_tool_routes_to_tool_call():
    assert route_tool({"type": "tool_call", "tool": "run_shell", "args": {}}) == "tool_call"


def test_route_tool_routes_to_finish_step():
    assert route_tool({"type": "finish_step", "status": "done", "result_summary": ""}) == "finish_step"


def test_executor_node_clears_executor_messages_between_steps():
    llm = FakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "brew install cmake"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "ok"}</action_json>',
    ])
    tools = {"run_shell": lambda command: f"ran {command}, returncode 0"}
    executor = build_executor(llm, tools)
    state = {
        "goal": "cmake",
        "system_info": "macos",
        "plan": [{"id": 1, "description": "brew install cmake", "status": "pending", "result_summary": ""}],
        "current_step_id": 1,
        "executor_messages": ["stale from previous step"],
        "consecutive_failures": 0,
    }

    result = executor(state)

    assert result["executor_messages"] == []
    assert result["plan"][0]["status"] == "done"
    assert result["plan"][0]["result_summary"] == "ok"
