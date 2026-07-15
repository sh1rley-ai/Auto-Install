import json
import re

from langgraph.graph import END, START, StateGraph

from core.executor import DEFAULT_MAX_RETRIES, build_executor, route_step_result
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
        plan = new_state.get("plan")

        if not plan:
            prompt = prompt_plan.format(
                goal=new_state.get("goal", ""),
                system_info=new_state.get("system_info", ""),
                memory_context=new_state.get("memory_context", ""),
            )
            content, _ = llm.chat(prompt)
            new_state["plan"] = _extract_json_block(content, "plan_json")
            new_state["replan_count"] = new_state.get("replan_count", 0)
        elif _needs_replan(new_state):
            failure_reason = new_state.get("verdict", {}).get("failure_reason", "")
            prompt = prompt_replan.format(
                goal=new_state.get("goal", ""),
                plan=json.dumps(plan, ensure_ascii=False),
                failure_reason=failure_reason,
            )
            content, _ = llm.chat(prompt)
            patch = _extract_json_block(content, "patch_json")
            new_state["plan"] = apply_plan_patch(plan, patch)
            new_state["replan_count"] = new_state.get("replan_count", 0) + 1
            new_state["consecutive_failures"] = 0
            new_state["verdict"] = {}  # stale failure_reason is now addressed by the patch
        else:
            # Re-entered via the "all_done" route with nothing to fix (no failed
            # step, no verifier failure_reason) — pass through untouched so
            # route_plan sees an all-done plan and sends the flow to the verifier.
            return new_state

        pending = [step for step in new_state["plan"] if step["status"] == "pending"]
        new_state["current_step_id"] = pending[0]["id"] if pending else new_state.get("current_step_id", 0)
        return new_state

    return plan_node


def _needs_replan(state: AgentState) -> bool:
    has_failed_step = any(step["status"] == "failed" for step in state.get("plan", []))
    # A non-empty verdict with passed != True means the verifier rejected the
    # install; don't key off failure_reason text — it may legitimately be empty.
    verdict = state.get("verdict", {})
    has_failure_verdict = bool(verdict) and not verdict.get("passed", False)
    return has_failed_step or has_failure_verdict


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


def memorize_node(state: AgentState) -> AgentState:
    """Distill and persist the successful installation path.

    Stub for Phase 1: core/memory_manager.py (long-term memory, SQLite CRUD +
    success-path distillation) is not implemented yet — that lands in Phase 3.
    For now this node is a no-op passthrough so the graph has a well-defined
    terminal node after a successful verification.
    """
    return dict(state)


def build_graph(
    planner_llm,
    executor_llm,
    executor_tools,
    verifier_llm,
    verifier_tools,
    max_replans: int = DEFAULT_MAX_REPLANS,
    max_retries: int = DEFAULT_MAX_RETRIES,
):
    """Assemble the Plan-and-Execute parent graph: planner -> executor -> verifier -> memorize.

    llm/tools are injected per role so callers can use different models (e.g.
    Deepseek-reasoner for planning, Deepseek-chat for execution/verification per
    the tech-stack spec) and different tool sets (verifier gets a read-only subset).
    """
    plan_node = build_planner(planner_llm, max_replans=max_replans)
    executor_node = build_executor(executor_llm, executor_tools, max_retries=max_retries)
    verifier_node = build_verifier(verifier_llm, verifier_tools)

    graph = StateGraph(AgentState)
    graph.add_node("planner", plan_node)
    graph.add_node("executor", executor_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("memorize", memorize_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges(
        "planner",
        lambda state: route_plan(state, max_replans=max_replans),
        {"execute": "executor", "verify": "verifier", "abort": END},
    )
    graph.add_conditional_edges(
        "executor",
        lambda state: route_step_result(state, max_retries=max_retries),
        {"next_step": "executor", "all_done": "planner", "replan": "planner", "retry": "executor"},
    )
    graph.add_conditional_edges(
        "verifier",
        route_verify,
        {"success": "memorize", "failed": "planner"},
    )
    graph.add_edge("memorize", END)

    return graph.compile()
