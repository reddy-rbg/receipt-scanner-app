"""ReceiptAI response architecture helpers.

This module owns the final answer contract:
- classify answer mode for traces
- require receipt evidence for receipt-fact claims
- keep general advice and aggregate analytics separate from receipt facts
"""

from __future__ import annotations

import re


RECEIPT_EVIDENCE_REQUIRED_INTENTS = {
    "adaptive_item_recovery",
    "agentic_tool_loop",
    "category_price",
    "category_price_with_includes",
    "item_price",
    "multi_item_price_from_classifier",
    "receipt_item_lookup",
    "receipt_missing_item_lookup",
    "shopping_list_price",
    "store_lookup",
}

RECEIPT_AGGREGATION_INTENTS = {
    "graph_memory",
    "monthly_report",
    "overview",
    "price_memory",
    "receipt_memory",
    "shopping_plan",
    "spending_summary",
}


def normalize_text(text: str | None) -> str:
    value = (text or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_query_item(message: str | None) -> str:
    text = normalize_text(message)
    stop_words = {
        "a", "an", "and", "any", "are", "at", "buy", "bought", "by",
        "did", "do", "does", "for", "from", "have", "i", "in", "is",
        "it", "me", "my", "of", "on", "or", "please", "price",
        "receipt", "receipts", "show", "the", "to", "was", "were",
        "what", "where", "which", "with",
    }
    tokens = [token for token in text.split() if token not in stop_words]
    return " ".join(tokens).strip()


def clean_item_query_for_display(query: str | None) -> str:
    return normalize_text(query)


def card_has_receipt_evidence(card: dict | None) -> bool:
    if not isinstance(card, dict):
        return False
    if card.get("receipt_id"):
        return True
    for row in card.get("rows") or card.get("items") or []:
        if evidence_row_is_receipt_backed(row):
            return True
    return False


def rag_trace(
    *,
    agent_mode: str = "receipt",
    intent: str,
    retrieval: str,
    original_message: str,
    normalized_query: str = "",
    evidence: list[dict] | None = None,
    retrieval_pipeline: dict | None = None,
    strict: bool = True,
    note: str = "",
) -> dict:
    evidence = evidence or []
    answer_mode = "receipt_fact"
    if agent_mode == "general" or intent == "general_advice" or retrieval.startswith("general"):
        answer_mode = "general_advice"
    elif intent in RECEIPT_AGGREGATION_INTENTS:
        answer_mode = "receipt_analytics"
    return {
        "architecture": "evidence_backed_hybrid_rag",
        "agent_architecture": "adaptive_agentic_hybrid_rag_multimodal_graph_memory",
        "answer_mode": answer_mode,
        "agent_mode": agent_mode,
        "intent": intent,
        "retrieval": retrieval,
        "original_message": original_message,
        "normalized_query": normalized_query,
        "evidence_count": len(evidence),
        "openable_evidence": any(row.get("openable") for row in evidence),
        "multimodal_evidence": any((row.get("multimodal") or {}).get("available") for row in evidence),
        "highlightable_evidence": any((row.get("multimodal") or {}).get("can_highlight_line") for row in evidence),
        "strict_receipt_grounding": strict,
        "retrieval_pipeline": retrieval_pipeline or {},
        "evidence": evidence,
        "note": note,
    }


def response_is_no_evidence_result(response: str | None) -> bool:
    text = normalize_text(response or "")
    return any(
        phrase in text
        for phrase in {
            "did not find",
            "do not see",
            "not found",
            "no clear",
            "could not find enough receipt data",
            "had trouble reading your receipt data",
        }
    )


def evidence_row_is_receipt_backed(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    return bool(
        row.get("receipt_id")
        or row.get("store")
        or row.get("date")
        or row.get("price")
        or row.get("line_price")
        or row.get("item")
        or row.get("item_original")
        or row.get("item_name_original")
    )


def result_has_receipt_evidence(result: dict) -> bool:
    trace_data = result.get("rag_trace") or {}
    evidence = trace_data.get("evidence") or []
    if any(evidence_row_is_receipt_backed(row) for row in evidence):
        return True
    return card_has_receipt_evidence(result.get("answer_card"))


def result_receipt_intent(result: dict) -> str:
    trace_data = result.get("rag_trace") or {}
    return str(trace_data.get("intent") or result.get("intent") or "")


def result_requires_receipt_evidence(result: dict) -> bool:
    trace_data = result.get("rag_trace") or {}
    intent = result_receipt_intent(result)
    if intent in RECEIPT_AGGREGATION_INTENTS:
        return False
    if str(trace_data.get("agent_mode") or "") == "general":
        return False
    if str(trace_data.get("retrieval") or "").startswith("general"):
        return False
    return intent in RECEIPT_EVIDENCE_REQUIRED_INTENTS


def safe_unverified_receipt_response(message: str, result: dict) -> str:
    query = clean_item_query_for_display(extract_query_item(message))
    if query and query != clean_item_query_for_display(message):
        return f"I could not verify {query} from your receipts, so I will not guess."
    return "I could not verify that from your receipts, so I will not guess."


def finalize_agent_result(result: dict, original_message: str) -> dict:
    """Final gate before an answer leaves the backend."""
    if not isinstance(result, dict):
        return result
    if not result_requires_receipt_evidence(result):
        return result
    if result_has_receipt_evidence(result) or response_is_no_evidence_result(result.get("response")):
        return result

    trace_data = dict(result.get("rag_trace") or {})
    trace_data["strict_receipt_grounding"] = True
    trace_data["evidence_gate_blocked"] = True
    existing_note = str(trace_data.get("note") or "")
    trace_data["note"] = (
        existing_note + " " if existing_note else ""
    ) + "Final evidence gate blocked an ungrounded receipt claim."
    result = dict(result)
    result["response"] = safe_unverified_receipt_response(original_message, result)
    result["answer_card"] = None
    result["tools_used"] = []
    result["rag_trace"] = trace_data
    return result
