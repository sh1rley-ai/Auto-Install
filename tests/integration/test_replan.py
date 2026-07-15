from core.executor import build_executor, route_step_result


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def chat(self, prompt):
        response = self.responses[self.calls]
        self.calls += 1
        return response, ""


def make_state(consecutive_failures=0):
    return {
        "goal": "cmake",
        "system_info": "macos",
        "plan": [{"id": 1, "description": "brew install cmake", "status": "pending", "result_summary": ""}],
        "current_step_id": 1,
        "executor_messages": [],
        "consecutive_failures": consecutive_failures,
    }


def test_normal_route_all_done_after_last_step_succeeds():
    llm = FakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "brew install cmake"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "installed via brew"}</action_json>',
    ])
    tools = {"run_shell": lambda command: f"ran {command}, returncode 0"}
    executor = build_executor(llm, tools, max_retries=2)

    result = executor(make_state())

    assert result["consecutive_failures"] == 0
    assert route_step_result(result, max_retries=2) == "all_done"


def test_normal_route_next_step_when_another_step_still_pending():
    llm = FakeLLM([
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "installed via brew"}</action_json>',
    ])
    tools = {"run_shell": lambda command: f"ran {command}, returncode 0"}
    executor = build_executor(llm, tools, max_retries=2)
    state = {
        "goal": "cmake",
        "system_info": "macos",
        "plan": [
            {"id": 1, "description": "brew install cmake", "status": "pending", "result_summary": ""},
            {"id": 2, "description": "verify cmake --version", "status": "pending", "result_summary": ""},
        ],
        "current_step_id": 1,
        "executor_messages": [],
        "consecutive_failures": 0,
    }

    result = executor(state)

    assert result["current_step_id"] == 2
    assert route_step_result(result, max_retries=2) == "next_step"


def test_retry_route_when_failure_below_threshold():
    llm = FakeLLM([
        '<action_json>{"type": "finish_step", "status": "failed", "result_summary": "permission denied"}</action_json>'
    ])
    tools = {"run_shell": lambda command: "returncode 1"}
    executor = build_executor(llm, tools, max_retries=2)

    result = executor(make_state(consecutive_failures=0))

    assert result["consecutive_failures"] == 1
    assert route_step_result(result, max_retries=2) == "retry"


def test_replan_route_when_failure_reaches_threshold():
    llm = FakeLLM([
        '<action_json>{"type": "finish_step", "status": "failed", "result_summary": "still failing"}</action_json>'
    ])
    tools = {"run_shell": lambda command: "returncode 1"}
    executor = build_executor(llm, tools, max_retries=2)

    result = executor(make_state(consecutive_failures=1))

    assert result["consecutive_failures"] == 2
    assert route_step_result(result, max_retries=2) == "replan"
