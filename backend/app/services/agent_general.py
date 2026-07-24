"""General-advice mode for ReceiptAI.

This module handles non-receipt household, cooking, storage, nutrition, and
shopping-advice questions. It must not make claims about the user's receipt
history unless receipt facts are explicitly passed in by a caller.
"""

from __future__ import annotations

import re
from app.services.app_logger import get_logger

logger = get_logger(__name__)

GENERAL_ADVICE_TERMS = {
    "temperature", "heat", "heated", "cook", "cooking", "boil", "boiled",
    "bacteria", "safe", "safety", "storage", "store", "expire", "expired",
    "fresh", "freeze", "frozen", "thaw", "recipe", "prepare", "pasteurize",
    "pasteurized", "milk", "food", "eat", "drink", "healthy", "health",
    "nutrition", "nutritious", "basmati", "rice", "vegetable", "vegetables",
    "curry", "go", "goes", "meaning", "mean", "cheaper", "save",
}

PRODUCT_RELATION_TERMS = {
    "alias", "aliases", "called", "define", "definition", "difference",
    "different", "equivalent", "mean", "meaning", "means", "name",
    "same", "similar", "synonym", "synonyms", "versus", "vs",
}

RECEIPT_FACT_TERMS = {
    "receipt", "receipts", "bought", "buy", "purchase", "purchased",
    "price", "prices", "cheap", "cheapest", "cheaper", "lowest",
    "highest", "cost", "costs", "damage", "damages", "pay", "paid", "spend", "spent", "spending", "total",
}


GENERAL_KNOWLEDGE_SNIPPETS = [
    {
        "id": "boiled_eggs_timing",
        "title": "Boiled egg timing",
        "keywords": {"egg", "eggs", "boil", "boiled", "cook", "cooking", "soft", "hard"},
        "text": "Large eggs usually take 6-7 minutes for softer yolks and 9-12 minutes for firm yolks after the water reaches a simmer. Cooling in ice water stops carryover cooking and helps peeling.",
    },
    {
        "id": "cilantro_storage",
        "title": "Cilantro storage",
        "keywords": {"cilantro", "coriander", "store", "storage", "fresh", "keep", "herb", "herbs"},
        "text": "Cilantro keeps longer when stems are trimmed, placed upright in a jar with a little water, loosely covered, and refrigerated. Change the water every few days.",
    },
    {
        "id": "meat_freezing",
        "title": "Freezing meat",
        "keywords": {"meat", "freeze", "frozen", "freezing", "thaw", "storage"},
        "text": "Freeze meat tightly wrapped at 0 deg F / -18 deg C. Ground meat is best used within 3-4 months for quality; larger cuts often keep quality for 6-12 months.",
    },
    {
        "id": "milk_pasteurization",
        "title": "Milk pasteurization temperature",
        "keywords": {"milk", "temperature", "heat", "heated", "bacteria", "pasteurize", "pasteurized", "safe", "safety"},
        "text": "Common milk pasteurization references are 161 deg F / 72 deg C for 15 seconds or 145 deg F / 63 deg C for 30 minutes, followed by quick cooling and refrigeration. Pasteurization does not make spoiled milk safe.",
    },
    {
        "id": "basmati_rice",
        "title": "Basmati rice basics",
        "keywords": {"basmati", "rice", "what", "meaning", "mean", "cook", "curry", "biryani"},
        "text": "Basmati is a long-grain aromatic rice with a fluffy texture and nutty aroma. It is commonly used for biryani, pilaf, curries, and dal meals.",
    },
    {
        "id": "goat_meat_nutrition",
        "title": "Goat meat nutrition",
        "keywords": {"goat", "meat", "healthy", "health", "nutrition", "nutritious", "protein", "cook", "cooking", "recipe", "prepare"},
        "text": "Goat meat can be a lean protein choice compared with some red meats. For cooking, use moist heat or a pressure cooker for tougher cuts, season well, and cook until tender. Healthfulness still depends on portion size, cooking method, sodium, fat, and the overall meal pattern.",
    },
    {
        "id": "cheaper_grocery_shopping",
        "title": "Cheaper grocery shopping",
        "keywords": {"shopping", "grocery", "groceries", "cheaper", "save", "saving", "budget", "plan"},
        "text": "Cheaper grocery shopping usually comes from planning meals, comparing unit prices, buying sale items you will actually use, avoiding duplicates, and checking repeat-item price history before checkout.",
    },
    {
        "id": "vegetables_for_chicken_curry",
        "title": "Vegetables for chicken curry",
        "keywords": {"vegetable", "vegetables", "chicken", "curry", "go", "goes", "with"},
        "text": "Vegetables that work well with chicken curry include potato, carrot, peas, bell pepper, spinach, cauliflower, green beans, and eggplant. Quick-cooking vegetables should be added later.",
    },
]


