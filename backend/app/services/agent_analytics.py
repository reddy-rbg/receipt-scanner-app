"""Receipt analytics routing helpers.

These functions decide whether a user message belongs to receipt analytics
mode: summaries, weekly/monthly reports, category breakdowns, shopping plans,
price memory, and repeat-item trends.
"""

from __future__ import annotations

import re


OVERVIEW_PHRASES = [
    "summary", "spending summary", "complete summary", "overview", "analyze spending", "analyse spending",
    "analyze my spending", "analyse my spending",
    "spending analysis", "spend analysis", "smart spending snapshot", "spending snapshot",
    "top 3 ways", "save money", "saving", "best value", "best store",
    "mostly purchased", "mostly purchase", "most purchased", "frequently",
    "what item i am frequently", "what items i am frequently",
    "what item am i frequently", "what items am i frequently",
    "frequently purchasing",
    "frequently purchased", "frequent purchases", "frequent items", "repeat items",
    "repeat purchases", "items purchased most", "products purchased most",
    "top spending", "spend the most", "spent the most", "spend most", "spent most",
    "store did i spend", "where did i spend", "which store did i spend",
    "monthly report", "monthly spending", "store breakdown", "best deals",
    "price trend", "price trends", "items i buy regularly", "buy regularly",
    "weekly", "week wise", "weekwise", "week graph", "weekly graph", "weekly spending",
    "week spending", "by week", "per week", "week report", "week wise graph",
    "this month", "monthly expenses", "monthly expense", "spent analysis",
    "expense analysis", "graph", "chart", "table", "items to purchase",
    "what should i buy", "shopping suggestions", "purchase this month", "shopping plan",
    "shopping", "next coming month", "coming month", "want i should",
    "least price", "lowest price of all", "cheapest item", "minimum price",
    "category", "categories", "categorize", "food receipts", "bank receipts",
    "hospital receipts", "medical receipts", "gardening receipts", "garden receipts",
    "tax", "taxes", "refund", "refunds", "return", "returns", "discount", "discounts",
    "recent receipts", "latest receipts", "last receipts", "store visits", "visit most",
    "where do i shop", "where i shop", "frequent store", "frequent stores",
    "price memory", "price dna", "good price", "is this a good price",
    "avoid price", "avoid above", "should i buy", "buy now", "wait to buy",
    "market price", "market prices", "current market", "overpaid", "over pay", "overpay",
]

WEEKLY_TERMS = [
    "weekly", "week wise", "weekwise", "week graph", "weekly graph",
    "weekly spending", "week spending", "by week", "per week", "week report",
    "week wise graph", "week wise spending", "i said week", "not month",
]

CATEGORY_SPENDING_TERMS = [
    "category wise", "category-wise", "category spending", "spending by category",
    "category breakdown", "category mix", "show categories", "categories spending",
    "categorize spending", "categorise spending",
]

MONTHLY_EXPENSE_TERMS = [
    "monthly expense", "monthly expenses", "monthly spending", "monthly report",
    "month expense", "month spending", "this month expense", "this month expenses",
    "this month spending", "show this month", "month report", "month wise", "month-wise",
]

REPEAT_PRICE_TREND_TERMS = [
    "price trend", "price trends", "buy regularly", "bought regularly",
    "items i buy regularly", "regular item", "regular items",
    "repeat purchase", "repeat purchases", "frequent items price",
    "mostly purchased", "mostly purchase", "most purchased",
    "what item i am frequently", "what items i am frequently",
    "what item am i frequently", "what items am i frequently",
    "frequently purchasing", "frequently purchased", "frequently bought",
    "frequent purchases", "frequent purchase", "frequent items",
    "frequently bought items", "frequently purchased items",
    "repeat items", "items purchased most", "items bought most",
    "item i bought most", "item i buy most", "items i bought most", "items i buy most", "buy most often",
    "bought most often", "most frequently bought", "most frequently purchased",
    "most bought items", "most purchased items", "most common purchases",
    "top bought items", "top purchased items", "top purchases",
    "top products", "top purchased products", "top products purchased", "top products i purchased",
    "products purchased most", "products bought most", "frequent products",
]


def looks_like_overview_question(message: str, *, normalize_text, correct_query_words) -> bool:
    text = correct_query_words(normalize_text(message))
    return any(re.search(rf"\b{re.escape(phrase)}\b", text) for phrase in OVERVIEW_PHRASES)


def looks_like_weekly_question(message: str, *, normalize_text) -> bool:
    text = normalize_text(message)
    return any(term in text for term in WEEKLY_TERMS)


def looks_like_category_spending_question(message: str, *, normalize_text) -> bool:
    text = normalize_text(message)
    return any(term in text for term in CATEGORY_SPENDING_TERMS)


def looks_like_monthly_expense_question(message: str, *, normalize_text) -> bool:
    text = normalize_text(message)
    return any(term in text for term in MONTHLY_EXPENSE_TERMS)


def looks_like_repeat_price_trend_question(message: str, *, normalize_text, correct_query_words) -> bool:
    text = correct_query_words(normalize_text(message))
    return any(term in text for term in REPEAT_PRICE_TREND_TERMS)
