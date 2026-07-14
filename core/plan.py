from typing import List, TypedDict


class PlanStep(TypedDict):
    id: int
    description: str
    status: str
    result_summary: str


class AgentState(TypedDict):
    goal: str
    system_info: str
    memory_context: str
    plan: List[PlanStep]
    current_step_id: int
    executor_messages: list
    verdict: dict
    consecutive_failures: int
    replan_count: int
    step_count: int


def apply_plan_patch(plan: List[PlanStep], patch: List[dict]) -> List[PlanStep]:
    """Apply a list of add/update/delete operations to a plan and return a new plan.

    Patch operations:
    - {"op": "add", "step": PlanStep}
    - {"op": "update", "id": int, ...fields to overwrite}
    - {"op": "delete", "id": int}

    The input plan is never mutated; a new list is returned.
    """
    result = [dict(step) for step in plan]
    index_by_id = {step["id"]: i for i, step in enumerate(result)}

    for operation in patch:
        op = operation.get("op")

        if op == "add":
            step = operation["step"]
            step_id = step["id"]
            if step_id in index_by_id:
                raise ValueError(f"duplicate step id: {step_id}")
            index_by_id[step_id] = len(result)
            result.append(dict(step))

        elif op == "update":
            step_id = operation["id"]
            if step_id not in index_by_id:
                raise ValueError(f"step id out of range: {step_id}")
            i = index_by_id[step_id]
            fields = {k: v for k, v in operation.items() if k not in ("op", "id")}
            result[i].update(fields)

        elif op == "delete":
            step_id = operation["id"]
            if step_id not in index_by_id:
                raise ValueError(f"step id out of range: {step_id}")
            i = index_by_id[step_id]
            result.pop(i)
            index_by_id = {step["id"]: j for j, step in enumerate(result)}

        else:
            raise ValueError(f"unknown patch op: {op}")

    return result