def looks_like_product_knowledge_question(
    message: str,
    *,
    normalize_text,
    correct_item_typos,
    correct_query_words,
) -> bool:
    """Detect meaning/relationship questions before any receipt-item extraction.

    This intentionally uses language shape rather than a list of known groceries,
    so the router works for products that have never appeared in our alias table.
    """
    normalized = correct_item_typos(correct_query_words(normalize_text(message)))
    tokens = set(normalized.split())
    if not tokens or tokens & RECEIPT_FACT_TERMS:
        return False

    if tokens & PRODUCT_RELATION_TERMS:
        return True

    relation_patterns = (
        r"\b(?:is|are)\b.+\b(?:the\s+)?same\b",
        r"\b(?:what|which)\s+(?:is|are)\b",
        r"\bwhat\s+does\b.+\bmean\b",
        r"\b(?:another|other|regional|common)\s+name\b",
        r"\bknown\s+as\b",
    )
    return any(re.search(pattern, normalized) for pattern in relation_patterns)


def looks_like_general_advice_question(
    message: str,
    *,
    normalize_text,
    correct_item_typos,
    correct_query_words,
    broad_category_terms: set[str],
) -> bool:
    m = correct_item_typos(correct_query_words(normalize_text(message)))
    tokens = set(m.split())
    if not tokens:
        return False
    if looks_like_product_knowledge_question(
        message,
        normalize_text=normalize_text,
        correct_item_typos=correct_item_typos,
        correct_query_words=correct_query_words,
    ):
        return True
    if (tokens & broad_category_terms) and (
        tokens & {"where", "show", "tell", "find", "cheap", "cheapest", "best", "bought", "buy", "purchase", "purchased"}
    ):
        return False
    household_actions = {"boil", "boiled", "cook", "cooking", "store", "storage", "fresh", "freeze", "thaw", "prepare", "recipe"}
    hard_receipt_terms = {
        "receipt", "receipts", "bought", "buy", "purchase", "purchased",
        "price", "prices", "cheap", "cheapest", "cheaper", "lowest",
        "highest", "spent", "spending", "total",
    }
    if "how" in tokens and tokens & household_actions and not tokens & hard_receipt_terms:
        return True
    if "shopping" in tokens and (tokens & {"cheaper", "save"}) and not (tokens & {"receipt", "receipts", "bought", "purchase", "purchased", "price", "prices", "store", "stores"}):
        return True
    receipt_terms = {
        "receipt", "receipts", "bought", "buy", "purchase", "purchased",
        "price", "prices", "cheap", "cheapest", "cheaper", "lowest",
        "highest", "store", "stores", "spent", "spending", "total",
    }
    question_terms = {"how", "what", "why", "when", "should", "can", "is"}
    return bool(tokens & GENERAL_ADVICE_TERMS) and bool(tokens & question_terms) and not bool(tokens & receipt_terms)


def retrieve_general_context(message: str, *, token_set, correct_query_words, normalize_text, limit: int = 3) -> list[dict]:
    query_tokens = token_set(message) | set(correct_query_words(normalize_text(message)).split())
    scored = []
    for snippet in GENERAL_KNOWLEDGE_SNIPPETS:
        keywords = set(snippet.get("keywords") or set())
        overlap = query_tokens & keywords
        if not overlap:
            continue
        score = len(overlap) / max(len(keywords), 1)
        scored.append((score, len(overlap), snippet))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [
        {
            "id": snippet["id"],
            "title": snippet["title"],
            "text": snippet["text"],
            "source": "curated_general_knowledge",
            "openable": False,
        }
        for _, _, snippet in scored[:limit]
    ]


def general_context_text(context: list[dict]) -> str:
    if not context:
        return ""
    return "\n".join(f"- {row['title']}: {row['text']}" for row in context)


