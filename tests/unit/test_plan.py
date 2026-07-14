import pytest

from core.plan import apply_plan_patch


def make_plan():
    return [
        {"id": 1, "description": "brew install cmake", "status": "pending", "result_summary": ""},
        {"id": 2, "description": "verify cmake --version", "status": "pending", "result_summary": ""},
    ]


def test_add_step_appends_new_step():
    plan = make_plan()
    patch = [{"op": "add", "step": {"id": 3, "description": "new step", "status": "pending", "result_summary": ""}}]

    result = apply_plan_patch(plan, patch)

    assert len(result) == 3
    assert result[2] == {"id": 3, "description": "new step", "status": "pending", "result_summary": ""}


def test_update_step_overwrites_only_given_fields():
    plan = make_plan()
    patch = [{"op": "update", "id": 1, "status": "done", "result_summary": "installed via brew"}]

    result = apply_plan_patch(plan, patch)

    assert result[0]["status"] == "done"
    assert result[0]["result_summary"] == "installed via brew"
    assert result[0]["description"] == "brew install cmake"


def test_delete_step_removes_it():
    plan = make_plan()
    patch = [{"op": "delete", "id": 1}]

    result = apply_plan_patch(plan, patch)

    assert len(result) == 1
    assert result[0]["id"] == 2


def test_update_out_of_range_id_raises():
    plan = make_plan()
    patch = [{"op": "update", "id": 999, "status": "done"}]

    with pytest.raises(ValueError):
        apply_plan_patch(plan, patch)


def test_delete_out_of_range_id_raises():
    plan = make_plan()
    patch = [{"op": "delete", "id": 999}]

    with pytest.raises(ValueError):
        apply_plan_patch(plan, patch)


def test_add_duplicate_id_raises():
    plan = make_plan()
    patch = [{"op": "add", "step": {"id": 1, "description": "dup", "status": "pending", "result_summary": ""}}]

    with pytest.raises(ValueError):
        apply_plan_patch(plan, patch)


def test_apply_plan_patch_does_not_mutate_input():
    plan = make_plan()
    original = [dict(step) for step in plan]
    patch = [{"op": "update", "id": 1, "status": "done"}]

    apply_plan_patch(plan, patch)

    assert plan == original


def test_apply_plan_patch_is_idempotent_when_reapplied_on_fresh_plan():
    plan = make_plan()
    patch = [{"op": "update", "id": 1, "status": "done", "result_summary": "ok"}]

    result_a = apply_plan_patch(plan, patch)
    result_b = apply_plan_patch(plan, patch)

    assert result_a == result_b


def test_multiple_operations_in_single_patch():
    plan = make_plan()
    patch = [
        {"op": "update", "id": 1, "status": "failed"},
        {"op": "delete", "id": 1},
        {"op": "add", "step": {"id": 3, "description": "retry step", "status": "pending", "result_summary": ""}},
    ]

    result = apply_plan_patch(plan, patch)

    ids = [step["id"] for step in result]
    assert ids == [2, 3]
