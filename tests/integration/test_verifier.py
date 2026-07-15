from core.agent import build_verifier, route_verify


class RecordingFakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.prompts = []

    def chat(self, prompt):
        self.prompts.append(prompt)
        response = self.responses[self.calls]
        self.calls += 1
        return response, ""


def make_state():
    return {
        "goal": "docker",
        "system_info": "macos",
        "plan": [{"id": 1, "description": "brew install docker", "status": "done", "result_summary": "SECRET_INSTALL_TRACE"}],
        "current_step_id": 1,
        "executor_messages": ["SECRET_MESSAGE"],
        "memory_context": "SECRET_MEMORY",
        "consecutive_failures": 0,
        "replan_count": 0,
    }


def test_verifier_passes_when_binary_verified():
    llm = RecordingFakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "docker --version"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "Docker version 27.3.1"}</action_json>',
    ])
    tools = {"run_shell": lambda command: "Docker version 27.3.1"}
    verifier = build_verifier(llm, tools)

    result = verifier(make_state())

    assert result["verdict"]["passed"] is True
    assert result["verdict"]["evidence"] == "Docker version 27.3.1"
    assert route_verify(result) == "success"


def test_verifier_fails_when_binary_not_in_path_despite_install_returning_zero():
    llm = RecordingFakeLLM([
        '<action_json>{"type": "tool_call", "tool": "run_shell", "args": {"command": "docker --version"}}</action_json>',
        '<action_json>{"type": "finish_step", "status": "failed", "result_summary": '
        '"command not found: docker, binary not in PATH despite install commands returning 0"}</action_json>',
    ])
    tools = {"run_shell": lambda command: "zsh: command not found: docker"}
    verifier = build_verifier(llm, tools)

    result = verifier(make_state())

    assert result["verdict"]["passed"] is False
    assert "PATH" in result["verdict"]["failure_reason"]
    assert route_verify(result) == "failed"


def test_verifier_does_not_see_installation_history_blank_context():
    llm = RecordingFakeLLM([
        '<action_json>{"type": "finish_step", "status": "done", "result_summary": "ok"}</action_json>',
    ])
    tools = {"run_shell": lambda command: "ok"}
    verifier = build_verifier(llm, tools)

    verifier(make_state())

    assert all("SECRET" not in prompt for prompt in llm.prompts)