def fallback_general_answer(message: str, context: list[dict] | None = None, *, correct_query_words, normalize_text) -> str:
    for row in context or []:
        direct_answer = str(row.get("direct_answer") or "").strip()
        if direct_answer:
            return direct_answer
    m = correct_query_words(normalize_text(message))
    if "boil" in m and ("egg" in m or "eggs" in m):
        return "For boiled eggs, simmer large eggs for about 9-12 minutes, then cool them in ice water. Use 6-7 minutes for softer yolks."
    if ("store" in m or "keep" in m or "fresh" in m) and ("cilantro" in m or "coriander" in m):
        return "To keep cilantro fresh, trim the stems, place it upright in a jar with a little water, cover loosely with a bag, and refrigerate. Change the water every few days."
    if ("store" in m or "keep" in m or "fresh" in m) and ("tomato" in m or "tomatoes" in m):
        return "To keep tomatoes fresh, store uncut ripe tomatoes at room temperature away from direct sun and use them within a few days. Refrigerate only very ripe or cut tomatoes, then let chilled whole tomatoes come back to room temperature before eating for better flavor."
    if "freeze" in m and "meat" in m:
        return "To freeze meat, wrap it tightly, press out air, label the date, and freeze at 0 deg F / -18 deg C. Use raw ground meat within 3-4 months and larger cuts within 6-12 months for best quality."
    if "expired" in m and ("yogurt" in m or "yoghurt" in m):
        return "Do not eat yogurt if it smells sour beyond normal, has mold, gas pressure, or unusual texture. If it is only slightly past the date and looks/smells normal, use caution and discard when unsure."
    if "milk" in m and ("bacteria" in m or "pasteur" in m or "temperature" in m):
        return (
            "To pasteurize milk at home, heat it to 161 deg F / 72 deg C for 15 seconds, "
            "then cool it quickly and refrigerate it. Another common method is "
            "145 deg F / 63 deg C for 30 minutes. Do not rely on this to make spoiled milk safe."
        )
    if "basmati" in m and "rice" in m:
        return "Basmati rice is a long-grain aromatic rice known for a fluffy texture and nutty aroma. It works well with biryani, curries, pilaf, and simple dal meals."
    if "goat" in m and ("cook" in m or "cooking" in m or "recipe" in m or "prepare" in m):
        return "To cook goat meat, use moist heat or a pressure cooker for tougher cuts, season well, and cook until tender. It works well in curry, stew, biryani, or slow braises."
    if "goat" in m and ("healthy" in m or "health" in m):
        return "Goat meat can be a healthy protein choice when eaten in moderation. It is typically leaner than some red meats, but portion size, cooking method, and overall diet still matter."
    if "shopping" in m and ("cheaper" in m or "save" in m):
        return "To make grocery shopping cheaper, plan meals around repeat items, compare unit prices, buy only sale items you will actually use, and avoid stocking up on products without price history."
    if "vegetable" in m and "curry" in m:
        return "Good vegetables with chicken curry include potato, carrot, peas, bell pepper, spinach, cauliflower, green beans, and eggplant. Add quick-cooking vegetables near the end so they do not get mushy."
    return "I can help with that. Please ask the question with a little more detail."


def general_advice_answer(
    message: str,
    context: list[dict] | None = None,
    *,
    retrieve_context,
    claude_client,
    claude_model: str,
    correct_query_words,
    normalize_text,
) -> str:
    context = context or retrieve_context(message)
    context_text = general_context_text(context)
    system = (
        "You are ReceiptAI's helpful shopping and household assistant. "
        "Answer general consumer, cooking, food safety, storage, and product questions clearly. "
        "Use the provided general context when relevant. "
        "Do not claim anything from the user's receipts unless receipt data is provided. "
        "Keep the answer concise, practical, and mobile-friendly. "
        "For safety topics, include the key safe number or rule and a short caution."
    )
    user_content = message
    if context_text:
        user_content = f"General context:\n{context_text}\n\nUser question:\n{message}"

    if claude_client is not None:
        try:
            response = claude_client.messages.create(
                model=claude_model,
                max_tokens=420,
                temperature=0.2,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            text = "".join(block.text for block in response.content if hasattr(block, "text") and block.text).strip()
            if text:
                return text
        except Exception as e:
            logger.warning("General advice generation unavailable: %s", e)

    return fallback_general_answer(
        message,
        context,
        correct_query_words=correct_query_words,
        normalize_text=normalize_text,
    )
