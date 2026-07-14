import json
import re

from core.plan import AgentState, apply_plan_patch
from prompt.prompt import prompt_plan, prompt_replan

DEFAULT_MAX_REPLANS = 3


def _extract_json_block(text: str, tag: str):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    if not match:
        raise ValueError(f"no <{tag}> block found in LLM output")
    return json.loads(match.group(1).strip())


def build_planner(llm, max_replans: int = DEFAULT_MAX_REPLANS):
    """Factory producing a plan_node bound to the given LLM client.

    llm must expose .chat(prompt) -> (content, reasoning_content), matching
    the Deepseek/Qwen wrapper interface used elsewhere in this project.
    """

    def plan_node(state: AgentState) -> AgentState:
        new_state = dict(state)

        if not new_state.get("plan"):
            prompt = prompt_plan.format(
                goal=new_state.get("goal", ""),
                system_info=new_state.get("system_info", ""),
                memory_context=new_state.get("memory_context", ""),
            )
            content, _ = llm.chat(prompt)
            new_state["plan"] = _extract_json_block(content, "plan_json")
            new_state["replan_count"] = new_state.get("replan_count", 0)
        else:
            failure_reason = new_state.get("verdict", {}).get("failure_reason", "")
            prompt = prompt_replan.format(
                goal=new_state.get("goal", ""),
                plan=json.dumps(new_state["plan"], ensure_ascii=False),
                failure_reason=failure_reason,
            )
            content, _ = llm.chat(prompt)
            patch = _extract_json_block(content, "patch_json")
            new_state["plan"] = apply_plan_patch(new_state["plan"], patch)
            new_state["replan_count"] = new_state.get("replan_count", 0) + 1
            new_state["consecutive_failures"] = 0

        pending = [step for step in new_state["plan"] if step["status"] == "pending"]
        new_state["current_step_id"] = pending[0]["id"] if pending else new_state.get("current_step_id", 0)
        return new_state

    return plan_node


def route_plan(state: AgentState, max_replans: int = DEFAULT_MAX_REPLANS) -> str:
    if state.get("replan_count", 0) > max_replans:
        return "abort"

    plan = state.get("plan", [])
    if any(step["status"] == "pending" for step in plan):
        return "execute"
    if plan and all(step["status"] == "done" for step in plan):
        return "verify"
    return "abort"
