"""ReceiptAI agent workflow orchestration.

This module introduces a LangGraph-compatible workflow around the existing
deterministic ReceiptAI agent. The existing agent remains the source of truth
for receipt math, item matching, and evidence gates.
"""

import os
import time
from typing import Any, TypedDict

from app.services.agent_contracts import IntentPlan

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # LangGraph is optional at runtime; fallback stays deterministic.
    END = START = None
    StateGraph = None


WORKFLOW_ENABLED = os.getenv("AGENT_WORKFLOW_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
LANGGRAPH_AVAILABLE = StateGraph is not None
WORKFLOW_ENGINE = "langgraph" if LANGGRAPH_AVAILABLE else "deterministic"


class ReceiptAgentWorkflowState(TypedDict, total=False):
    message: str
    resolved_message: str
    conversation_history: list[dict]
    user_id: str | None
    guest_session_id: str | None
    understanding: dict
    intent_plan: IntentPlan
    action: str
    items: list[str]
    category: str
    result: dict
    workflow_trace: dict


def _workflow_trace(state: ReceiptAgentWorkflowState, stage: str, **extra: Any) -> dict:
    trace = dict(state.get("workflow_trace") or {})
    stages = list(trace.get("stages") or [])
    stages.append(stage)
    trace.update({
        "engine": WORKFLOW_ENGINE,
        "langgraph_available": LANGGRAPH_AVAILABLE,
        "stages": stages,
    })
    trace.update(extra)
    return trace


def prepare_state(state: ReceiptAgentWorkflowState) -> ReceiptAgentWorkflowState:
    from app.services import agent

    started = time.perf_counter()
    message = state.get("message") or ""
    history = state.get("conversation_history") or []
    resolved = agent.resolve_followup_message(message, history)
    intent_plan = agent.build_intent_plan(message, resolved, history)
    understanding = intent_plan.to_understanding()
    canonical = agent.canonicalize_message_with_understanding(resolved, understanding)
    items = agent.extract_shopping_list_items(resolved)
    action = agent.classify_receipt_action(resolved) or ""
    category = agent.category_with_include_from_message(resolved) or agent.broad_category_from_message(resolved, understanding) or ""

    next_state = dict(state)
    next_state.update({
        "resolved_message": resolved,
        "understanding": understanding,
        "intent_plan": intent_plan,
        "action": action,
        "items": items,
        "category": category,
        "workflow_trace": _workflow_trace(
            state,
            "prepare",
            intent=understanding.get("intent") or action or "unknown",
            canonical_message=canonical,
            extracted_items=items,
            category=category,
            intent_plan=intent_plan.trace(),
            prepare_ms=round((time.perf_counter() - started) * 1000, 2),
        ),
    })
    return next_state


def execute_state(state: ReceiptAgentWorkflowState) -> ReceiptAgentWorkflowState:
    from app.services import agent

    started = time.perf_counter()
    result = agent.run_agent(
        message=state.get("resolved_message") or state.get("message") or "",
        conversation_history=state.get("conversation_history") or [],
        user_id=state.get("user_id"),
        guest_session_id=state.get("guest_session_id"),
        intent_plan=state.get("intent_plan"),
        message_is_resolved=True,
    )
    next_state = dict(state)
    next_state.update({
        "result": result if isinstance(result, dict) else {"response": str(result), "tools_used": []},
        "workflow_trace": _workflow_trace(
            state,
            "execute",
            execute_ms=round((time.perf_counter() - started) * 1000, 2),
        ),
    })
    return next_state


def finalize_state(state: ReceiptAgentWorkflowState) -> ReceiptAgentWorkflowState:
    started = time.perf_counter()
    result = dict(state.get("result") or {})
    trace = dict(result.get("rag_trace") or {})
    trace["workflow"] = _workflow_trace(
        state,
        "finalize",
        finalize_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    result["rag_trace"] = trace

    next_state = dict(state)
    next_state.update({
        "result": result,
        "workflow_trace": trace["workflow"],
    })
    return next_state


def _run_deterministic_workflow(state: ReceiptAgentWorkflowState) -> ReceiptAgentWorkflowState:
    state = prepare_state(state)
    state = execute_state(state)
    return finalize_state(state)


def _build_langgraph_workflow():
    if StateGraph is None:
        return None

    graph = StateGraph(ReceiptAgentWorkflowState)
    graph.add_node("prepare", prepare_state)
    graph.add_node("execute", execute_state)
    graph.add_node("finalize", finalize_state)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "execute")
    graph.add_edge("execute", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


_LANGGRAPH_WORKFLOW = _build_langgraph_workflow() if WORKFLOW_ENABLED else None


def run_agent_workflow(
    message: str,
    conversation_history: list,
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> dict:
    """Run the ReceiptAI agent through the workflow wrapper."""
    if not WORKFLOW_ENABLED:
        from app.services import agent

        return agent.run_agent(message, conversation_history, user_id=user_id, guest_session_id=guest_session_id)

    state: ReceiptAgentWorkflowState = {
        "message": message,
        "conversation_history": conversation_history or [],
        "user_id": user_id,
        "guest_session_id": guest_session_id,
        "workflow_trace": {},
    }

    if _LANGGRAPH_WORKFLOW is not None:
        final_state = _LANGGRAPH_WORKFLOW.invoke(state)
    else:
        final_state = _run_deterministic_workflow(state)

    return final_state.get("result") or {"response": "I could not generate a response.", "tools_used": []}


def workflow_status() -> dict:
    return {
        "enabled": WORKFLOW_ENABLED,
        "engine": WORKFLOW_ENGINE,
        "langgraph_available": LANGGRAPH_AVAILABLE,
    }
