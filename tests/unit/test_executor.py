import pytest

from core.executor import build_executor, invoke_tool, reason_node, route_step_result, route_tool


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
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


def make_step_state():
    return {
        "goal": "investigate alert A-1",
        "system_info": "",
        "plan": [{"id": 1, "description": "look up account", "status": "pending", "result_summary": ""}],
        "current_step_id": 1,
        "executor_messages": [],
        "consecutive_failures": 0,
    }


def test_invoke_tool_reports_unknown_tool_with_available_names():
    observation = invoke_tool({"lookup": lambda key: "ok"}, "run_shell", {"command": "ls"})

    assert observation.startswith("error: unknown tool 'run_shell'")
    assert "available tools: lookup" in observation


def test_invoke_tool_reports_unknown_tool_on_empty_tool_set():
    assert "available tools: (none)" in invoke_tool({}, "lookup", {})


def test_invoke_tool_reports_argument_mismatch():
    observation = invoke_tool({"lookup": lambda key: "ok"}, "lookup", {"account": "A1"})

    assert observation.startswith("error: invalid arguments for tool 'lookup'")


def test_invoke_tool_rejects_non_object_args_and_non_string_tool_name():
    tools = {"lookup": lambda: "ok"}

    assert "must be a JSON object" in invoke_tool(tools, "lookup", ["A1"])
    assert "unknown tool" in invoke_tool(tools, ["lookup"], {})
    assert "unknown tool" in invoke_tool(tools, None, {})


def test_executor_node_feeds_hallucinated_tool_error_back_and_recovers():
    llm = FakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "ls"}}</action_json>',
        '<action_json>{"type": "tool_call", "tool": "lookup", "args": {"key": "A1"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "found A1"}</action_json>',
    ])
    calls = []
    tools = {"lookup": lambda key: calls.append(key) or f"record {key}"}

    result = build_executor(llm, tools)(make_step_state())

    assert result["plan"][0]["status"] == "done"
    assert calls == ["A1"]
    assert "unknown tool 'run_shell'" in llm.prompts[1]


def test_executor_node_marks_step_failed_on_unparsable_output_and_routes_retry():
    llm = FakeLLM(["I should probably query something first"])

    result = build_executor(llm, {})(make_step_state())

    step = result["plan"][0]
    assert step["status"] == "failed"
    assert "unparsable executor output" in step["result_summary"]
    assert result["consecutive_failures"] == 1
    assert route_step_result(result) == "retry"
    assert llm.calls == 1
