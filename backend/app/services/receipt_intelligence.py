"""
Production-oriented receipt intelligence layer.

This module keeps query parsing, item normalization, retrieval, scoring, and
answer formatting separate from the LLM/tool loop. It is intentionally
deterministic: receipt-related claims must come from receipt rows or item rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any


STOP_WORDS = {
    "a", "an", "and", "any", "are", "at", "buy", "bought", "by", "did",
    "do", "does", "from", "have", "i", "in", "is", "it", "me", "my",
    "no", "of", "on", "or", "please", "receipt", "receipts", "right", "show",
    "the", "there", "to", "was", "were", "what", "where", "which",
    "with",
}

QUESTION_WORDS = STOP_WORDS | {
    "find", "found", "get", "give", "list", "look", "looking", "purchased",
    "spend", "spent", "total", "how", "much", "many", "last", "this",
    "month", "week", "year", "price", "prices", "cost", "costs", "paid",
    "pay", "rate", "there", "having", "missing", "comma", "commas", "not",
    "all", "item", "items", "complete", "summary", "overview", "analysis",
    "report", "deal", "deals", "recent", "recently", "time", "times",
    "count", "often", "frequently",
}

TYPO_CORRECTIONS = {
    "by": "buy",
    "rise": "rice",
    "riice": "rice",
    "ric": "rice",
    "onoin": "onion",
    "onins": "onions",
    "yougurt": "yogurt",
    "yoghurt": "yogurt",
    "brijal": "brinjal",
    "bringal": "brinjal",
    "corander": "coriander",
    "corandr": "coriander",
    "detergnt": "detergent",
    "powdr": "powder",
    "walmrt": "walmart",
    "cheep": "cheap",
    "cheepest": "cheapest",
    "recipt": "receipt",
    "recipts": "receipts",
    "recepit": "receipt",
    "recepits": "receipts",
    "waht": "what",
    "vegitables": "vegetables",
}

ALIAS_GROUPS = [
    {"curd", "yogurt", "yoghurt", "dahi"},
    {"brinjal", "eggplant", "aubergine", "baingan"},
    {"cilantro", "coriander", "dhaniya"},
    {"detergent", "washing powder", "laundry powder", "soap powder"},
    {"coke", "cola", "coca cola", "soft drink", "soda"},
    {"capsicum", "bell pepper", "pepper"},
    {"chickpeas", "chana", "garbanzo", "garbanzo beans"},
    {"atta", "flour", "wheat flour", "chapati flour"},
    {"rice", "basmati rice", "sona masoori", "jasmine rice"},
    {"onion", "onions"},
    {"tomato", "tomatoes"},
    {"egg", "eggs"},
]

CATEGORY_ALIASES = {
    "vegetable": {
        "vegetable", "vegetables", "veggie", "veggies", "produce", "tomato",
        "tomatoes", "onion", "onions", "potato", "potatoes", "eggplant",
        "brinjal", "capsicum", "bell pepper", "cilantro", "coriander",
    },
    "snacks": {"snack", "snacks", "chips", "cookies", "cracker", "crackers", "namkeen"},
    "dairy": {"milk", "curd", "yogurt", "cheese", "paneer", "butter"},
    "drinks": {"drink", "drinks", "soda", "coke", "cola", "juice"},
    "pantry": {"rice", "atta", "flour", "dal", "lentil", "lentils", "oil", "ghee"},
}

AMBIGUOUS_SINGLE_ITEM_BLOCKERS = {
    "pepper": {
        "chicken", "goat", "beef", "pork", "fish", "dosa", "biryani",
        "fried", "combo", "meal", "sandwich", "sauce",
    },
    "rice": set(),
    "oil": {"burner", "lamp", "diffuser", "fragrance", "essential"},
    "mushroom": {"gummy", "gummies", "candy", "blend", "trolli", "chapo"},
}

RECEIPT_WORDS = {
    "buy", "bought", "purchase", "purchased", "receipt", "receipts", "spend",
    "spent", "store", "walmart", "cost", "price", "pay", "paid", "total",
}
RECEIPT_CLAIM_WORDS = RECEIPT_WORDS - {"store"}

GENERAL_ADVICE_WORDS = {
    "best way", "how to", "store tomatoes", "store tomato", "cook", "recipe",
    "safe", "healthy", "temperature",
}

PRODUCT_RELATION_WORDS = {
    "alias", "aliases", "called", "define", "definition", "difference",
    "different", "equivalent", "mean", "meaning", "means", "name",
    "same", "similar", "synonym", "synonyms", "versus", "vs",
}

INTENT_ITEM_LOOKUP = "receipt_item_lookup"
INTENT_MISSING_ITEM_LOOKUP = "receipt_missing_item_lookup"
INTENT_SPENDING_SUMMARY = "spending_summary"
INTENT_STORE_LOOKUP = "store_lookup"
INTENT_GENERAL = "general_question"
INTENT_UNCLEAR = "unclear_question"
BROAD_LEGACY_CATEGORY_TERMS = {"meat", "mutton", "grocery", "groceries", "produce", "veggie", "veggies"}


@dataclass
class ReceiptQuery:
    original: str
    normalized: str
    intent: str
    items: list[str] = field(default_factory=list)
    category: str = ""
    store: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    negative: bool = False


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        return float(value)
    except Exception:
        return default


def normalize_item_name(text: str | None) -> str:
    if not text:
        return ""
    value = str(text).lower()
    value = value.replace("&", " and ")
    value = re.sub(r"\b\d+(?:\.\d+)?\s*(?:oz|lb|lbs|ct|ea|g|kg|ml|l|gal|qt|pt)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    tokens = [TYPO_CORRECTIONS.get(token, token) for token in value.split()]
    return re.sub(r"\s+", " ", " ".join(tokens)).strip()


def normalize_store_name(text: str | None) -> str:
    normalized = normalize_item_name(text)
    compact = normalized.replace(" ", "")
    if compact in {"walmart", "walmartstore", "walmartsupercenter"} or normalized.startswith("wal mart"):
        return "walmart"
    return normalized


def singularize(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def item_tokens(text: str | None) -> set[str]:
    return {
        singularize(token)
        for token in normalize_item_name(text).split()
        if token and token not in STOP_WORDS and len(token) > 1
    }


def phrase_in_text(phrase: str, text: str) -> bool:
    phrase_norm = normalize_item_name(phrase)
    text_norm = normalize_item_name(text)
    if not phrase_norm or not text_norm:
        return False
    return re.search(rf"(^|\s){re.escape(phrase_norm)}(\s|$)", text_norm) is not None


def alias_terms(term: str) -> set[str]:
    norm = normalize_item_name(term)
    terms = {norm}
    for group in ALIAS_GROUPS:
        normalized_group = {normalize_item_name(value) for value in group}
        if norm in normalized_group or item_tokens(norm) & set().union(*(item_tokens(v) for v in normalized_group)):
            terms |= normalized_group
    return {value for value in terms if value}


def disqualified_ambiguous_match(query_item: str, event_name: str) -> bool:
    q_tokens = item_tokens(query_item)
    if len(q_tokens) != 1:
        return False
    query_token = next(iter(q_tokens))
    blockers = AMBIGUOUS_SINGLE_ITEM_BLOCKERS.get(query_token)
    if not blockers:
        return False
    event_tokens = item_tokens(event_name)
    if not event_tokens & blockers:
        return False
    if query_token == "pepper" and event_tokens & {"bell", "black", "capsicum"}:
        return False
    if query_token == "rice" and event_tokens & {"raw", "basmati", "sona", "masoori", "jasmine"}:
        return False
    return True


def canonical_category(term: str) -> str:
    tokens = item_tokens(term)
    for category in ["snacks", "drinks", "dairy", "pantry", "vegetable"]:
        aliases = CATEGORY_ALIASES[category]
        alias_tokens = {singularize(normalize_item_name(alias)) for alias in aliases}
        if tokens & alias_tokens or normalize_item_name(term) in {normalize_item_name(a) for a in aliases}:
            return category
    return ""


def known_item_labels() -> set[str]:
    labels = set()
    for group in ALIAS_GROUPS:
        labels |= {normalize_item_name(value) for value in group}
    for aliases in CATEGORY_ALIASES.values():
        labels |= {normalize_item_name(value) for value in aliases}
    labels |= {normalize_item_name(value) for value in TYPO_CORRECTIONS.values()}
    return {label for label in labels if label}


def split_known_item_sequence(items: list[str]) -> list[str]:
    labels = known_item_labels()
    result: list[str] = []
    for item in items:
        tokens = item.split()
        if len(tokens) <= 1:
            result.append(item)
            continue
        found: list[str] = []
        i = 0
        while i < len(tokens):
            best = ""
            best_j = i
            for j in range(min(len(tokens), i + 3), i, -1):
                phrase = " ".join(tokens[i:j])
                if phrase in labels:
                    best = phrase
                    best_j = j
                    break
            if best:
                found.append(best)
                i = best_j
            else:
                i += 1
        result.extend(found if len(found) >= 2 else [item])
    deduped: list[str] = []
    for item in result:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def parse_date_range(message: str, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    now = now or datetime.now()
    text = normalize_item_name(message)
    today = datetime(now.year, now.month, now.day)
    if "last month" in text:
        first_this_month = today.replace(day=1)
        last_prev_month = first_this_month - timedelta(days=1)
        start = last_prev_month.replace(day=1)
        end = first_this_month
        return start, end
    if "this month" in text:
        return today.replace(day=1), today + timedelta(days=1)
    if "last week" in text:
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=7)
    if "this week" in text:
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1)
    return None, None


def parse_receipt_query(message: str, now: datetime | None = None) -> ReceiptQuery:
    normalized = normalize_item_name(message)
    lower = (message or "").lower()
    start, end = parse_date_range(message, now)

    # Product meaning is a different task from receipt lookup. Alias presence
    # must never be used as proof that the user asked about a purchase.
    normalized_tokens = set(normalized.split())
    if (
        normalized_tokens & PRODUCT_RELATION_WORDS
        and not normalized_tokens & RECEIPT_CLAIM_WORDS
    ):
        return ReceiptQuery(message, normalized, INTENT_GENERAL)

    if any(phrase in lower for phrase in GENERAL_ADVICE_WORDS) and not (set(normalized.split()) & RECEIPT_CLAIM_WORDS):
        return ReceiptQuery(message, normalized, INTENT_GENERAL)

    negative = bool(re.search(r"\b(don'?t|do not|didn'?t|not|missing|without|no)\b", lower))

    store = ""
    store_match = re.search(r"\bfrom\s+([a-zA-Z0-9 &'.-]+?)(?:\s+(?:last|this|where|what|how|with|for)\b|[?.!,]|$)", message or "", re.I)
    if store_match:
        store = normalize_item_name(store_match.group(1))
    elif "walmart" in normalized:
        store = "walmart"

    category = ""
    for key in CATEGORY_ALIASES:
        if key in normalized or key.rstrip("s") in normalized:
            category = key
            break

    broad_summary_terms = {
        "summary", "overview", "analysis", "report", "spending", "expense",
        "expenses", "deal", "deals", "saving", "savings",
    }
    if set(normalized.split()) & broad_summary_terms:
        return ReceiptQuery(message, normalized, INTENT_SPENDING_SUMMARY, category=category, store=store, start_date=start, end_date=end)

    extracted_items = extract_items(message, store=store, category=category)

    if "spend" in normalized or "spent" in normalized or "how much" in lower:
        items = [] if category else extracted_items
        return ReceiptQuery(message, normalized, INTENT_SPENDING_SUMMARY, items=items, category=category, store=store, start_date=start, end_date=end)

    if negative and ("receipt" in normalized or "receipts" in normalized or "which" in normalized):
        item = extracted_items
        return ReceiptQuery(message, normalized, INTENT_MISSING_ITEM_LOOKUP, items=item, store=store, start_date=start, end_date=end, negative=True)

    store_listing_words = {"what", "all", "items", "item", "list", "show"}
    if store and extracted_items and not (set(normalized.split()) & store_listing_words and not any(item in normalized for item in extracted_items)):
        return ReceiptQuery(message, normalized, INTENT_ITEM_LOOKUP, items=extracted_items, store=store, start_date=start, end_date=end, negative=negative)

    if store and ("what" in normalized or "items" in normalized or "buy" in normalized or "bought" in normalized):
        return ReceiptQuery(message, normalized, INTENT_STORE_LOOKUP, store=store, start_date=start, end_date=end)

    if set(normalized.split()) & RECEIPT_WORDS:
        items = extracted_items
        if items:
            return ReceiptQuery(message, normalized, INTENT_ITEM_LOOKUP, items=items, store=store, start_date=start, end_date=end, negative=negative)

    if len(item_tokens(message)) <= 3 and item_tokens(message):
        return ReceiptQuery(message, normalized, INTENT_ITEM_LOOKUP, items=[normalize_item_name(message)], start_date=start, end_date=end)

    return ReceiptQuery(message, normalized, INTENT_UNCLEAR)


def extract_items(message: str, store: str = "", category: str = "") -> list[str]:
    text = normalize_item_name(message)
    for phrase in [
        "did i buy", "i bought", "where did i buy", "where i bought",
        "show me receipts where i bought", "show receipts where i bought",
        "which receipts do not have", "which receipts dont have",
        "which receipts don t have", "how much did i spend on",
        "how many times did i buy", "how many times i bought",
        "how often did i buy", "how frequently did i buy",
        "receipts not having", "receipt not having", "which receipts missing",
        "receipts missing", "not having",
    ]:
        text = text.replace(phrase, " ")
    if store:
        text = text.replace(store, " ")
    if category:
        text = text.replace(category, " ")
    text = re.sub(r"\b(last|this)\s+(month|week|year)\b", " ", text)
    raw_parts = re.split(r"\bor\b|,", text) if re.search(r"\bor\b|,", text) else [text]
    items = []
    for part in raw_parts:
        tokens = [token for token in part.split() if token not in QUESTION_WORDS]
        cleaned = normalize_item_name(" ".join(tokens))
        if cleaned:
            items.append(cleaned)
    return split_known_item_sequence(items)


def parse_event_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%y", "%m/%d/%Y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(text[:19] if "T" in fmt else text[:11], fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def event_in_filters(event: dict, query: ReceiptQuery) -> bool:
    if query.store and query.store not in normalize_store_name(event.get("store")):
        return False
    if query.start_date or query.end_date:
        date = parse_event_date(event.get("date") or event.get("purchase_date") or event.get("created_at"))
        if not date:
            return False
        if query.start_date and date < query.start_date:
            return False
        if query.end_date and date >= query.end_date:
            return False
    return True


def item_match_score(query_item: str, event_name: str) -> tuple[float, str]:
    q_norm = normalize_item_name(query_item)
    e_norm = normalize_item_name(event_name)
    if not q_norm or not e_norm:
        return 0.0, "none"
    if disqualified_ambiguous_match(q_norm, e_norm):
        return 0.0, "none"
    if q_norm == e_norm:
        return 1.0, "exact"
    if phrase_in_text(q_norm, e_norm) or phrase_in_text(e_norm, q_norm):
        return 0.94, "normalized"

    best_alias_score = 0.0
    for alias in alias_terms(q_norm):
        if alias == e_norm or phrase_in_text(alias, e_norm) or phrase_in_text(e_norm, alias):
            return 0.9, "synonym"
        best_alias_score = max(best_alias_score, SequenceMatcher(None, alias, e_norm).ratio())
        alias_token_overlap = item_tokens(alias) & item_tokens(e_norm)
        if alias_token_overlap and alias_token_overlap == item_tokens(alias):
            return 0.86, "synonym"

    q_tokens = item_tokens(q_norm)
    e_tokens = item_tokens(e_norm)
    if q_tokens and q_tokens <= e_tokens:
        return 0.84, "normalized"
    if len(q_tokens) == 1:
        token = next(iter(q_tokens))
        if len(token) <= 4:
            # Short item names are too easy to corrupt with fuzzy suffix matches:
            # rice -> ice, egg -> peg, milk -> silk. Require a real token/alias.
            return 0.0, "none"
    token_scores = [max((SequenceMatcher(None, qt, et).ratio() for et in e_tokens), default=0.0) for qt in q_tokens]
    token_fuzzy = sum(token_scores) / len(token_scores) if token_scores else 0.0
    seq = SequenceMatcher(None, q_norm, e_norm).ratio()
    fuzzy = max(seq, token_fuzzy, best_alias_score)
    if fuzzy >= 0.82:
        return min(0.82, fuzzy), "fuzzy"
    if fuzzy >= 0.72:
        return min(0.74, fuzzy), "possible"
    return fuzzy * 0.6, "none"


def match_item_events(query: ReceiptQuery, events: list[dict], threshold: float = 0.72) -> list[dict]:
    matches: list[dict] = []
    for event in events:
        if not event_in_filters(event, query):
            continue
        event_name = event.get("item_original") or event.get("item_name_original") or event.get("name") or ""
        for query_item in query.items:
            score, method = item_match_score(query_item, event_name)
            if score >= threshold:
                row = dict(event)
                row["matched_query"] = query_item
                row["match_score"] = round(score, 4)
                row["matching_method"] = method
                row["match_confidence"] = "high" if score >= 0.84 else "medium"
                matches.append(row)
                break
    matches.sort(key=lambda row: (row.get("match_score", 0), row.get("date") or row.get("created_at") or ""), reverse=True)
    return matches


def receipt_has_item(receipt: dict, query: ReceiptQuery) -> bool:
    events = []
    for index, item in enumerate(receipt.get("items") or []):
        if isinstance(item, dict):
            events.append({
                "receipt_id": receipt.get("id"),
                "line_index": index,
                "store": receipt.get("store"),
                "date": receipt.get("date") or receipt.get("created_at"),
                "item_original": item.get("name") or item.get("item"),
                "line_price": item.get("price"),
            })
    return bool(match_item_events(query, events))


def money(value: Any) -> str:
    return f"${safe_float(value):.2f}"


def format_item_row(event: dict) -> str:
    item = event.get("item_original") or event.get("item_name_original") or "item"
    store = event.get("store") or "Unknown store"
    date = event.get("date") or event.get("purchase_date") or event.get("created_at") or "unknown date"
    price = event.get("line_price") if event.get("line_price") is not None else event.get("price")
    price_text = money(price) if price is not None else "price not shown"
    confidence = event.get("match_confidence") or "medium"
    method = event.get("matching_method") or "match"
    return f"- {item} at {store} on {date} for {price_text} ({confidence}, {method})"


def date_range_label(query: ReceiptQuery) -> str:
    if query.start_date and query.end_date:
        end = query.end_date - timedelta(days=1)
        return f" from {query.start_date.date()} to {end.date()}"
    return ""


def scope_label(query: ReceiptQuery) -> str:
    parts = []
    if query.store:
        parts.append(f"at {query.store}")
    date_label = date_range_label(query).strip()
    if date_label:
        parts.append(date_label)
    return " ".join(parts)


def without_filters(query: ReceiptQuery) -> ReceiptQuery:
    return ReceiptQuery(
        original=query.original,
        normalized=query.normalized,
        intent=query.intent,
        items=list(query.items),
        category=query.category,
        negative=query.negative,
    )


def store_current_price_hint(query: ReceiptQuery, display: str) -> str:
    if not query.store:
        return ""
    store_display = query.store.title()
    return f"For a current price, check the {store_display} app or website for {display}; I will not guess a live price from receipt history."


def scoped_not_found_lines(query: ReceiptQuery, events: list[dict], display: str) -> list[str]:
    scope = scope_label(query)
    lines = [f"I did not find a clear {display} purchase{(' ' + scope) if scope else ''} in your receipts."]
    broader_matches = match_item_events(without_filters(query), events) if query.items else []
    if broader_matches:
        lines.append("I did find possible receipt history outside that exact scope:")
        for event in broader_matches[:3]:
            lines.append(format_item_row(event))
    hint = store_current_price_hint(query, display)
    if hint:
        lines.append(hint)
    return lines


def answer_item_lookup(query: ReceiptQuery, events: list[dict]) -> tuple[str, dict | None]:
    matches = match_item_events(query, events)
    display = " or ".join(query.items) if query.items else "that item"
    if not matches:
        return "\n".join(scoped_not_found_lines(query, events, display)), None
    first = matches[0]
    prefix = "Yes"
    if first.get("matching_method") == "synonym" and normalize_item_name(first.get("matched_query")) not in normalize_item_name(first.get("item_original")):
        prefix = "Yes, I found a likely alias match"
    lines = [f"{prefix}, I found {len(matches)} matching purchase{'s' if len(matches) != 1 else ''} for {display}."]
    lines.extend(format_item_row(event) for event in matches[:5])
    return "\n".join(lines), answer_card_from_event(first, "receipt_item_lookup")


def answer_missing_lookup(query: ReceiptQuery, receipts: list[dict]) -> tuple[str, dict | None]:
    scoped_receipts = [
        receipt for receipt in receipts
        if not query.store or query.store in normalize_store_name(receipt.get("store"))
    ]
    missing = [receipt for receipt in scoped_receipts if not receipt_has_item(receipt, query)]
    display = " or ".join(query.items) if query.items else "that item"
    if not missing:
        return f"All available receipts include a match for {display}.", None
    lines = [f"{len(missing)} receipt{'s' if len(missing) != 1 else ''} do not have a clear {display} match:"]
    for receipt in missing[:8]:
        lines.append(f"- {receipt.get('store') or 'Unknown store'} on {receipt.get('date') or receipt.get('created_at') or 'unknown date'} (receipt {receipt.get('id')})")
    return "\n".join(lines), None


def infer_store_from_receipts(query: ReceiptQuery, receipts: list[dict]) -> ReceiptQuery:
    if query.store:
        query.store = normalize_store_name(query.store)
        return query
    if not any(token in query.normalized.split() for token in {"what", "items", "buy", "bought", "purchase", "purchased", "from"}):
        return query
    query_compact = query.normalized.replace(" ", "")
    best_store = ""
    best_len = 0
    for receipt in receipts:
        store = normalize_store_name(receipt.get("store"))
        if not store:
            continue
        store_compact = store.replace(" ", "")
        if (store in query.normalized or store_compact in query_compact) and len(store_compact) > best_len:
            best_store = store
            best_len = len(store_compact)
    if best_store:
        query.store = best_store
        items = extract_items(query.original, store=best_store, category=query.category)
        if items and not (set(query.normalized.split()) & {"what", "all", "items", "item", "list", "show"}):
            query.items = items
            query.intent = INTENT_ITEM_LOOKUP
        else:
            query.intent = INTENT_STORE_LOOKUP
    return query


def answer_store_lookup(query: ReceiptQuery, receipts: list[dict], events: list[dict]) -> tuple[str, dict | None]:
    filtered_events = [event for event in events if query.store in normalize_store_name(event.get("store"))]
    if filtered_events:
        lines = [f"Items found from {query.store}:"]
        rows = []
        for event in filtered_events[:20]:
            item = event.get("item_original") or event.get("item_name_original") or "Item"
            store = event.get("store") or "Unknown store"
            date = event.get("date") or event.get("purchase_date") or event.get("created_at") or "unknown date"
            price = event.get("line_price") if event.get("line_price") is not None else event.get("price")
            price_text = money(price) if price is not None else "price not shown"
            lines.append(f"- {item} - {price_text} at {store} ({date})")
            rows.append({
                "item": item,
                "store": store,
                "date": date,
                "price": price_text,
                "receipt_id": event.get("receipt_id"),
                "line_index": event.get("line_index"),
                "detail": event.get("detail"),
            })
        return "\n".join(lines), {
            "type": "store_items",
            "title": f"Items from {query.store}",
            "rows": rows,
        }

    filtered = [r for r in receipts if query.store in normalize_store_name(r.get("store"))]
    if not filtered:
        return f"No receipts found for {query.store}.", None
    lines = [f"Items found from {query.store}:"]
    for receipt in filtered[:6]:
        items = [item for item in (receipt.get("items") or []) if isinstance(item, dict)]
        label = f"{receipt.get('store') or 'Unknown store'} on {receipt.get('date') or receipt.get('created_at') or 'unknown date'}"
        names = ", ".join(str(item.get("name") or item.get("item")) for item in items[:8] if item.get("name") or item.get("item"))
        lines.append(f"- {label}: {names or 'no item lines stored'}")
    return "\n".join(lines), None


def event_category(event: dict) -> str:
    name = event.get("item_original") or event.get("item_name_original") or ""
    category = canonical_category(name)
    return category


def answer_spending_summary(query: ReceiptQuery, events: list[dict]) -> tuple[str, dict | None]:
    filtered = [event for event in events if event_in_filters(event, query)]
    if query.category:
        filtered = [event for event in filtered if event_category(event) == query.category]
    if query.items:
        filtered = match_item_events(query, filtered)
    if any(token in query.normalized.split() for token in {"deal", "deals"}):
        return answer_best_deals(query, filtered)
    total = sum(safe_float(event.get("line_price") if event.get("line_price") is not None else event.get("price")) for event in filtered)
    label = query.category or (" or ".join(query.items) if query.items else "all receipt item lines")
    if not filtered:
        return "\n".join(scoped_not_found_lines(query, events, label)), None
    lines = [f"You spent {money(total)} on {label}{date_range_label(query)} across {len(filtered)} item line{'s' if len(filtered) != 1 else ''}."]
    by_store: dict[str, float] = {}
    for event in filtered:
        by_store[event.get("store") or "Unknown store"] = by_store.get(event.get("store") or "Unknown store", 0.0) + safe_float(event.get("line_price") if event.get("line_price") is not None else event.get("price"))
    for store, value in sorted(by_store.items(), key=lambda row: row[1], reverse=True)[:5]:
        lines.append(f"- {store}: {money(value)}")
    return "\n".join(lines), None


def answer_best_deals(query: ReceiptQuery, events: list[dict]) -> tuple[str, dict | None]:
    priced = [
        event for event in events
        if safe_float(event.get("line_price") if event.get("line_price") is not None else event.get("price")) > 0
    ]
    if not priced:
        return "I do not have enough priced receipt items to identify recent deals yet.", None

    by_item: dict[str, list[dict]] = {}
    for event in priced:
        name = normalize_item_name(event.get("item_original") or event.get("item_name_original"))
        if not name or name == "unknown item":
            continue
        by_item.setdefault(name, []).append(event)

    opportunities = []
    for name, rows in by_item.items():
        prices = [safe_float(row.get("line_price") if row.get("line_price") is not None else row.get("price")) for row in rows]
        if not prices:
            continue
        best = min(rows, key=lambda row: safe_float(row.get("line_price") if row.get("line_price") is not None else row.get("price")))
        if len(prices) >= 2 and max(prices) > min(prices):
            opportunities.append((max(prices) - min(prices), len(rows), best))
        else:
            opportunities.append((0.0, len(rows), best))

    opportunities.sort(key=lambda row: (row[0], row[1], safe_float(row[2].get("line_price") if row[2].get("line_price") is not None else row[2].get("price"))), reverse=True)
    if not opportunities:
        return "I do not have enough clear receipt item names to identify deals yet.", None

    lines = ["Best receipt deals I found recently:"]
    rows = []
    for spread, count, event in opportunities[:5]:
        item = event.get("item_original") or event.get("item_name_original") or "Item"
        store = event.get("store") or "Unknown store"
        date = event.get("date") or event.get("purchase_date") or event.get("created_at") or "unknown date"
        price = event.get("line_price") if event.get("line_price") is not None else event.get("price")
        detail = f"seen {count} time{'s' if count != 1 else ''}"
        if spread > 0:
            detail += f", price swing {money(spread)}"
        lines.append(f"- {item}: {money(price)} at {store} ({date}; {detail})")
        rows.append({
            "item": item,
            "store": store,
            "date": date,
            "price": money(price),
            "receipt_id": event.get("receipt_id"),
            "line_index": event.get("line_index"),
            "detail": detail,
        })
    return "\n".join(lines), {
        "type": "best_deals",
        "title": "Best receipt deals",
        "rows": rows,
        "note": "Based only on your receipt history; live market prices are not guessed.",
    }


def answer_card_from_event(event: dict, card_type: str) -> dict:
    return {
        "type": card_type,
        "item": event.get("item_original") or event.get("item_name_original"),
        "store": event.get("store"),
        "date": event.get("date") or event.get("purchase_date") or event.get("created_at"),
        "price": money(event.get("line_price") if event.get("line_price") is not None else event.get("price")),
        "receipt_id": event.get("receipt_id"),
        "line_index": event.get("line_index"),
        "match_score": event.get("match_score"),
        "matching_method": event.get("matching_method"),
        "match_confidence": event.get("match_confidence"),
    }


def trace(query: ReceiptQuery, evidence: list[dict] | None = None) -> dict:
    answer_mode = "receipt_analytics" if query.intent == INTENT_SPENDING_SUMMARY else "receipt_fact"
    return {
        "architecture": "deterministic_receipt_intelligence_v2",
        "answer_mode": answer_mode,
        "intent": query.intent,
        "normalized_query": query.normalized,
        "entities": {
            "items": query.items,
            "category": query.category,
            "store": query.store,
            "date_range": [
                query.start_date.date().isoformat() if query.start_date else None,
                query.end_date.date().isoformat() if query.end_date else None,
            ],
            "negative": query.negative,
        },
        "evidence_count": len(evidence or []),
        "evidence": evidence or [],
        "strict_receipt_grounding": True,
    }


def answer_receipt_query(message: str, receipts: list[dict], events: list[dict], now: datetime | None = None) -> dict | None:
    query = infer_store_from_receipts(parse_receipt_query(message, now), receipts)
    if query.intent in {INTENT_GENERAL, INTENT_UNCLEAR}:
        return None
    if any(phrase in query.normalized for phrase in {"shopping plan", "items to purchase", "purchase this month", "what should i buy", "buy next", "next grocery"}):
        return None
    if (
        query.intent == INTENT_SPENDING_SUMMARY
        and any(token in query.normalized.split() for token in {"monthly", "expense", "expenses", "analysis", "analyze", "chart", "graph", "report"})
        and " on " not in f" {query.normalized} "
    ):
        return None
    price_like_terms = {"price", "prices", "best", "cheap", "cheapest", "paid", "pay", "cost"}
    if "," in (message or "") and any(token in query.normalized.split() for token in price_like_terms):
        return None
    if query.intent == INTENT_ITEM_LOOKUP and len(query.items) > 1 and any(token in query.normalized.split() for token in price_like_terms | {"table", "tabular"}):
        return None
    if (
        any(token in query.normalized.split() for token in price_like_terms | {"history", "tabular", "table"})
        and not any(phrase in query.normalized for phrase in {"did i buy", "i bought", "where did i", "show me receipts", "receipts where"})
        and query.intent != INTENT_SPENDING_SUMMARY
        and not (query.store and query.items)
    ):
        return None
    if (
        query.intent == INTENT_ITEM_LOOKUP
        and any(token in query.normalized.split() for token in price_like_terms | {"history"})
        and not any(phrase in query.normalized for phrase in {"did i buy", "i bought", "where did i", "show me receipts"})
        and not (query.store and query.items)
    ):
        return None
    if query.intent == INTENT_ITEM_LOOKUP and set(query.normalized.split()) & BROAD_LEGACY_CATEGORY_TERMS:
        return None

    response = ""
    card = None
    evidence: list[dict] = []
    if query.intent == INTENT_ITEM_LOOKUP:
        response, card = answer_item_lookup(query, events)
        evidence = match_item_events(query, events)[:5]
    elif query.intent == INTENT_MISSING_ITEM_LOOKUP:
        response, card = answer_missing_lookup(query, receipts)
    elif query.intent == INTENT_STORE_LOOKUP:
        response, card = answer_store_lookup(query, receipts, events)
        evidence = [event for event in events if query.store in normalize_store_name(event.get("store"))][:8]
    elif query.intent == INTENT_SPENDING_SUMMARY:
        response, card = answer_spending_summary(query, events)
    else:
        return None

    return {
        "response": response,
        "answer_card": card,
        "tools_used": [],
        "thinking": "",
        "rag_trace": trace(query, evidence),
    }
