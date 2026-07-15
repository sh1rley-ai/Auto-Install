import json
import re

from core.plan import AgentState
from prompt.prompt import prompt_execute

DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_TOOL_ITERATIONS = 6


def _extract_json_block(text: str, tag: str):
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    if not match:
        raise ValueError(f"no <{tag}> block found in LLM output")
    return json.loads(match.group(1).strip())


def reason_node(llm, prompt_template, goal, system_info, step_description, executor_messages):
    """CoT reasoning step: ask the LLM to pick the next action for the current plan step.

    Returns a decision dict, either:
    - {"type": "tool_call", "tool": <name>, "args": {...}}
    - {"type": "finish_step", "status": "done"|"failed", "result_summary": "..."}
    """
    prompt_formatted = prompt_template.format(
        goal=goal,
        system_info=system_info,
        step_description=step_description,
        executor_messages=json.dumps(executor_messages, ensure_ascii=False),
    )
    content, _ = llm.chat(prompt_formatted)
    return _extract_json_block(content, "action_json")


def route_tool(decision: dict) -> str:
    return "finish_step" if decision.get("type") == "finish_step" else "tool_call"


def build_executor(
    llm,
    tools,
    prompt=None,
    fresh_context=True,
    max_retries: int = DEFAULT_MAX_RETRIES,
    max_tool_iterations: int = DEFAULT_MAX_TOOL_ITERATIONS,
):
    """Factory producing an executor_node bound to an LLM client and a tool set.

    Shared by Executor and Verifier (task 1.4): passing prompt_verify, a read-only
    tools map, and fresh_context=True yields the verifier_subgraph from the same code.

    llm must expose .chat(prompt) -> (content, reasoning_content).
    tools is a dict[str, Callable[..., str]] mapping tool name to a callable that
    takes the decision's args as keyword arguments and returns an observation string.
    """
    prompt_template = prompt or prompt_execute

    def executor_node(state: AgentState) -> AgentState:
        new_state = dict(state)
        plan = [dict(step) for step in new_state["plan"]]
        current_id = new_state["current_step_id"]
        step = next(s for s in plan if s["id"] == current_id)
        step["status"] = "running"

        messages = [] if fresh_context else list(new_state.get("executor_messages", []))

        decision = {"type": "finish_step", "status": "failed", "result_summary": "exceeded max tool iterations"}
        for _ in range(max_tool_iterations):
            decision = reason_node(
                llm,
                prompt_template,
                goal=new_state.get("goal", ""),
                system_info=new_state.get("system_info", ""),
                step_description=step["description"],
                executor_messages=messages,
            )
            if route_tool(decision) == "finish_step":
                break

            tool_name = decision["tool"]
            args = decision.get("args", {})
            observation = tools[tool_name](**args)
            messages.append({"tool": tool_name, "args": args, "observation": observation})

        step["status"] = decision.get("status", "failed")
        step["result_summary"] = decision.get("result_summary", "")

        new_state["plan"] = plan
        new_state["consecutive_failures"] = (
            0 if step["status"] == "done" else new_state.get("consecutive_failures", 0) + 1
        )
        new_state["executor_messages"] = []  # cleared between steps to avoid context pollution
        return new_state

    return executor_node


def route_step_result(state: AgentState, max_retries: int = DEFAULT_MAX_RETRIES) -> str:
    plan = state.get("plan", [])
    current_id = state.get("current_step_id")
    step = next((s for s in plan if s["id"] == current_id), None)

    if step is None:
        return "replan"
    if step["status"] == "done":
        return "next_step"
    if state.get("consecutive_failures", 0) >= max_retries:
        return "replan"
    return "retry"
