import json

from core.plan import AgentState
from prompt.prompt import prompt_execute
from utils.text_processors import extract_tagged_json

DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_TOOL_ITERATIONS = 6


def reason_node(llm, prompt_template, goal, system_info, step_description, executor_messages):
    """CoT reasoning step: ask the LLM to pick the next action for the current plan step.

    Returns a decision dict, either:
    - {"type": "tool_call", "tool": <name>, "args": {...}}
    - {"type": "finish_step", "status": "done"|"failed", "result_summary": "..."}

    Raises ValueError when the LLM output has no parsable <action_json> block.
    """
    prompt_formatted = prompt_template.format(
        goal=goal,
        system_info=system_info,
        step_description=step_description,
        executor_messages=json.dumps(executor_messages, ensure_ascii=False),
    )
    content, _ = llm.chat(prompt_formatted)
    return extract_tagged_json(content, "action_json")


def route_tool(decision: dict) -> str:
    return "finish_step" if decision.get("type") == "finish_step" else "tool_call"


def invoke_tool(tools, tool_name, args) -> str:
    """Run one tool call, turning caller-side mistakes into an observation string.

    A hallucinated tool name or mismatched arguments is an LLM error the LLM can
    fix on its next reasoning round, so it is fed back as an observation instead
    of raising and tearing down the whole graph.
    """
    if not isinstance(tool_name, str) or tool_name not in tools:
        available = ", ".join(sorted(tools)) or "(none)"
        return f"error: unknown tool {tool_name!r}, available tools: {available}"
    if not isinstance(args, dict):
        return f"error: args for tool {tool_name!r} must be a JSON object"
    try:
        return tools[tool_name](**args)
    except TypeError as e:
        return f"error: invalid arguments for tool {tool_name!r}: {e}"


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
            try:
                decision = reason_node(
                    llm,
                    prompt_template,
                    goal=new_state.get("goal", ""),
                    system_info=new_state.get("system_info", ""),
                    step_description=step["description"],
                    executor_messages=messages,
                )
            except ValueError as e:
                # Unparsable output fails this step so the normal retry/replan routing takes over.
                decision = {"type": "finish_step", "status": "failed", "result_summary": f"unparsable executor output: {e}"}
                break
            if route_tool(decision) == "finish_step":
                break

            tool_name = decision.get("tool")
            args = decision.get("args", {})
            observation = invoke_tool(tools, tool_name, args)
            messages.append({"tool": tool_name, "args": args, "observation": observation})

        step["status"] = decision.get("status", "failed")
        step["result_summary"] = decision.get("result_summary", "")

        new_state["plan"] = plan
        new_state["consecutive_failures"] = (
            0 if step["status"] == "done" else new_state.get("consecutive_failures", 0) + 1
        )
        new_state["executor_messages"] = []  # cleared between steps to avoid context pollution

        if step["status"] == "done":
            pending = [s for s in plan if s["status"] == "pending"]
            new_state["current_step_id"] = pending[0]["id"] if pending else current_id

        return new_state

    return executor_node


def route_step_result(state: AgentState, max_retries: int = DEFAULT_MAX_RETRIES) -> str:
    """Route after one executor_node call.

    executor_node advances current_step_id to the next pending step as soon as a
    step succeeds, so current_step_id at routing time points at one of:
    - a fresh "pending" step (previous step succeeded, more work queued)
      -> "next_step": loop back into the executor directly for that step
    - the just-finished "done" step (it was the last one, nothing left pending)
      -> "all_done": hand control back to the Planner so route_plan can verify
    - the just-failed "failed" step (executor_node never advances on failure)
      -> "retry" if under the retry ceiling, else "replan"
    """
    plan = state.get("plan", [])
    current_id = state.get("current_step_id")
    step = next((s for s in plan if s["id"] == current_id), None)

    if step is None:
        return "replan"
    if step["status"] == "pending":
        return "next_step"
    if step["status"] == "done":
        return "all_done"
    if state.get("consecutive_failures", 0) >= max_retries:
        return "replan"
    return "retry"
