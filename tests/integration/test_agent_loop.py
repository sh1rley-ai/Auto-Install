from core.agent import build_graph


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def chat(self, prompt):
        response = self.responses[self.calls]
        self.calls += 1
        return response, ""


def make_initial_state(goal="cmake", system_info="macos 14, brew available"):
    return {
        "goal": goal,
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


def test_full_plan_execute_verify_loop_succeeds():
    planner_llm = FakeLLM([
        '<plan_json>[{"id": 1, "description": "brew install cmake", "status": "pending", "result_summary": ""}]</plan_json>'
    ])
    executor_llm = FakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "brew install cmake"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "installed via brew"}</action_json>',
    ])
    verifier_llm = FakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "cmake --version"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "cmake version 3.30.0"}</action_json>',
    ])
    tools = {"run_shell": lambda command: "cmake version 3.30.0, returncode 0"}

    graph = build_graph(planner_llm, executor_llm, tools, verifier_llm, tools)
    result = graph.invoke(make_initial_state())

    assert result["plan"][0]["status"] == "done"
    assert result["verdict"]["passed"] is True
    assert result["verdict"]["evidence"] == "cmake version 3.30.0"


def test_full_loop_replans_after_verifier_rejects_then_succeeds():
    planner_llm = FakeLLM([
        '<plan_json>[{"id": 1, "description": "brew install --cask docker", "status": "pending", "result_summary": ""}]</plan_json>',
        '<patch_json>[{"op": "add", "step": {"id": 2, "description": "open -a Docker and wait for daemon", "status": "pending", "result_summary": ""}}]</patch_json>',
    ])
    executor_llm = FakeLLM([
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "cask installed"}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "daemon started"}</action_json>',
    ])
    verifier_llm = FakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "docker --version"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "failed", "result_summary": "daemon not running"}</action_json>',
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "docker --version"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "Docker version 27.3.1"}</action_json>',
    ])
    tool_calls = {"count": 0}

    def run_shell(command):
        tool_calls["count"] += 1
        if tool_calls["count"] == 1:
            return "Cannot connect to the Docker daemon"
        return "Docker version 27.3.1"

    tools = {"run_shell": run_shell}

    graph = build_graph(planner_llm, executor_llm, tools, verifier_llm, tools)
    result = graph.invoke(make_initial_state(goal="docker"))

    assert result["verdict"]["passed"] is True
    assert result["replan_count"] == 1
    assert [step["id"] for step in result["plan"]] == [1, 2]
    assert all(step["status"] == "done" for step in result["plan"])
