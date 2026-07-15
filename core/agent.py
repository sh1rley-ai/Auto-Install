import json
import re

from core.executor import build_executor
from core.plan import AgentState, apply_plan_patch
from prompt.prompt import prompt_plan, prompt_replan, prompt_verify

DEFAULT_MAX_REPLANS = 3
DEFAULT_VERIFIER_MAX_TOOL_ITERATIONS = 4


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


def build_verifier(llm, tools, max_tool_iterations: int = DEFAULT_VERIFIER_MAX_TOOL_ITERATIONS):
    """Factory producing a verifier_node that reuses the Executor subgraph.

    Reuses build_executor with prompt_verify, a caller-supplied read-only tools map,
    and fresh_context=True so the Verifier never sees the installation's message
    history or plan (blank context) — this avoids self-grading bias, since the
    agent that performed the install would tend to grade its own work favorably.

    Writes the structured verdict {passed, evidence, failure_reason} into
    AgentState.verdict for the parent graph's route_verify / replan logic.
    """
    executor_node = build_executor(
        llm,
        tools,
        prompt=prompt_verify,
        fresh_context=True,
        max_tool_iterations=max_tool_iterations,
    )

    def verifier_node(state: AgentState) -> AgentState:
        verify_state = {
            "goal": state.get("goal", ""),
            "system_info": state.get("system_info", ""),
            "plan": [{
                "id": 1,
                "description": f"验证安装目标已正确安装并可用：{state.get('goal', '')}",
                "status": "pending",
                "result_summary": "",
            }],
            "current_step_id": 1,
            "executor_messages": [],
            "consecutive_failures": 0,
        }
        result = executor_node(verify_state)
        verified_step = result["plan"][0]
        passed = verified_step["status"] == "done"

        new_state = dict(state)
        new_state["verdict"] = {
            "passed": passed,
            "evidence": verified_step["result_summary"] if passed else "",
            "failure_reason": "" if passed else verified_step["result_summary"],
        }
        return new_state

    return verifier_node


def route_verify(state: AgentState) -> str:
    return "success" if state.get("verdict", {}).get("passed") else "failed"
