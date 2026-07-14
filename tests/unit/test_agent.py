from core.agent import build_planner, route_plan


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0

    def chat(self, prompt):
        response = self.responses[self.calls]
        self.calls += 1
        return response, ""


def test_plan_node_generates_initial_plan():
    llm = FakeLLM([
        '<plan_json>[{"id": 1, "description": "install cmake", "status": "pending", "result_summary": ""}]</plan_json>'
    ])
    planner = build_planner(llm)
    state = {"goal": "cmake", "system_info": "macos", "memory_context": "", "plan": [], "replan_count": 0}

    result = planner(state)

    assert result["plan"] == [{"id": 1, "description": "install cmake", "status": "pending", "result_summary": ""}]
    assert result["current_step_id"] == 1
    assert result["replan_count"] == 0


def test_plan_node_applies_replan_patch_on_reentry():
    llm = FakeLLM([
        '<patch_json>[{"op": "update", "id": 1, "status": "failed"}, '
        '{"op": "add", "step": {"id": 2, "description": "retry with sudo", "status": "pending", "result_summary": ""}}]</patch_json>'
    ])
    planner = build_planner(llm)
    state = {
        "goal": "docker",
        "plan": [{"id": 1, "description": "brew install docker", "status": "failed", "result_summary": "perm denied"}],
        "replan_count": 0,
        "verdict": {"failure_reason": "permission denied"},
        "consecutive_failures": 2,
    }

    result = planner(state)

    assert result["replan_count"] == 1
    assert result["consecutive_failures"] == 0
    assert [step["id"] for step in result["plan"]] == [1, 2]
    assert result["current_step_id"] == 2


def test_plan_node_does_not_mutate_input_state():
    llm = FakeLLM([
        '<plan_json>[{"id": 1, "description": "x", "status": "pending", "result_summary": ""}]</plan_json>'
    ])
    planner = build_planner(llm)
    state = {"goal": "cmake", "system_info": "", "memory_context": "", "plan": [], "replan_count": 0}

    planner(state)

    assert state["plan"] == []


def test_route_plan_execute_when_pending_steps():
    state = {"plan": [{"id": 1, "description": "x", "status": "pending", "result_summary": ""}], "replan_count": 0}
    assert route_plan(state) == "execute"


def test_route_plan_verify_when_all_done():
    state = {"plan": [{"id": 1, "description": "x", "status": "done", "result_summary": ""}], "replan_count": 0}
    assert route_plan(state) == "verify"


def test_route_plan_abort_when_replan_exceeded():
    state = {"plan": [{"id": 1, "description": "x", "status": "failed", "result_summary": ""}], "replan_count": 4}
    assert route_plan(state) == "abort"


def test_route_plan_abort_when_no_pending_and_not_all_done():
    state = {"plan": [{"id": 1, "description": "x", "status": "failed", "result_summary": ""}], "replan_count": 0}
    assert route_plan(state) == "abort"
