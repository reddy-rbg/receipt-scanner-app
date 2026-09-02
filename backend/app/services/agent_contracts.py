"""Stable contracts shared by ReceiptAI planning, execution, and rendering.

The raw user question is never replaced by this contract.  The plan describes
what should happen while preserving the original language for answer shaping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any


ITEM_ENTITY_META_WORDS = {
    "all", "best", "bought", "buy", "buying", "buys", "cheap", "cheapest",
    "complete", "cost", "entire", "find", "full", "history", "latest",
    "paid", "pay", "price", "prices", "purchase", "purchased", "purchases",
    "purchasing", "recent", "show", "total", "trend", "trends", "where", "when",
}


class AgentIntent(str, Enum):
    ITEM_LOOKUP = "item_lookup"
    PURCHASE_DATE = "purchase_date"
    PURCHASE_COUNT = "purchase_count"
    BEST_PRICE = "best_price"
    PRICE_HISTORY = "price_history"
    MULTI_ITEM_PRICE = "multi_item_price"
    CATEGORY_PRICE = "category_price"
    GLOBAL_CHEAPEST = "global_cheapest"
    RECEIPT_ANALYTICS = "receipt_analytics"
    PRODUCT_KNOWLEDGE = "product_knowledge"
    GENERAL_ADVICE = "general_advice"
    HELP = "help"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentPlan:
    raw_message: str
    resolved_message: str
    intent: AgentIntent
    item_query: str = ""
    items: tuple[str, ...] = field(default_factory=tuple)
    category: str = ""
    is_receipt_question: bool = True
    planner_source: str = "deterministic"
    confidence: float = 1.0
    legacy_intent: str = ""

    def to_understanding(self) -> dict[str, Any]:
        """Compatibility adapter while legacy executors are retired."""
        return {
            "intent": self.legacy_intent or self.intent.value,
            "canonical_message": self.resolved_message,
            "item_query": self.item_query,
            "items": list(self.items),
            "category": self.category,
            "is_receipt_question": self.is_receipt_question,
            "intent_plan": self.intent.value,
            "planner_source": self.planner_source,
            "planner_confidence": self.confidence,
        }

    def trace(self) -> dict[str, Any]:
        data = asdict(self)
        data["intent"] = self.intent.value
        data["items"] = list(self.items)
        return data


def _normalized_tokens(message: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9]+", " ", (message or "").lower()).split())


def clean_item_entity(value: str) -> str:
    """Final plan-boundary guard: request language can never become a product."""
    tokens = re.sub(r"[^a-z0-9.]+", " ", (value or "").lower()).split()
    return " ".join(token for token in tokens if token not in ITEM_ENTITY_META_WORDS).strip()


def operation_from_understanding(message: str, understanding: dict[str, Any]) -> AgentIntent:
    """Map all old router labels into one stable intent vocabulary."""
    tokens = _normalized_tokens(message)
    legacy = str(understanding.get("intent") or "").lower()
    items = [str(item) for item in understanding.get("items") or [] if item]

    if "when" in tokens and tokens & {"buy", "bought", "purchase", "purchased", "paid"}:
        return AgentIntent.PURCHASE_DATE
    if tokens & {"count", "times", "often"} or {"how", "many"} <= tokens or legacy == "item_count":
        return AgentIntent.PURCHASE_COUNT
    if tokens & {"history", "trend", "trends"}:
        return AgentIntent.PRICE_HISTORY
    if len(items) >= 2:
        return AgentIntent.MULTI_ITEM_PRICE
    if legacy == "category_price":
        return AgentIntent.CATEGORY_PRICE
    if legacy == "global_cheapest":
        return AgentIntent.GLOBAL_CHEAPEST
    if legacy == "product_knowledge":
        return AgentIntent.PRODUCT_KNOWLEDGE
    if legacy == "general_advice":
        return AgentIntent.GENERAL_ADVICE
    if legacy == "help":
        return AgentIntent.HELP
    if legacy in {"spending_summary", "monthly_report", "shopping_plan", "store_compare"}:
        return AgentIntent.RECEIPT_ANALYTICS
    if legacy == "item_price":
        if tokens & {"best", "cheap", "cheapest", "cheaper", "lowest", "where"}:
            return AgentIntent.BEST_PRICE
        return AgentIntent.ITEM_LOOKUP
    return AgentIntent.UNKNOWN


def intent_plan_from_understanding(
    raw_message: str,
    resolved_message: str,
    understanding: dict[str, Any],
) -> IntentPlan:
    source = "semantic" if understanding.get("semantic_extraction") else "deterministic"
    confidence = float(understanding.get("semantic_confidence") or (1.0 if understanding else 0.0))
    cleaned_items = tuple(
        cleaned
        for item in understanding.get("items") or []
        if (cleaned := clean_item_entity(str(item)))
    )
    cleaned_item_query = clean_item_entity(str(understanding.get("item_query") or ""))
    if not cleaned_items and cleaned_item_query:
        cleaned_items = (cleaned_item_query,)
    return IntentPlan(
        raw_message=raw_message,
        resolved_message=resolved_message,
        intent=operation_from_understanding(resolved_message, understanding),
        item_query=cleaned_item_query,
        items=cleaned_items,
        category=str(understanding.get("category") or ""),
        is_receipt_question=bool(understanding.get("is_receipt_question", True)),
        planner_source=source,
        confidence=max(0.0, min(1.0, confidence)),
        legacy_intent=str(understanding.get("intent") or ""),
    )
