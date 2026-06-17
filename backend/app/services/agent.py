# ─────────────────────────────────────────
# services/agent.py
# ReceiptAI Autonomous Agent + Structured Receipt RAG
#
# Fixes:
# - Ground answers in retrieved receipt item events
# - Fuzzy item matching for OCR/name variations (PREM vs PREN, Rose Pink Prem vs Rose Pink Frame)
# - Treat product size (2.00-GAL, 10.00-OZ, etc.) as packaging, NOT quantity
# - Never combine separate receipts into quantity 2 unless receipt explicitly says QTY 2 / 2 @ / 2 EA
# ─────────────────────────────────────────

import json
import hashlib
import math
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from statistics import median
from typing import Any
from app.config import claude_client, supabase
from app.services.agent_architecture import finalize_agent_result, rag_trace
from app.services import receipt_intelligence
from app.services import agent_general
from app.services import agent_analytics

MODEL = os.getenv("CLAUDE_AGENT_MODEL", "claude-opus-4-5-20251101")
SONNET_MODEL = os.getenv("CLAUDE_SONNET_MODEL", "claude-sonnet-4-5-20250929")
LOCAL_EMBEDDING_MODEL = os.getenv("RECEIPT_ITEM_EMBEDDING_MODEL", "receiptai-local-hash-v1")
EMBEDDING_DIMENSIONS = 1536
AGENT_FLEXIBLE_MEMORY_ENABLED = os.getenv("AGENT_FLEXIBLE_MEMORY_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
AGENT_STRICT_MATCHING = os.getenv("AGENT_STRICT_MATCHING", "true").lower() != "false"
AGENT_EMBEDDING_RETRIEVAL_ENABLED = os.getenv("AGENT_EMBEDDING_RETRIEVAL_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
STRICT_ITEM_MIN_SCORE = float(os.getenv("STRICT_ITEM_MIN_SCORE", "0.72"))
AGENT_BUILD = "claude-only-agent-2026-06-11"
AGENT_CAPABILITIES = {
    "structured_rag": True,
    "adaptive_query_recovery": True,
    "feedback_learning_ranker": True,
    "exclusion_clause_parser": True,
    "non_food_grocery_guard": True,
    "descriptor_safe_matching": True,
    "multi_item_splitter": True,
    "optional_embedding_boosts": AGENT_EMBEDDING_RETRIEVAL_ENABLED,
    "claude_only": True,
}
RECEIPT_SELECT = "id,store,address,date,time,total,subtotal,discount,tax,total_savings,items,created_at"
ITEM_SELECT = "receipt_id,line_index,store,purchase_date,receipt_created_at,code,item_name_original,item_name_normalized,product_size,quantity,raw_quantity,unit,unit_price,line_price,source,confidence,explicit_quantity,metadata"
_RECEIPT_CACHE: dict[tuple[str, str, int], list[dict]] = {}
_ITEM_EVENT_CACHE: dict[tuple[str, str, int], list[dict]] = {}
_ALIAS_CACHE: dict[tuple[str, str], list[set[str]]] = {}
_FEEDBACK_CACHE: dict[tuple[str, str], list[dict]] = {}
_PUBLIC_MEANING_CACHE: dict[str, list[set[str]]] = {}


def local_text_embedding(text: str) -> list[float]:
    """Create a deterministic local vector so receipt search stays Claude-only."""
    if not text:
        return []

    normalized = normalize_text(text)
    tokens = normalized.split()
    features = tokens[:]
    compact = "".join(tokens)
    if compact:
        features.extend(compact[i:i + 3] for i in range(max(0, len(compact) - 2)))
    if not features:
        return []

    vector = [0.0] * EMBEDDING_DIMENSIONS
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return []
    return [value / magnitude for value in vector]


def receipt_event_key(event: dict) -> tuple[str, str, str]:
    return (
        str(event.get("receipt_id") or ""),
        str(event.get("line_index") or ""),
        normalize_text(event.get("item_original") or ""),
    )


def fetch_embedding_rank_boosts(
    query: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> dict[tuple[str, str, str], float]:
    """
    Optional pgvector retrieval boost.
    Requires supabase_agent_ml.sql plus populated receipt_item_embeddings.
    """
    if not AGENT_EMBEDDING_RETRIEVAL_ENABLED or supabase is None:
        return {}
    embedding = local_text_embedding(query)
    if not embedding:
        return {}
    try:
        rows = supabase.rpc("match_receipt_item_embeddings", {
            "query_embedding": embedding,
            "match_count": 50,
            "p_user_id": user_id,
            "p_guest_session_id": guest_session_id,
        }).execute().data or []
    except Exception as e:
        print(f"[embeddings] Vector retrieval unavailable: {e}")
        return {}

    boosts: dict[tuple[str, str, str], float] = {}
    for row in rows:
        similarity = _safe_float(row.get("similarity"), 0.0)
        if similarity <= 0:
            continue
        key = (
            str(row.get("receipt_id") or ""),
            str(row.get("line_index") or ""),
            normalize_text(row.get("item_name") or ""),
        )
        boosts[key] = max(boosts.get(key, 0.0), min(0.18, max(0.0, (similarity - 0.74) * 0.7)))
    return boosts

AGENT_TOOLS = [
    {
        "name": "query_receipts",
        "description": "Query the user's receipt database. Use for receipt lists, totals, store info, and broad summary. Always filtered to the current user/guest.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query_type": {"type": "string", "enum": ["all", "by_store", "by_item", "summary"]},
                "store_name": {"type": "string"},
                "item_name": {"type": "string"},
                "limit": {"type": "integer", "default": 20}
            },
            "required": ["query_type"]
        }
    },
    {
        "name": "get_price_history",
        "description": "Structured RAG item search. Retrieves exact receipt item purchase events using fuzzy matching and product-size aware quantity logic. Use this for item counts, item price comparisons, price history, cheapest/highest price, and same-product questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {"type": "string", "description": "Item to search, e.g. '2.00-GAL ROSE PINK PREM' or 'rose pink frame'"},
                "limit": {"type": "integer", "default": 25}
            },
            "required": ["item_name"]
        }
    },
    {
        "name": "analyze_spending",
        "description": "Analyze spending patterns — totals by store, monthly trends, savings, top items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "analysis_type": {"type": "string", "enum": ["by_store", "by_month", "by_category", "savings", "top_items", "tax_discount", "recent_receipts", "store_frequency", "overview"]}
            },
            "required": ["analysis_type"]
        }
    },
    {
        "name": "find_best_deals",
        "description": "Find cheapest store for shopping items based on real purchase events.",
        "input_schema": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "string"}}},
            "required": ["items"]
        }
    },
    {
        "name": "search_market_prices",
        "description": "Search web for current market prices. Use only when comparing user's receipt prices to current market prices.",
        "input_schema": {
            "type": "object",
            "properties": {"item_name": {"type": "string"}},
            "required": ["item_name"]
        }
    },
    {
        "name": "check_live_price",
        "description": "Compare a current shelf/web price against the user's personal receipt price memory. Use when the user gives today's/current price, asks should I buy now, or wants live price comparison.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_name": {"type": "string"},
                "current_price": {"type": "number"},
                "store": {"type": "string"},
                "source_url": {"type": "string"},
                "live_search": {"type": "boolean", "default": False}
            },
            "required": ["item_name"]
        }
    }
]

AGENT_SCENARIO_PLAYBOOK = """
ReceiptAI scenario playbook:
1. Item count: answer with exact matched purchase events. Never combine receipts into quantity.
2. Lowest/highest item price: list each matching event with store, date, quantity, and price.
3. Same item with OCR variants: mention the scanned names briefly and answer from matched events.
4. Product size confusion: 2.00-GAL, 10 OZ, 12 CT, 5 LB, 1 QT are packaging, not quantity.
5. Store comparison: compare total spend, visit count, average trip, and savings when available.
6. Monthly report: show total, receipt count, trend chart, top stores, and highest item spend.
7. This month shopping plan: suggest repeat items with cheapest known store and price range.
8. Savings advice: give exactly 3 actions tied to price spread, top store, coupons, or repeat items.
9. Best deals: use real low prices from receipt item events; do not claim market-wide best unless web search was used.
10. Category questions: group receipts into food/grocery, restaurant, gardening/hardware, medical, pharmacy, bank/finance, fuel/auto, home, retail, or other.
11. Returns/refunds: only count negative lines or clear return/refund/void evidence.
12. Tax/discount questions: separate subtotal, tax, discounts, total savings, and final total.
13. Recent receipts: show newest receipt trips with date, store, total, and category.
14. Budget questions: compare monthly or store totals from available receipts; do not invent budgets.
15. Market price comparison: use check_live_price when the user provides today's/current price. Use web search only when the user explicitly asks for current/live market prices.
16. Unclear item query: show closest scanned receipt names instead of guessing.
17. No receipt data: say that no receipts are available and keep the answer short.
18. Customer tone: direct answer first, then compact bullets/table/chart; no repeated question, no internal process.

Example style:
Lowest found: $12.49 at Lowe's on 05/09/26.
1. 2.00-GAL ROSE PINK PREM - Lowe's - 05/09/26 - qty 1 - $12.49
2. 2.00-GAL ROSE PINK PREN - Lowe's - 05/09/26 - qty 1 - $24.98
Difference: $12.49.
Note: 2.00-GAL is product size, not quantity.
"""

STOP_WORDS = {
    "how", "many", "times", "time", "did", "do", "i", "have", "has", "bought", "buy", "purchase", "purchased",
    "receipt", "receipts", "evidence",
    "product", "item", "items", "same", "name", "price", "prices", "paid", "pay", "rate", "best", "cheap", "cheapest", "lowest", "highest",
    "greater", "less", "more", "store", "stores", "from", "for", "to", "the", "a", "an", "my", "me", "what", "which", "show", "tell",
    "history", "compare", "comparison", "cost", "costs", "howmuch", "much", "where", "it", "this", "that", "cheaper",
    "trend", "trends", "regularly", "often", "deal", "deals", "least", "all", "should", "good", "avoid", "above", "now", "wait", "low", "equal", "equals", "right",
    "is", "s", "are", "was", "were", "find", "give", "get", "please", "pls", "want", "need", "in", "at", "on", "near",
    "of", "with", "under", "over", "than", "by", "around", "inside", "between", "about", "list",
    "per",
    "them", "those", "these", "ones", "top", "most", "common", "commonly", "usual", "usually", "frequent", "open",
    "am", "mostly", "frequently", "purchasing", "purpased", "purposed", "coming", "cmg", "month", "next",
    # Negation and exclusion words — strip from item names
    "not", "no", "without", "except", "excluding", "avoid",
}

ITEM_SYNONYM_GROUPS = [
    {"mutton", "goat", "lamb", "sheep", "chevon"},
    {"meat", "beef", "pork", "chicken", "turkey", "fish", "seafood"},
    {"keema", "kheema", "qeema", "mince", "minced", "ground"},
    {"noodle", "noodles", "ramen"},
    {"cilantro", "coriander", "dhania"},  # coriander = dhania = cilantro leaf
    {"okra", "bhindi", "ladyfinger", "ladyfingers"},
    {"eggplant", "brinjal", "aubergine"},
    {"zucchini", "courgette"},
    {"bellpepper", "capsicum"},
    {"scallion", "scallions", "springonion", "greenonion"},
    {"arugula", "rocket"},
    {"shrimp", "prawn", "prawns"},
    {"chickpea", "chickpeas", "chana", "garbanzo"},
    {"yogurt", "yoghurt", "curd", "dahi"},
    {"flour", "atta", "maida"},
    {"lentil", "lentils", "dal", "dhal"},
    {"cassava", "yuca", "manioc"},
    {"cumin", "jeera", "jira"},
    {"fennel", "saunf", "anise"},
    {"mustard", "rai", "sarson"},

    {"beet", "beetroot"},
    {"sweetpotato", "yam"},
    {"bokchoy", "pakchoi"},
    {"napacabbage", "chinesecabbage"},
    {"dragonfruit", "pitaya"},
    {"cookie", "cookies", "biscuit", "biscuits"},
    {"soda", "pop", "softdrink"},
]

MEAT_ALIAS_TERMS = {"meat", "mutton", "goat", "lamb", "sheep", "chevon", "beef", "pork", "chicken", "turkey", "fish", "seafood"}
MUTTON_ALIAS_TERMS = {"mutton", "goat", "lamb", "sheep", "chevon"}
GROUND_MEAT_TERMS = {"keema", "kheema", "qeema", "mince", "minced", "ground"}
SPECIFIC_ITEM_FAMILIES = [
    {"mutton", "goat", "lamb", "sheep", "chevon"},
    {"keema", "kheema", "qeema", "mince", "minced", "ground"},
    {"chicken"},
    {"beef"},
    {"pork"},
    {"turkey"},
    {"fish", "seafood", "shrimp", "prawn", "prawns"},
    {"egg", "eggs"},
    {"maggi"},
    {"cilantro", "coriander", "dhania"},
    {"okra", "bhindi", "ladyfinger", "ladyfingers"},
    {"eggplant", "brinjal", "aubergine"},
    {"zucchini", "courgette"},
    {"bellpepper", "capsicum"},
    {"scallion", "scallions", "springonion", "greenonion"},
    {"arugula", "rocket"},
    {"shrimp", "prawn", "prawns"},
    {"chickpea", "chickpeas", "chana", "garbanzo"},
    {"yogurt", "yoghurt", "curd", "dahi"},
    {"flour", "atta", "maida"},
    {"lentil", "lentils", "dal", "dhal"},
    {"cassava", "yuca", "manioc"},
    {"beet", "beetroot"},
    {"sweetpotato", "yam"},
    {"bokchoy", "pakchoi"},
    {"napacabbage", "chinesecabbage"},
    {"cookie", "cookies", "biscuit", "biscuits"},
    {"soda", "pop", "softdrink"},
]
BROAD_CATEGORY_FAMILIES = [
    {"meat", "mutton", "goat", "lamb", "sheep", "chevon", "beef", "pork", "chicken", "turkey", "fish", "seafood", "keema", "kheema", "qeema", "mince", "minced", "ground"},
    {"vegetable", "vegetables", "veggie", "veggies", "produce", "okra", "bhindi", "ladyfinger", "ladyfingers", "eggplant", "brinjal", "aubergine", "zucchini", "courgette", "bellpepper", "capsicum", "scallion", "scallions", "springonion", "greenonion", "cilantro", "coriander", "arugula", "rocket", "squash", "onion", "potato", "tomato", "carrot", "beans", "methi", "curry", "amla", "daikon", "plantain", "taro", "eddo"},
    {"fruit", "fruits", "apple", "banana", "orange", "mango", "grape", "grapes", "berry", "berries", "strawberry", "blueberry", "pineapple", "melon", "watermelon", "plantain"},
    {"dairy", "milk", "cheese", "butter", "cream", "yogurt", "yoghurt", "curd", "dahi", "paneer", "ghee"},
    {"drink", "drinks", "beverage", "beverages", "soda", "pop", "softdrink", "juice", "water", "tea", "coffee"},
    {"snack", "snacks", "chips", "cookie", "cookies", "biscuit", "biscuits", "cracker", "crackers", "candy", "chocolate"},
    {"grain", "grains", "rice", "flour", "atta", "maida", "bread", "noodle", "noodles", "ramen", "maggi", "pasta"},
    {"pulse", "pulses", "lentil", "lentils", "dal", "dhal", "bean", "beans", "chickpea", "chickpeas", "chana", "garbanzo"},
    {"hardware", "garden", "gardening", "soil", "mulch", "seed", "seeds", "plant", "plants", "paint", "lumber", "wood", "tool", "tools"},
]
SEMANTIC_ITEM_FAMILIES = SPECIFIC_ITEM_FAMILIES + BROAD_CATEGORY_FAMILIES
RAW_PRODUCE_TERMS = set(BROAD_CATEGORY_FAMILIES[1]) | {"mushroom", "mushrooms"}
RAW_STAPLE_TERMS = {
    "rice", "atta", "maida", "flour", "dal", "dhal", "lentil", "lentils", "ghee",
}
BROAD_CATEGORY_QUERY_TERMS = {
    "meat", "vegetable", "vegetables", "veggie", "veggies", "produce", "fruit", "fruits", "dairy",
    "drink", "drinks", "beverage", "beverages", "snack", "snacks", "grain",
    "grains", "pulse", "pulses", "hardware", "garden", "gardening",
}

RAW_MEAT_TERMS = {
    "meat", "mutton", "goat", "lamb", "sheep", "chevon", "beef", "pork",
    "chicken", "turkey", "fish", "seafood", "mackerel", "sardine", "anchovy",
    "shrimp", "prawn", "keema", "kheema", "qeema", "mince", "minced",
    "ground", "leg", "thigh", "wingett", "wingette", "drumstick", "breast",
}

BROAD_MEAT_QUERY_TERMS = RAW_MEAT_TERMS - {"keema", "kheema", "qeema", "mince", "minced", "ground"}

RAW_MEAT_CUT_TERMS = {
    "leg", "thigh", "wingett", "wingette", "drumstick", "breast", "keema",
    "kheema", "qeema", "mince", "minced", "ground",
}

PREPARED_DISH_PHRASES = {
    "butter chicken", "pepper chicken", "chicken keema dosa", "chicken dosa",
    "fried rice", "schezwan", "biryani", "dosa", "naan", "samosa", "curry",
    "burger", "pizza", "sandwich", "combo", "meal", "plate",
    "gummies", "trolli", "medley",
}

GLOBAL_GROCERY_TERMS = [
    "india mart", "bharath bazaar", "bharat bazaar", "nwa bharath", "nwa bharat",
    "asian amigo", "indian grocery", "desi", "methi", "amla", "okra", "bhindi",
    "goat", "mutton", "lamb", "keema", "kheema", "qeema", "dal", "dhal", "atta",
    "rice", "masala", "paneer", "ghee", "curry", "squash", "chana", "garbanzo", "egg", "eggs",
    "brinjal", "eggplant", "cilantro", "coriander", "dahi", "curd", "naan",
    "zucchini", "courgette", "capsicum", "bell pepper", "spring onion", "green onion",
    "scallion", "arugula", "rocket", "prawn", "shrimp", "yuca", "cassava", "manioc",
    "beetroot", "beet", "aubergine", "yoghurt", "maida", "plantain", "taro", "eddo",
    "yam", "sweet potato", "bok choy", "pak choi", "napa cabbage", "daikon",
]

INDIAN_GROCERY_TERMS = GLOBAL_GROCERY_TERMS

COMMON_ITEM_TYPO_CORRECTIONS = {
    "clantro": "cilantro",
    "cilanto": "cilantro",
    "cilntro": "cilantro",
    "corriander": "coriander",
    # Common non-English grocery words customers may type in simple queries.
    "huevo": "egg",
    "huevos": "eggs",
    "oeuf": "egg",
    "oeufs": "eggs",
    "leche": "milk",
    "lait": "milk",
    "pollo": "chicken",
    "poulet": "chicken",
    "cordero": "lamb",
    "agneau": "lamb",
    "carne": "meat",
    "verdura": "vegetable",
    "verduras": "vegetables",
    "legume": "vegetable",
    "legumes": "vegetables",
    "corriandr": "coriander",
    "round": "round",
    "yougurt": "yogurt",
    "yoghert": "yogurt",
    "panner": "paneer",
    "paner": "paneer",
    "bindi": "bhindi",
    "bindhi": "bhindi",
    "okraa": "okra",
    "magi": "maggi",
    "magie": "maggi",
    "kema": "keema",
    "kherma": "keema",
    "khema": "keema",
    "keemae": "keema",
    "qeema": "keema",
    "kheema": "keema",
    "muton": "mutton",
    "muttton": "mutton",
    "yougart": "yogurt",
    "yogourt": "yogurt",
    "yougourt": "yogurt",
    "corriander": "coriander",
    "corriandr": "coriander",
    "coriandr": "coriander",
    "cinnamom": "cinnamon",
    "turmric": "turmeric",
    "tumeric": "turmeric",
    "cardamon": "cardamom",
    "cardemon": "cardamom",
    "safforn": "saffron",
    "saffran": "saffron",
    "cummin": "cumin",
    "fenugrek": "fenugreek",
    "dalchini": "cinnamon",
    "elaichi": "cardamom",
    "haldi": "turmeric",
    "kesar": "saffron",
    "rai": "mustard",
    "saunf": "fennel",
    "laung": "clove",
    "basmathi": "basmati",
    "dhania": "coriander",
    "jeera": "cumin",

    "cinnamonm": "cinnamon",
    "cinnamonn": "cinnamon",
    "vlcinnamon": "cinnamon",
    "vlcinnamonm": "cinnamon",
    "tomatoes": "tomato",
    "potatoes": "potato",
    "drumsticks": "drumstick",
    "mushrooms": "mushroom",
    "chappals": "chappal",
    "sticks": "stick",
    "zuccini": "zucchini",
    "zuchini": "zucchini",
    "courgett": "courgette",
    "capcicum": "capsicum",
    "capsicam": "capsicum",
    "peper": "pepper",
    "bellpeper": "bell pepper",
    "aubergin": "aubergine",
    "eggplat": "eggplant",
    "scallian": "scallion",
    "arugla": "arugula",
    "prawns": "prawn",
    "shrimps": "shrimp",
    "chikpea": "chickpea",
    "garbanso": "garbanzo",
    "beetroot": "beetroot",
}

QUERY_WORD_CORRECTIONS = {
    "wer": "where",
    "wher": "where",
    "wherre": "where",
    "whre": "where",
    "wich": "which",
    "wat": "what",
    "waht": "what",
    "whta": "what",
    "wht": "what",
    "velow": "below",
    "isted": "listed",
    "ist": "list",
    "isting": "listing",
    "pls": "please",
    "bot": "bought",
    "baught": "bought",
    "brougt": "bought",
    "cheep": "cheap",
    "chiep": "cheap",
    "chep": "cheap",
    "prise": "price",
    "prize": "price",
    "prce": "price",
    "pice": "price",
    "pic": "price",
    "pric": "price",
    "loww": "low",
    "lest": "least",
    "qunatity": "quantity",
    "quanty": "quantity",
    "barato": "cheap",
    "barata": "cheap",
    "moins": "cheap",
    "cher": "price",
    "precio": "price",
    "precios": "prices",
    "prix": "price",
    "cmg": "coming",
    "purpased": "purchased",
    "purposed": "purchased",
    "purcased": "purchased",
    "purchsing": "purchasing",
    "recipt": "receipt",
    "recipts": "receipts",
    "recepit": "receipt",
    "recepits": "receipts",
    "reciept": "receipt",
    "reciepts": "receipts",
    "reciptss": "receipts",
    "recepitss": "receipts",
    "recepitsss": "receipts",
    "recieptss": "receipts",
    "vegitables": "vegetables",
    "vegitable": "vegetable",
}

KNOWN_ITEM_TERMS = set().union(*ITEM_SYNONYM_GROUPS, set(INDIAN_GROCERY_TERMS), set(COMMON_ITEM_TYPO_CORRECTIONS.values()))

PRODUCT_SIZE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*-?\s*(GAL|GALLON|GALLONS|OZ|FL\s*OZ|LB|LBS|QT|QTS|PT|PTS|CT|EA|ML|L|LTR|LITER|LITERS|G|GM|GMS|GRAM|GRAMS)\b",
    re.IGNORECASE,
)

EXPLICIT_QTY_RE = re.compile(r"\b(QTY\s*\d+|\d+\s*@|\d+\s+EA\b|\d+\s+FOR\b|\d+\s+AT\b)", re.IGNORECASE)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        return float(value)
    except Exception:
        return default


def normalize_text(text: str | None) -> str:
    """Normalize text for receipt item matching. Keeps product meaning, removes OCR noise."""
    if not text:
        return ""
    t = str(text).lower()
    t = t.replace("lowe's", "lowes").replace("lowe’s", "lowes")
    # Common OCR corrections seen in receipts. Keep small and conservative.
    t = t.replace("pren", "prem")
    t = t.replace("prern", "prem")
    t = t.replace("prcm", "prem")
    phrase_replacements = {
        "bell pepper": "bellpepper",
        "bell peppers": "bellpepper",
        "green onion": "greenonion",
        "green onions": "greenonion",
        "spring onion": "springonion",
        "spring onions": "springonion",
        "soft drink": "softdrink",
        "soft drinks": "softdrink",
        "sweet potato": "sweetpotato",
        "sweet potatoes": "sweetpotato",
        "bok choy": "bokchoy",
        "pak choi": "bokchoy",
        "napa cabbage": "napacabbage",
        "dragon fruit": "dragonfruit",
        "garam masala": "garammasala",
        "black pepper": "blackpepper",
        "chili powder": "chilipowder",
        "coriander powder": "coriandrpowder",
        "turmeric powder": "turmericpowder",
    }
    for phrase, replacement in phrase_replacements.items():
        t = re.sub(rf"\b{re.escape(phrase)}\b", replacement, t)
    # User may say frame while receipt says prem; this is not a perfect synonym, but helps this project use case.
    t = re.sub(r"\bframe\b", "prem", t)
    t = re.sub(r"[^a-z0-9\.]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def strip_product_sizes(text: str) -> str:
    return PRODUCT_SIZE_RE.sub(" ", text or "")


def find_product_size(name: str | None) -> str | None:
    if not name:
        return None
    m = PRODUCT_SIZE_RE.search(str(name))
    if not m:
        return None
    amount = m.group(1)
    unit = re.sub(r"\s+", "", m.group(2).upper())
    return f"{amount}-{unit}"


def correct_item_token(token: str) -> str:
    if token in STOP_WORDS:
        return token
    if token in COMMON_ITEM_TYPO_CORRECTIONS:
        return COMMON_ITEM_TYPO_CORRECTIONS[token]
    if token in KNOWN_ITEM_TERMS or len(token) < 4:
        return token

    best_term = None
    best_score = 0.0
    for term in KNOWN_ITEM_TERMS:
        if " " in term or abs(len(term) - len(token)) > 2:
            continue
        score = SequenceMatcher(None, token, term).ratio()
        if score > best_score:
            best_term = term
            best_score = score

    return best_term if best_term and best_score >= 0.88 else token


def correct_item_typos(text: str) -> str:
    return normalize_text(" ".join(correct_item_token(token) for token in (text or "").split()))


def correct_query_words(text: str) -> str:
    return " ".join(QUERY_WORD_CORRECTIONS.get(token, token) for token in (text or "").split())


def merge_alias_family(families: list[set[str]], left: str, right: str) -> None:
    left_term = correct_item_typos(normalize_text(strip_product_sizes(left)))
    right_term = correct_item_typos(normalize_text(strip_product_sizes(right)))
    merged = {t for t in (left_term, right_term) if t and t not in STOP_WORDS}
    if len(merged) < 2:
        return

    touched = []
    for family in families:
        if family & merged:
            touched.append(family)

    if touched:
        for family in touched:
            merged |= family
            families.remove(family)
    families.append(merged)


def term_matches_text(term: str, text: str) -> bool:
    term_norm = correct_item_typos(normalize_text(strip_product_sizes(term)))
    text_norm = correct_item_typos(normalize_text(strip_product_sizes(text)))
    if not term_norm or not text_norm:
        return False
    if " " in term_norm:
        return term_norm in text_norm
    return term_norm in token_set(text_norm)


def family_matches_text(family: set[str], text: str) -> bool:
    return any(term_matches_text(term, text) for term in family)


def raw_item_token_set(text: str) -> set[str]:
    """Tokenize scanned receipt text without typo-correcting it into another product."""
    normalized = normalize_text(strip_product_sizes(text))
    return {t for t in normalized.split() if t and t not in STOP_WORDS and len(t) > 1}


def family_matches_item_text(family: set[str], text: str) -> bool:
    """Strict semantic match for receipt item text. Avoids correcting ROUND into GROUND."""
    text_norm = normalize_text(strip_product_sizes(text))
    item_tokens = raw_item_token_set(text)
    if not text_norm or not item_tokens:
        return False

    for term in family:
        term_norm = correct_item_typos(normalize_text(strip_product_sizes(term)))
        if not term_norm:
            continue
        if " " in term_norm and term_norm in text_norm:
            return True
        if term_norm in item_tokens:
            return True
        if len(term_norm) >= 4 and any(SequenceMatcher(None, term_norm, item_token).ratio() >= 0.92 for item_token in item_tokens):
            return True
    return False


def extract_alias_families_from_text(text: str) -> list[set[str]]:
    normalized = correct_query_words(normalize_text(text))
    if not normalized:
        return []

    patterns = [
        r"\b(.+?)\s+(?:is\s+the\s+same\s+as|is\s+same\s+as|are\s+the\s+same\s+as|are\s+same\s+as|same\s+as)\s+(.+?)\b(?:right|correct|ok|okay)?$",
        r"\b(.+?)\s+(?:equals|equal\s+to|equal|means|mean)\s+(.+?)\b(?:right|correct|ok|okay)?$",
        r"\b(.+?)\s+(?:and|or)\s+(.+?)\s+(?:are|is)\s+(?:the\s+same|same|similar|related)\b",
    ]
    families: list[set[str]] = []
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        left = clean_item_query_for_display(match.group(1))
        right = clean_item_query_for_display(match.group(2))
        if left and right and left != right:
            merge_alias_family(families, left, right)
    return families


def learned_alias_families(conversation_history: list[dict] | None, current_message: str) -> list[set[str]]:
    families: list[set[str]] = []
    for row in (conversation_history or [])[-12:]:
        if row.get("role") != "user":
            continue
        for family in extract_alias_families_from_text(str(row.get("content") or "")):
            families.append(family)
    for family in extract_alias_families_from_text(current_message):
        families.append(family)

    merged_families: list[set[str]] = []
    for family in families:
        touched = [existing for existing in merged_families if existing & family]
        if not touched:
            merged_families.append(set(family))
            continue
        merged = set(family)
        for existing in touched:
            merged |= existing
            merged_families.remove(existing)
        merged_families.append(merged)
    return merged_families


def owner_alias_cache_key(user_id: str | None = None, guest_session_id: str | None = None) -> tuple[str, str]:
    return ("user", user_id) if user_id else ("guest", guest_session_id or "__none__")


def fetch_owner_alias_families(user_id: str | None = None, guest_session_id: str | None = None) -> list[set[str]]:
    """Load aliases the user taught the agent. Safe no-op until the SQL table exists."""
    cache_key = owner_alias_cache_key(user_id, guest_session_id)
    if cache_key in _ALIAS_CACHE:
        return _ALIAS_CACHE[cache_key]

    try:
        q = supabase.table("receipt_item_aliases").select("term,alias")
        if user_id:
            q = q.eq("user_id", user_id)
        elif guest_session_id:
            q = q.eq("guest_session_id", guest_session_id)
        else:
            return []
        rows = q.limit(500).execute().data or []
    except Exception as e:
        print(f"[item_aliases] Alias table not available: {e}")
        rows = []

    families: list[set[str]] = []
    for row in rows:
        term = str(row.get("term") or "")
        alias = str(row.get("alias") or "")
        if term and alias:
            merge_alias_family(families, term, alias)

    _ALIAS_CACHE[cache_key] = families
    if len(_ALIAS_CACHE) > 20:
        _ALIAS_CACHE.clear()
    return families


def save_owner_alias_families(
    families: list[set[str]],
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> None:
    """Persist user-taught aliases when the optional alias table exists."""
    if not families or (not user_id and not guest_session_id):
        return
    rows = []
    for family in families:
        terms = sorted(t for t in family if t)
        for index, term in enumerate(terms):
            for alias in terms[index + 1:]:
                row = {
                    "term": term,
                    "alias": alias,
                    "user_id": user_id,
                    "guest_session_id": None if user_id else guest_session_id,
                }
                rows.append(row)
    if not rows:
        return
    try:
        supabase.table("receipt_item_aliases").insert(rows).execute()
        _ALIAS_CACHE.pop(owner_alias_cache_key(user_id, guest_session_id), None)
    except Exception as e:
        print(f"[item_aliases] Could not save learned aliases: {e}")


def owner_feedback_cache_key(user_id: str | None = None, guest_session_id: str | None = None) -> tuple[str, str]:
    return ("user", user_id) if user_id else ("guest", guest_session_id or "__none__")


def clear_owner_learning_caches(user_id: str | None = None, guest_session_id: str | None = None) -> None:
    _ALIAS_CACHE.pop(owner_alias_cache_key(user_id, guest_session_id), None)
    _FEEDBACK_CACHE.pop(owner_feedback_cache_key(user_id, guest_session_id), None)
    _BLOCKLIST_CACHE.pop(owner_feedback_cache_key(user_id, guest_session_id), None)
    owner_type = "user" if user_id else "guest"
    owner_id = user_id or guest_session_id or "__none__"
    for key in list(_ITEM_EVENT_CACHE.keys()):
        if key[0] == owner_type and key[1] == owner_id:
            _ITEM_EVENT_CACHE.pop(key, None)


_BLOCKLIST_CACHE: dict[tuple[str, str], set[tuple[str, str]]] = {}


def fetch_owner_feedback_examples(user_id: str | None = None, guest_session_id: str | None = None) -> list[dict]:
    """Load correction examples that act as a lightweight trained ranker."""
    cache_key = owner_feedback_cache_key(user_id, guest_session_id)
    if cache_key in _FEEDBACK_CACHE:
        return _FEEDBACK_CACHE[cache_key]

    try:
        q = supabase.table("agent_feedback").select(
            "message,response,expected_response,rating,correction_note,alias_term,alias_value,created_at"
        )
        if user_id:
            q = q.eq("user_id", user_id)
        elif guest_session_id:
            q = q.eq("guest_session_id", guest_session_id)
        else:
            return []
        rows = q.order("created_at", desc=True).limit(200).execute().data or []
    except Exception as e:
        print(f"[agent_feedback] Feedback table not available for ranking: {e}")
        rows = []

    _FEEDBACK_CACHE[cache_key] = rows
    if len(_FEEDBACK_CACHE) > 20:
        _FEEDBACK_CACHE.clear()
    return rows


def fetch_owner_blocklist(
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> set[tuple[str, str]]:
    """
    Return a set of (normalized_query_token, normalized_item_token) pairs that the user
    has explicitly marked wrong.  Any candidate whose item name contains a blocked token
    for the given query gets score forced to 0 in retrieve_item_events.

    Built from agent_feedback rows where rating is 'wrong'/'bad'/etc and the response
    text contains a recognisable item name.  Safe no-op if the table doesn't exist yet.
    """
    cache_key = owner_feedback_cache_key(user_id, guest_session_id)
    if cache_key in _BLOCKLIST_CACHE:
        return _BLOCKLIST_CACHE[cache_key]

    feedback = fetch_owner_feedback_examples(user_id, guest_session_id)
    BAD_RATINGS = {"bad", "wrong", "incorrect", "down", "thumbs_down", "negative", "1", "2"}
    blocklist: set[tuple[str, str]] = set()

    for row in feedback:
        rating = str(row.get("rating") or "").lower()
        if rating not in BAD_RATINGS:
            continue

        # The query the user asked
        raw_query = str(row.get("message") or "")
        # The bad response the agent gave (contains the wrongly matched item)
        bad_response = str(row.get("response") or "")
        # What the user said the correct answer should be (should NOT be blocked)
        correct_response = str(row.get("expected_response") or row.get("correction_note") or "")

        if not raw_query or not bad_response:
            continue

        query_norm = normalize_text(strip_product_sizes(raw_query))
        query_tokens = {t for t in query_norm.split() if t and t not in STOP_WORDS and len(t) > 2}

        # Extract item tokens from the bad response text
        bad_norm = normalize_text(strip_product_sizes(bad_response))
        bad_tokens = {t for t in bad_norm.split() if t and t not in STOP_WORDS and len(t) > 2}

        # Exclude tokens that also appear in the correct response (those are the RIGHT items)
        correct_norm = normalize_text(strip_product_sizes(correct_response))
        correct_tokens = {t for t in correct_norm.split() if t and t not in STOP_WORDS and len(t) > 2}
        blocked_tokens = bad_tokens - correct_tokens - query_tokens

        for q_tok in query_tokens:
            for b_tok in blocked_tokens:
                blocklist.add((q_tok, b_tok))

    _BLOCKLIST_CACHE[cache_key] = blocklist
    if len(_BLOCKLIST_CACHE) > 20:
        _BLOCKLIST_CACHE.clear()
    return blocklist


def is_blocklisted(query: str, item_name: str, blocklist: set[tuple[str, str]]) -> bool:
    """Return True if any (query_token, item_token) pair from the blocklist matches."""
    if not blocklist:
        return False
    q_tokens = {t for t in normalize_text(strip_product_sizes(query)).split() if t and t not in STOP_WORDS and len(t) > 2}
    i_tokens = {t for t in normalize_text(strip_product_sizes(item_name)).split() if t and t not in STOP_WORDS and len(t) > 2}
    for q_tok in q_tokens:
        for i_tok in i_tokens:
            if (q_tok, i_tok) in blocklist:
                return True
    return False


def feedback_query_similarity(query: str, feedback_message: str) -> float:
    q = clean_item_query_for_display(query)
    f = clean_item_query_for_display(feedback_message)
    if not q or not f:
        return 0.0
    q_tokens = token_set(q)
    f_tokens = token_set(f)
    overlap = len(q_tokens & f_tokens) / max(1, len(q_tokens | f_tokens))
    seq = SequenceMatcher(None, q, f).ratio()
    return max(overlap, seq * 0.75)


def item_mentioned_in_text(item_name: str, text: str | None) -> bool:
    if not item_name or not text:
        return False
    item_norm = normalize_text(strip_product_sizes(item_name))
    text_norm = normalize_text(strip_product_sizes(text))
    if item_norm and re.search(rf"\b(?:not|no|instead\s+of|rather\s+than)\s+{re.escape(item_norm)}\b", text_norm):
        return False
    if item_norm and item_norm in text_norm:
        return True
    item_tokens = raw_item_token_set(item_name)
    text_tokens = raw_item_token_set(text)
    meaningful = {t for t in item_tokens if t not in {"fresh", "large", "small", "round", "cut"}}
    if not meaningful:
        return False
    return len(meaningful & text_tokens) >= min(len(meaningful), 2)


def learned_rank_adjustment(query: str, event: dict, feedback_examples: list[dict]) -> float:
    """Boost/penalize receipt candidates from the user's prior corrections."""
    if not feedback_examples:
        return 0.0

    item_name = str(event.get("item_original") or "")
    adjustment = 0.0
    for row in feedback_examples[:120]:
        similarity = feedback_query_similarity(query, str(row.get("message") or ""))
        if similarity < 0.42:
            continue

        positive_text = " ".join(
            str(row.get(key) or "")
            for key in ("expected_response", "correction_note", "alias_value")
        )
        negative_text = str(row.get("response") or "")
        rating = str(row.get("rating") or "").lower()

        if item_mentioned_in_text(item_name, positive_text):
            adjustment += 0.22 * similarity
        if rating in {"bad", "wrong", "incorrect", "down", "thumbs_down", "negative", "1", "2"}:
            if item_mentioned_in_text(item_name, negative_text) and not item_mentioned_in_text(item_name, positive_text):
                adjustment -= 0.18 * similarity

    return max(-0.35, min(0.35, adjustment))


def google_meaning_snippets(query: str) -> str:
    """Optional Google Custom Search lookup for public item meaning."""
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY") or os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_SEARCH_ENGINE_ID") or os.getenv("GOOGLE_CSE_ID")
    if not api_key or not cx:
        return ""

    params = urlencode({
        "key": api_key,
        "cx": cx,
        "q": f"{query} food product aliases common names",
        "num": 5,
    })
    url = f"https://www.googleapis.com/customsearch/v1?{params}"
    try:
        with urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"[google_meaning] Search unavailable: {e}")
        return ""

    snippets = []
    for item in payload.get("items") or []:
        title = item.get("title") or ""
        snippet = item.get("snippet") or ""
        if title or snippet:
            snippets.append(f"{title}. {snippet}")
    return "\n".join(snippets[:5])


def public_meaning_alias_families(query: str) -> list[set[str]]:
    """
    Use optional Google snippets only to understand possible aliases.
    Receipt prices/counts still come only from receipt RAG.
    """
    normalized_query = clean_item_query_for_display(query)
    if not normalized_query or len(normalized_query) < 3:
        return []
    if normalized_query in _PUBLIC_MEANING_CACHE:
        return _PUBLIC_MEANING_CACHE[normalized_query]

    snippets = google_meaning_snippets(normalized_query)
    if not snippets:
        _PUBLIC_MEANING_CACHE[normalized_query] = []
        return []

    prompt = f"""Extract only common grocery/retail item aliases for this query from the Google snippets.
Return strict JSON only: {{"aliases":["alias 1","alias 2"]}}
Rules:
- Include only names that mean the same product/item family.
- Do not include brands, stores, recipes, adjectives, or unrelated items.
- Max 8 aliases.

Query: {normalized_query}
Google snippets:
{snippets}
"""
    aliases = []

    try:
        if claude_client is not None:
            response = claude_client.messages.create(
                model=SONNET_MODEL,
                max_tokens=220,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
            data = parse_json_object(text)
            aliases = [clean_item_query_for_display(str(a)) for a in data.get("aliases") or []]
    except Exception as e:
        print(f"[google_meaning] Alias extraction unavailable: {e}")
        aliases = []

    family = {normalized_query, *[a for a in aliases if a and a != normalized_query]}
    families = [family] if len(family) > 1 else []
    _PUBLIC_MEANING_CACHE[normalized_query] = families
    if len(_PUBLIC_MEANING_CACHE) > 50:
        _PUBLIC_MEANING_CACHE.clear()
    return families


def token_set(text: str) -> set[str]:
    normalized = correct_item_typos(normalize_text(strip_product_sizes(text)))
    return {t for t in normalized.split() if t and t not in STOP_WORDS and len(t) > 1}


def extract_query_item(user_message: str) -> str:
    """Extract likely item text from a natural language question."""
    msg = correct_query_words(normalize_text(user_message))
    msg = re.sub(r"\b\d+\s+(?:buy|buys|bought|purchase|purchases|times)\b", " ", msg)
    msg = re.sub(r"\b(?:buy|buys|bought|purchase|purchases|times)\s+\d+\b", " ", msg)
    # Remove common question words but keep item descriptors.
    toks = [t for t in msg.split() if t not in STOP_WORDS and not t.isdigit()]
    # If nothing remains, return original normalized string.
    item_text = " ".join(toks).strip() or msg
    return correct_item_typos(item_text)


SHOPPING_LIST_MARKERS = [
    "below listed items",
    "listed items",
    "following items",
    "these items",
    "to buy",
]

SHOPPING_LIST_NOISE_WORDS = STOP_WORDS | {
    "table", "tabular", "form", "listing", "listed", "below", "following",
    "shop", "shopping", "available", "clear", "from", "best", "price",
    "prices", "buy", "where", "current", "market", "overpaid", "overpay",
    "can", "you", "find", "paid", "please", "include", "including", "but",
    "vegetable", "vegetables", "veggie", "veggies", "produce",
    "also", "same", "table", "grocery", "raw", "dont", "don", "count", "unknown", "as",
    "pantry", "if", "found",
    # query adverbs and intensifiers that are never item names
    "cheepest", "cheapeast", "lowest", "cheaply", "cheapest",
    # query modifier words that describe what kind of answer the user wants
    "full", "history", "trend", "trends", "all", "complete", "entire",
    "show", "tell", "give", "display", "view", "recent", "latest",
    # category/descriptor prefixes — never a specific product name
    "spice", "spices", "grocery", "groceries", "staple", "staples",
    "item", "items", "product", "products", "ingredient", "ingredients",
    # conversational yes/no replies — never item names
    "no", "yes", "ok", "okay", "yeah", "yep", "nope", "sure", "fine",
    # modifier words that describe HOW but not WHAT
    "only", "just", "separately", "together", "alone", "already",
    "fresh", "frozen", "organic", "natural", "cooked",
    "small", "medium", "large", "big", "little",
    "more", "less", "extra", "few", "some", "any", "each",
    "type", "types", "kind", "kinds", "variety",
    "per",
    "above", "below", "usual", "normal", "regular",
}

SHOPPING_LIST_BOUNDARY_TERMS = (
    KNOWN_ITEM_TERMS
    | BROAD_CATEGORY_QUERY_TERMS
    | MEAT_ALIAS_TERMS
    | GROUND_MEAT_TERMS
    | {
        "beef", "sirloin", "tomato", "potato", "sunflower", "cilantro",
        "coriander", "cinnamon", "mushroom", "chappal", "drumstick",
        "oil", "mutton", "goat", "lamb", "sweetpotato", "coconut",
        "saffron", "turmeric", "cardamom", "garam", "masala", "garammasala",
        "cumin", "fenugreek", "fennel", "clove", "cloves",
        "pepper", "blackpepper", "chilipowder", "coriandrpowder",
        "saffron", "cumin", "jeera", "mustard", "rai", "fenugreek", "methi",
        "cardamom", "elaichi", "clove", "cloves", "laung",
        "fennel", "saunf", "anise", "coriander", "dhania",
        "haldi", "turmericpowder", "chaat", "amchur",
        "bay", "bayleaf", "oregano", "thyme", "basil", "rosemary",

        "rice", "atta", "dal", "ghee", "paneer", "milk", "yogurt",
        "onion", "carrot", "okra", "eggplant", "potato", "tomato",
    }
)
SHOPPING_LIST_TRAILING_DESCRIPTOR_TERMS = {
    "leg", "cut", "stick", "round", "small", "white", "oil", "kheema",
    "keema", "drumstick", "masala", "chunk", "slice", "sliced", "piece",
    "pieces", "bone", "boneless", "fresh", "raw", "whole", "half",
}


def _correct_preserving_separators(text: str) -> str:
    def replace(match: re.Match) -> str:
        token = match.group(0).lower()
        return QUERY_WORD_CORRECTIONS.get(token, COMMON_ITEM_TYPO_CORRECTIONS.get(token, token))

    return re.sub(r"[A-Za-z]+", replace, str(text or "").lower())


def clean_shopping_list_item(candidate: str) -> str:
    text = correct_item_typos(correct_query_words(normalize_text(strip_product_sizes(candidate))))
    words = [word for word in text.split() if word not in SHOPPING_LIST_NOISE_WORDS and not word.isdigit()]
    return " ".join(words).strip()


def split_space_separated_shopping_items(text: str) -> list[str]:
    tokens = [token for token in clean_shopping_list_item(text).split() if token]
    if len(tokens) < 2:
        return [" ".join(tokens)] if tokens else []

    groups: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        is_boundary = token in SHOPPING_LIST_BOUNDARY_TERMS
        current_has_boundary = any(t in SHOPPING_LIST_BOUNDARY_TERMS for t in current)
        if current and is_boundary and current_has_boundary and token not in SHOPPING_LIST_TRAILING_DESCRIPTOR_TERMS:
            groups.append(current)
            current = [token]
        else:
            current.append(token)
    if current:
        groups.append(current)

    cleaned_groups = []
    for group in groups:
        text_group = clean_shopping_list_item(" ".join(group))
        if text_group and token_set(text_group):
            cleaned_groups.append(text_group)
    return cleaned_groups


def split_failed_shopping_item(item: str) -> list[str]:
    """Self-heal a failed combined item like 'cilantro sweetpotato' into sub-items."""
    tokens = [token for token in clean_shopping_list_item(item).split() if token]
    if len(tokens) < 2:
        return []
    parts: list[str] = []
    current: list[str] = []
    for token in tokens:
        starts_new_item = (
            current
            and token in SHOPPING_LIST_BOUNDARY_TERMS
            and any(t in SHOPPING_LIST_BOUNDARY_TERMS for t in current)
            and token not in SHOPPING_LIST_TRAILING_DESCRIPTOR_TERMS
        )
        if starts_new_item:
            parts.append(" ".join(current))
            current = [token]
        else:
            current.append(token)
    if current:
        parts.append(" ".join(current))
    cleaned = [clean_shopping_list_item(part) for part in parts]
    cleaned = [part for part in cleaned if part and part != item]
    return cleaned if len(cleaned) > 1 else []


def extract_shopping_list_items(message: str) -> list[str]:
    """Extract multi-item shopping requests without letting request wording become an item."""
    import re as _sli_re
    # Drop exclusion tails before splitting, e.g. "..., but do not count oil burner,
    # mushroom gummies, fried rice, or cooked meals".
    message = _sli_re.sub(
        r"\b(?:but\s+)?(?:do\s+not|dont|don\s+t)\s+(?:count|include|match|use|return|show)\b.*$",
        " ", str(message or ""), flags=_sli_re.IGNORECASE,
    )
    message = _sli_re.sub(
        r"\b(?:exclude|excluding|except|without|avoid|ignore|skip)\b.*$",
        " ", str(message or ""), flags=_sli_re.IGNORECASE,
    )
    # Remove mid-sentence negation clauses: "X, not gummies", "X excluding Y".
    # Use a lookbehind so "no, month wise" (starts with no) is NOT stripped.
    message = _sli_re.sub(
        r"(?<=[\w,])\s*,?\s*\b(?:not|except|excluding|avoid|without|ignore|skip|but\s+not|rather\s+than)\s+[\w\s]{1,40}",
        " ", str(message or ""), flags=_sli_re.IGNORECASE,
    ).strip()
    raw = _correct_preserving_separators(message).replace("\r", "\n")
    raw = re.sub(r"\bto\s+but\b", "to buy", raw)
    raw = re.sub(r"\b(?:where\s+to\s+buy\s+from|where\s+to\s+buy|buy\s+from)\b", " ", raw)
    nonempty_lines = [line.strip(" :-\t") for line in raw.split("\n") if line.strip(" :-\t")]
    first_line = nonempty_lines[0] if nonempty_lines else ""

    if len(nonempty_lines) > 1 and any(term in first_line for term in ["price", "table", "tabular", "listing", "buy"]):
        item_blob = "\n".join(nonempty_lines[1:])
    else:
        item_blob = raw
        for marker in SHOPPING_LIST_MARKERS:
            index = item_blob.rfind(marker)
            if index != -1:
                item_blob = item_blob[index + len(marker):]
                break

    pieces = re.split(r"[\n,;]+|\s+\band\b\s+|(?:^|\s)[-*•]\s*", item_blob)
    items: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        cleaned = clean_shopping_list_item(piece)
        candidates = split_space_separated_shopping_items(cleaned) if len(token_set(cleaned)) > 2 else [cleaned]
        for candidate in candidates:
            tokens = token_set(candidate)
            if not candidate or not tokens or candidate in seen:
                continue
            if len(tokens) > 6:
                continue
            seen.add(candidate)
            items.append(candidate)

    normalized = correct_query_words(normalize_text(raw))
    if (
        re.search(r"\bunknown\s+(?:veggie|vegetable|item|product)\b", normalized)
        and not re.search(r"\b(?:do\s+not|dont|don\s+t)\s+count\s+unknown\b", normalized)
        and "unknown veggie" not in seen
    ):
        items.append("unknown veggie")
    return items[:20]


def looks_like_shopping_list_price_request(message: str) -> bool:
    m = correct_query_words(normalize_text(message))
    if any(term in m for term in ["current market", "market price", "market prices", "overpaid", "overpay"]):
        return False
    tokens = set(m.split())
    inferred_items = extract_shopping_list_items(message)
    if len(inferred_items) < 2:
        return False
    has_price_intent = bool(tokens & {"price", "prices", "cheap", "cheapest", "best", "lowest", "least", "where", "buy", "compare"})
    # A comma-separated or newline-separated list of 2+ distinct items implicitly asks
    # for prices even without explicit price words (e.g. "coconut oil, milk, rice")
    has_explicit_list = (
        "," in str(message)
        or "\n" in str(message)
        or bool(tokens & {"table", "tabular", "listing", "listed"})
        or any(marker in m for marker in SHOPPING_LIST_MARKERS)
    )
    has_list_shape = has_explicit_list or len(inferred_items) >= 2
    # Require at least 2 real product items (not noise/conversational words)
    real_items = [
        item for item in inferred_items
        if token_set(item) - SHOPPING_LIST_NOISE_WORDS
    ]
    if len(real_items) < 2:
        return False
    # Explicit list (commas/newlines) with real items always triggers
    if has_explicit_list:
        return True
    if re.search(r"\b(?:what\s+i\s+paid\s+for|what\s+did\s+i\s+pay\s+for|find\s+what\s+i\s+paid|paid\s+for)\b", m):
        return False
    # Space-separated list: 3+ real items triggers even without price words
    # (e.g. "rice atta dal ghee" is clearly a shopping list)
    if len(real_items) >= 3:
        return True
    # 2-item space-separated list needs explicit price intent
    return has_price_intent and has_list_shape


def all_semantic_families(extra_families: list[set[str]] | None = None) -> list[set[str]]:
    # User-taught/public aliases should win before broad categories like fruit or meat.
    return (extra_families or []) + SEMANTIC_ITEM_FAMILIES



# Tokens that are shape/modifier descriptors with no standalone product meaning.
# They are valid inside compound queries but should never be emitted as
# single-token search variants (otherwise "round beef" → "round" matches cinnamon rounds).
_DESCRIPTOR_ONLY_TOKENS: frozenset[str] = frozenset({
    "round", "cut", "slice", "sliced", "chunk", "piece", "pieces",
    "bone", "boneless", "lean", "whole", "half", "fresh", "frozen",
    "raw", "cooked", "dried", "powdered", "ground",
    "small", "medium", "large", "big", "mini",
})

def expand_query_variants(query: str, extra_families: list[set[str]] | None = None) -> list[str]:
    """Generate typo-corrected and synonym-expanded item queries for RAG retrieval."""
    base = correct_item_typos(normalize_text(query))
    tokens = [t for t in base.split() if t and t not in STOP_WORDS]
    variants: list[str] = []

    def add(value: str) -> None:
        value = correct_item_typos(normalize_text(value))
        if value and value not in variants:
            variants.append(value)

    add(base)

    for token in tokens:
        # Don't generate standalone variants for pure shape/modifier descriptors
        if len(tokens) == 1 or token not in _DESCRIPTOR_ONLY_TOKENS:
            add(token)
        for group in ITEM_SYNONYM_GROUPS:
            if token in group:
                for alias in sorted(group):
                    add(alias)
                    if len(tokens) > 1:
                        replaced = [alias if t == token else t for t in tokens]
                        add(" ".join(replaced))

    for family in all_semantic_families(extra_families):
        if family_matches_text(family, base):
            for alias in sorted(family):
                add(alias)
                if len(tokens) > 1:
                    for token in tokens:
                        if token in family:
                            replaced = [alias if t == token else t for t in tokens]
                            add(" ".join(replaced))

    # Preserve useful food descriptors while expanding meat aliases.
    if "meat" in tokens:
        add("goat")
        add("mutton")
        add("lamb")
        add("beef")
        add("pork")
        add("chicken")
        add("turkey")
        add("fish")
        add("seafood")
        add("keema")
    if "mutton" in tokens and "keema" in tokens:
        add("goat keema")
        add("lamb keema")
    if "mutton" in tokens:
        add("goat")
        add("goat meat")
        add("goat keema")
        add("goat leg")
        add("lamb")
        add("lamb meat")
        add("sheep")
    if "goat" in tokens and "keema" in tokens:
        add("mutton keema")
        add("lamb keema")
    if "goat" in tokens:
        add("mutton")
        add("mutton keema")
        add("lamb")
        add("sheep")

    return variants


def query_semantic_family(query: str, extra_families: list[set[str]] | None = None) -> str | None:
    query_tokens = token_set(query)
    if query_tokens & MUTTON_ALIAS_TERMS:
        for index, family in enumerate(all_semantic_families(extra_families)):
            if family == {"mutton", "goat", "lamb", "sheep", "chevon"}:
                return f"family:{index}"

    # Specific item names must win before broad categories. Example:
    # "cilantro" should match coriander/cilantro only, not every vegetable.
    for index, family in enumerate((extra_families or []) + SPECIFIC_ITEM_FAMILIES):
        if family_matches_text(family, query):
            return f"family:{index}"

    if query_tokens & BROAD_CATEGORY_QUERY_TERMS:
        families = all_semantic_families(extra_families)
        for broad_family in BROAD_CATEGORY_FAMILIES:
            if query_tokens & broad_family:
                for index, family in enumerate(families):
                    if family is broad_family or family == broad_family:
                        return f"family:{index}"

    for index, family in enumerate(all_semantic_families(extra_families)):
        if family_matches_text(family, query):
            return f"family:{index}"
    return None


def event_matches_semantic_family(event: dict, family: str | None, extra_families: list[set[str]] | None = None) -> bool:
    if not family:
        return True
    item_text = event.get("item_original") or ""
    if family.startswith("family:"):
        try:
            family_terms = all_semantic_families(extra_families)[int(family.split(":", 1)[1])]
        except Exception:
            return True
        return family_matches_item_text(family_terms, item_text)
    semantic_family = query_semantic_family(family, extra_families)
    if semantic_family and semantic_family != family:
        return event_matches_semantic_family(event, semantic_family, extra_families)
    family_tokens = token_set(family)
    if family_tokens <= BROAD_CATEGORY_QUERY_TERMS:
        return False
    return bool(family_tokens & raw_item_token_set(item_text))


def required_query_families(query: str, extra_families: list[set[str]] | None = None) -> list[set[str]]:
    """Specific terms in the user's query must remain present in matched items."""
    query_tokens = token_set(query)
    if query_tokens <= BROAD_CATEGORY_QUERY_TERMS:
        return []
    required: list[set[str]] = []

    for family in (extra_families or []) + ITEM_SYNONYM_GROUPS + SPECIFIC_ITEM_FAMILIES:
        if query_tokens & family and family not in required:
            required.append(family)

    return required


def required_anchor_tokens(query: str) -> set[str]:
    """Meaningful user item words that should not disappear from matches."""
    tokens = token_set(query)
    if not tokens:
        return set()

    # Pure broad-category questions should remain broad:
    # "cheap meat", "cheap vegetables", "snacks" etc.
    if tokens <= BROAD_CATEGORY_QUERY_TERMS:
        return set()

    broad_only = {
        "meat", "vegetable", "vegetables", "produce", "fruit", "fruits", "dairy",
        "drink", "drinks", "beverage", "beverages", "snack", "snacks", "grain",
        "grains", "pulse", "pulses", "hardware", "garden", "gardening",
    }
    return {token for token in tokens if token not in broad_only}


def is_specific_item_query(query: str) -> bool:
    return bool(required_anchor_tokens(query) or required_query_families(query))


def event_has_anchor_evidence(event: dict, query: str) -> bool:
    anchors = required_anchor_tokens(query)
    if not anchors:
        return True

    item_text = event.get("item_original") or ""
    item_tokens = raw_item_token_set(item_text)
    if anchors & item_tokens:
        return True

    for anchor in anchors:
        if any(anchor in family and family.intersection(item_tokens) for family in ITEM_SYNONYM_GROUPS):
            return True
        if any(anchor in family and family.intersection(item_tokens) for family in SPECIFIC_ITEM_FAMILIES):
            return True
        if any(SequenceMatcher(None, anchor, item_token).ratio() >= 0.92 for item_token in item_tokens):
            return True

    return False


def query_anchor_coverage_count(event: dict, query: str) -> int:
    anchors = required_anchor_tokens(query)
    if not anchors:
        return 0
    item_tokens = raw_item_token_set(event.get("item_original") or "")
    covered = 0
    for anchor in anchors:
        if anchor in item_tokens:
            covered += 1
            continue
        if any(anchor in family and family.intersection(item_tokens) for family in ITEM_SYNONYM_GROUPS):
            covered += 1
            continue
        if any(anchor in family and family.intersection(item_tokens) for family in SPECIFIC_ITEM_FAMILIES):
            covered += 1
            continue
        if any(SequenceMatcher(None, anchor, item_token).ratio() >= 0.92 for item_token in item_tokens):
            covered += 1
    return covered


def looks_like_partial_combined_item_match(query: str, events: list[dict]) -> bool:
    """Detect when one receipt row matched only part of a likely multi-product query."""
    anchors = required_anchor_tokens(query)
    if len(anchors) < 3 or not events:
        return False
    max_covered = max(query_anchor_coverage_count(event, query) for event in events)
    if max_covered >= len(anchors):
        return False
    # If a query has three or more independent product words but the best receipt
    # row only explains one or two, recover as multiple items before answering.
    return max_covered <= max(1, len(anchors) - 2)


def event_satisfies_required_families(event: dict, query: str, extra_families: list[set[str]] | None = None) -> bool:
    required = required_query_families(query, extra_families)
    item_text = event.get("item_original") or ""
    query_tokens = token_set(query)
    item_tokens = raw_item_token_set(item_text)
    if query_tokens <= {"egg", "eggs"} and item_tokens & {"noodle", "noodles", "pasta", "ramen"}:
        return False
    if required and not all(family_matches_item_text(family, item_text) for family in required):
        return False

    anchors = required_anchor_tokens(query)
    if not anchors:
        return True
    descriptor_terms = {"stick", "round", "small", "white", "cut"}
    required_anchors = anchors - descriptor_terms
    if len(required_anchors) > 1 and query_anchor_coverage_count(event, " ".join(sorted(required_anchors))) < len(required_anchors):
        return False

    return event_has_anchor_evidence(event, query)


def verified_match_level(event: dict, query: str, score: float | None = None, extra_families: list[set[str]] | None = None) -> str:
    """Classify match safety for final answers: high, medium, category, or none."""
    if not event_satisfies_required_families(event, query, extra_families):
        return "none"

    anchors = required_anchor_tokens(query)
    if not anchors:
        return "category"

    item_tokens = raw_item_token_set(event.get("item_original") or "")
    if anchors & item_tokens:
        return "high"

    for anchor in anchors:
        if any(anchor in family and family.intersection(item_tokens) for family in ITEM_SYNONYM_GROUPS):
            return "high"
        if any(anchor in family and family.intersection(item_tokens) for family in SPECIFIC_ITEM_FAMILIES):
            return "high"
        if any(SequenceMatcher(None, anchor, item_token).ratio() >= 0.92 for item_token in item_tokens):
            return "medium"

    if isinstance(score, (int, float)) and score >= 0.9:
        return "medium"
    return "none"


def query_is_specific_mutton(query: str) -> bool:
    return bool(token_set(query) & MUTTON_ALIAS_TERMS)


def minimum_match_score(query: str, semantic_family: str | None) -> float:
    """Use strict scores unless a semantic family is already constraining candidates."""
    tokens = token_set(query)
    if query_is_specific_mutton(query):
        return 0.72
    if semantic_family:
        return 0.50
    if len(tokens) <= 1:
        return 0.82
    return 0.68


def minimum_candidate_score(query: str, semantic_family: str | None) -> float:
    if semantic_family:
        return 0.50
    return max(0.76, minimum_match_score(query, semantic_family))


def synonym_overlap_score(q_tokens: set[str], i_tokens: set[str]) -> float:
    """Return conservative synonym coverage for product search terms."""
    if not q_tokens or not i_tokens:
        return 0.0

    hits = 0
    for q_token in q_tokens:
        if q_token in i_tokens:
            hits += 1
            continue
        for group in ITEM_SYNONYM_GROUPS:
            if q_token in group and group.intersection(i_tokens):
                hits += 1
                break

    return hits / max(1, min(len(q_tokens), len(i_tokens)))


# Words that qualify or transform an item into a different product.
# If a candidate has one of these qualifiers and the query does NOT, the match is penalized.
ITEM_QUALIFIER_WORDS: frozenset[str] = frozenset({
    "gummies", "gummy", "supplement", "supplements", "capsule", "capsules",
    "tablet", "tablets", "pill", "pills", "vitamin", "vitamins",
    "burner", "diffuser", "lamp", "candle", "wax", "fragrance",
    "fried", "instant", "mix", "powder", "extract", "concentrate",
    "spray", "lotion", "cream", "gel", "soap", "detergent",
    "chips", "cracker", "crackers", "cookie", "cookies", "biscuit", "biscuits",
    "sauce", "dressing", "syrup", "vinegar",
    "candy", "chocolate", "caramel",
    "seed", "seeds",  # coconut oil ≠ coconut seeds
})


def _qualifier_penalty(q_tokens: set[str], i_tokens: set[str]) -> float:
    """
    Return a score penalty when the candidate item has qualifier words the query lacks.
    e.g. query={"mushroom"}, item={"mushroom","gummies"} → penalty -0.5
         query={"coconut","oil"}, item={"oil","burner"} → penalty -0.5
    """
    extra_qualifiers = (i_tokens & ITEM_QUALIFIER_WORDS) - q_tokens
    if extra_qualifiers:
        return -0.5
    return 0.0


def _asymmetric_subset_penalty(q_tokens: set[str], i_tokens: set[str]) -> float:
    """
    If the query tokens are NOT a subset of item tokens (after removing known qualifiers),
    and the score would otherwise pass, penalise.
    e.g. query={"round"}, item={"ground","meat"} — "round" is not in item tokens → penalty.
    Only applied when query is 1 token to avoid over-penalizing compound queries.
    """
    if len(q_tokens) != 1:
        return 0.0
    q_token = next(iter(q_tokens))
    i_tokens_clean = i_tokens - ITEM_QUALIFIER_WORDS
    if q_token not in i_tokens_clean:
        # Check for fuzzy near-match (catches OCR variants of the *same* root word)
        for it in i_tokens_clean:
            if SequenceMatcher(None, q_token, it).ratio() >= 0.92:
                return 0.0
        return -0.4
    return 0.0


def item_match_score(query: str, item_name: str, code: str | None = None) -> float:
    q_norm = correct_item_typos(normalize_text(query))
    i_norm = normalize_text(item_name)
    q_no_size = normalize_text(strip_product_sizes(q_norm))
    i_no_size = normalize_text(strip_product_sizes(i_norm))

    if not q_norm or not i_norm:
        return 0.0

    q_tokens = token_set(q_norm)
    i_tokens = token_set(i_norm)

    # Pre-compute penalties applied universally to every score path so that
    # qualifier words (gummies, burner, fried, etc.) always reduce a match score.
    qualifier_pen  = _qualifier_penalty(q_tokens, i_tokens)
    asymmetric_pen = _asymmetric_subset_penalty(q_tokens, i_tokens)

    # ── Whole-word token-set containment ──
    # Use token sets instead of raw substring so "round" does NOT match "ground".
    if q_tokens and i_tokens:
        if q_tokens <= i_tokens or i_tokens <= q_tokens:
            base = 1.0
            return max(0.0, round(base + qualifier_pen + asymmetric_pen, 4))

    # Size-stripped token containment
    q_no_size_tokens = token_set(q_no_size)
    i_no_size_tokens = token_set(i_no_size)
    if q_no_size_tokens and i_no_size_tokens:
        if q_no_size_tokens <= i_no_size_tokens or i_no_size_tokens <= q_no_size_tokens:
            base = 0.92
            return max(0.0, round(base + qualifier_pen + asymmetric_pen, 4))

    if not q_tokens or not i_tokens:
        overlap_score = 0.0
    else:
        overlap = len(q_tokens & i_tokens)
        overlap_score = overlap / max(1, min(len(q_tokens), len(i_tokens)))

    seq_score = SequenceMatcher(None, q_no_size, i_no_size).ratio()
    synonym_score = synonym_overlap_score(q_tokens, i_tokens)
    token_fuzzy_score = 0.0
    if q_tokens and i_tokens:
        token_fuzzy_score = max(
            SequenceMatcher(None, qt, it).ratio()
            for qt in q_tokens
            for it in i_tokens
        )

    # Short one-word product searches need stricter matching to avoid
    # "maggi" matching "mango" etc.
    if len(q_tokens) == 1:
        q_token = next(iter(q_tokens))
        if q_token in i_tokens:
            base = 1.0
        elif synonym_score >= 1.0:
            base = 0.88
        elif token_fuzzy_score >= 0.82:
            base = round(token_fuzzy_score, 4)
        else:
            return 0.0
        return max(0.0, round(base + qualifier_pen + asymmetric_pen, 4))

    # If user includes a product code/barcode, honor it strongly.
    if code and str(code) in q_norm:
        return 1.0

    synonym_boosted_score = 0.0
    if synonym_score > 0:
        synonym_boosted_score = min(0.94, 0.72 + (synonym_score * 0.22))

    raw_score = round(max(seq_score, overlap_score, synonym_boosted_score, token_fuzzy_score * 0.85), 4)
    return max(0.0, round(raw_score + qualifier_pen + asymmetric_pen, 4))


PRICE_MEMORY_TOKEN_STOPWORDS = {
    "each", "ea", "item", "items", "fresh", "large", "small", "medium",
    "food", "non", "the", "and", "with", "good", "price", "current",
    "buy", "now", "for", "this", "that", "should",
}


def is_valid_receipt_item_name(value: Any) -> bool:
    normalized = normalize_text(value)
    if not normalized:
        return False
    if normalized in {"unknown", "unknown item", "item", "nan", "none", "null"}:
        return False
    return bool(token_set(normalized))


def price_memory_compare_tokens(value: str) -> set[str]:
    return {
        token
        for token in token_set(strip_product_sizes(normalize_text(value)))
        if token not in PRICE_MEMORY_TOKEN_STOPWORDS and len(token) > 2 and not _safe_float(token, None)
    }


def price_memory_match_is_comparable(query: str, item_name: str, score: float) -> bool:
    q_tokens = price_memory_compare_tokens(query)
    i_tokens = price_memory_compare_tokens(item_name)
    if not q_tokens or not i_tokens:
        return False
    if q_tokens <= i_tokens:
        return True
    if len(q_tokens) == 1 and i_tokens <= q_tokens:
        return True

    for q_token in q_tokens:
        if any(q_token in family and family.intersection(i_tokens) for family in ITEM_SYNONYM_GROUPS + SPECIFIC_ITEM_FAMILIES):
            if len(q_tokens) == 1:
                return True

    overlap = q_tokens & i_tokens
    if len(q_tokens) == 1:
        return bool(overlap) or score >= 0.92
    if len(q_tokens) == 2:
        return len(overlap) == 2 or score >= 0.94

    coverage = len(overlap) / max(1, len(q_tokens))
    return (len(overlap) >= 2 and coverage >= 0.6) or score >= 0.94


def apply_owner_filter(q, user_id: str | None = None, guest_session_id: str | None = None):
    if user_id:
        return q.eq("user_id", user_id)
    if guest_session_id:
        return q.eq("is_guest", True).eq("guest_session_id", guest_session_id)
    return q.eq("id", "__no_access__")


def fetch_owner_receipts(user_id: str | None = None, guest_session_id: str | None = None, limit: int = 200) -> list[dict]:
    owner_type = "user" if user_id else "guest"
    owner_id = user_id or guest_session_id or "__none__"
    cache_key = (owner_type, owner_id, limit)
    if cache_key in _RECEIPT_CACHE:
        return _RECEIPT_CACHE[cache_key]

    q = supabase.table("receipts").select(RECEIPT_SELECT)
    q = apply_owner_filter(q, user_id, guest_session_id)
    result = q.order("created_at", desc=True).limit(limit).execute()
    receipts = result.data or []
    _RECEIPT_CACHE[cache_key] = receipts
    if len(_RECEIPT_CACHE) > 20:
        _RECEIPT_CACHE.clear()
    return receipts


def _item_row_to_event(row: dict) -> dict:
    name = row.get("item_name_original") or ""
    quantity = _safe_float(row.get("quantity"), 1.0) or 1.0
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return {
        "receipt_id": row.get("receipt_id"),
        "line_index": row.get("line_index"),
        "store": row.get("store") or "Unknown Store",
        "address": None,
        "date": row.get("purchase_date") or (row.get("receipt_created_at") or "")[:10],
        "time": None,
        "created_at": row.get("receipt_created_at"),
        "code": row.get("code"),
        "item_original": name,
        "item_normalized": row.get("item_name_normalized") or normalize_text(name),
        "product_size": row.get("product_size"),
        "quantity": quantity,
        "raw_quantity_from_scan": _safe_float(row.get("raw_quantity"), quantity),
        "unit": row.get("unit") or "each",
        "unit_price": _safe_float(row.get("unit_price"), None),
        "line_price": _safe_float(row.get("line_price"), None),
        "source": row.get("source") or "printed",
        "confidence": row.get("confidence"),
        "metadata": metadata,
        "source_page": metadata.get("page") or metadata.get("source_page") or metadata.get("page_index"),
        "source_bbox": metadata.get("bbox") or metadata.get("bounding_box") or metadata.get("source_bbox"),
        "source_text": metadata.get("line_text") or metadata.get("source_text") or name,
        "source_image_hash": metadata.get("image_hash") or metadata.get("source_image_hash"),
        "explicit_quantity": bool(row.get("explicit_quantity")),
        "quantity_note": "explicit quantity" if row.get("explicit_quantity") else "default quantity 1",
        "suspected_size_as_quantity_scan_error": False,
    }


def fetch_owner_item_events(user_id: str | None = None, guest_session_id: str | None = None, limit: int = 1000) -> list[dict]:
    owner_type = "user" if user_id else "guest"
    owner_id = user_id or guest_session_id or "__none__"
    cache_key = (owner_type, owner_id, limit)
    if cache_key in _ITEM_EVENT_CACHE:
        return _ITEM_EVENT_CACHE[cache_key]

    try:
        q = supabase.table("receipt_items").select(ITEM_SELECT)
        if user_id:
            q = q.eq("user_id", user_id)
        elif guest_session_id:
            q = q.eq("is_guest", True).eq("guest_session_id", guest_session_id)
        else:
            return []
        result = q.order("receipt_created_at", desc=True).limit(limit).execute()
        events = []
        for row in (result.data or []):
            name = str(row.get("item_name_original") or "")
            if not is_valid_receipt_item_name(name):
                continue
            if name.upper().startswith("DISCOUNT") or "discount" in name.lower() or "coupon" in name.lower():
                continue
            events.append(_item_row_to_event(row))
    except Exception as e:
        print(f"[receipt_items] Falling back to receipt JSON: {e}")
        events = []

    # The receipt_items table is the fast path, but older scans may only have
    # item details inside the receipt JSON. Merge both sources so RAG does not
    # miss real purchases because a backfill/index step lagged behind.
    try:
        json_events = build_item_events(fetch_owner_receipts(user_id, guest_session_id, limit=300))
        seen = {
            (
                str(event.get("receipt_id") or ""),
                str(event.get("line_index") or ""),
                normalize_text(event.get("item_original") or ""),
                str(event.get("line_price") or ""),
            )
            for event in events
        }
        for event in json_events:
            key = (
                str(event.get("receipt_id") or ""),
                str(event.get("line_index") or ""),
                normalize_text(event.get("item_original") or ""),
                str(event.get("line_price") or ""),
            )
            if key not in seen:
                events.append(event)
                seen.add(key)
    except Exception as e:
        print(f"[receipt_items] Could not merge receipt JSON items: {e}")

    events = events[:limit]
    _ITEM_EVENT_CACHE[cache_key] = events
    if len(_ITEM_EVENT_CACHE) > 20:
        _ITEM_EVENT_CACHE.clear()
    return events


def build_item_events(receipts: list[dict]) -> list[dict]:
    """Flatten receipt JSON items into exact purchase events for grounded RAG."""
    events: list[dict] = []
    for receipt in receipts:
        receipt_items = []
        for item in receipt.get("items") or []:
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("source", "printed")
                receipt_items.append(item)
        for item in receipt.get("handwritten_items") or []:
            if isinstance(item, dict):
                item = dict(item)
                item.setdefault("source", "handwritten")
                receipt_items.append(item)

        for index, item in enumerate(receipt_items):
            name = item.get("name") or item.get("item") or ""
            if not is_valid_receipt_item_name(name):
                continue
            name_lower = str(name).lower()
            if str(name).upper().startswith("DISCOUNT") or "discount" in name_lower or "coupon" in name_lower:
                continue
            product_size = item.get("product_size") or find_product_size(name)
            raw_qty = _safe_float(item.get("quantity"), 1.0) or 1.0
            line_price = _safe_float(item.get("price"), 0.0)
            stored_unit_price = _safe_float(item.get("unit_price"), 0.0)
            unit = item.get("unit") or "each"
            explicit_qty = bool(item.get("explicit_quantity")) or bool(EXPLICIT_QTY_RE.search(str(name)))

            # Product-size safeguard: 2.00-GAL, 10.00-OZ, etc. are packaging, not purchase quantity.
            suspected_size_as_qty = False
            if product_size and not explicit_qty:
                # If qty equals the product size number or any qty >1 came from a scanner guess, use 1.
                size_match = PRODUCT_SIZE_RE.search(str(name))
                size_amount = _safe_float(size_match.group(1), 0.0) if size_match else 0.0
                if abs(raw_qty - size_amount) < 0.001 or raw_qty > 1:
                    suspected_size_as_qty = True
                purchase_qty = 1.0
            else:
                purchase_qty = raw_qty if raw_qty > 0 else 1.0

            paid_price = line_price
            if paid_price == 0 and stored_unit_price:
                paid_price = stored_unit_price * purchase_qty

            # For product-size items with no explicit quantity, the line price is the real item price.
            normalized_unit_price = paid_price / purchase_qty if purchase_qty and explicit_qty else paid_price

            events.append({
                "receipt_id": receipt.get("id"),
                "line_index": index,
                "store": receipt.get("store") or "Unknown Store",
                "address": receipt.get("address"),
                "date": receipt.get("date") or (receipt.get("created_at") or "")[:10],
                "time": receipt.get("time"),
                "created_at": receipt.get("created_at"),
                "code": item.get("code"),
                "item_original": name,
                "item_normalized": normalize_text(name),
                "product_size": product_size,
                "quantity": purchase_qty,
                "raw_quantity_from_scan": raw_qty,
                "unit": unit,
                "unit_price": round(normalized_unit_price, 2) if normalized_unit_price else None,
                "line_price": round(paid_price, 2) if paid_price else None,
                "source": item.get("source", "printed"),
                "confidence": item.get("confidence"),
                "metadata": item,
                "source_page": item.get("page") or item.get("source_page") or item.get("page_index"),
                "source_bbox": item.get("bbox") or item.get("bounding_box") or item.get("source_bbox"),
                "source_text": item.get("line_text") or item.get("source_text") or name,
                "source_image_hash": item.get("image_hash") or receipt.get("image_hash"),
                "explicit_quantity": explicit_qty,
                "quantity_note": "product size detected; treated as quantity 1" if product_size and not explicit_qty else "explicit quantity" if explicit_qty else "default quantity 1",
                "suspected_size_as_quantity_scan_error": suspected_size_as_qty,
            })
    return events


def retrieve_item_events(
    item_query: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    limit: int = 25,
    extra_families: list[set[str]] | None = None,
) -> dict:
    all_events = fetch_owner_item_events(user_id, guest_session_id)
    if not all_events:
        receipts = fetch_owner_receipts(user_id, guest_session_id)
        all_events = build_item_events(receipts)
    query = extract_query_item(item_query)
    query_variants = expand_query_variants(query, extra_families)
    semantic_family = query_semantic_family(query, extra_families)
    match_threshold = minimum_match_score(query, semantic_family)
    candidate_threshold = minimum_candidate_score(query, semantic_family)
    feedback_examples = fetch_owner_feedback_examples(user_id, guest_session_id)
    embedding_boosts = fetch_embedding_rank_boosts(query, user_id, guest_session_id)
    blocklist = fetch_owner_blocklist(user_id, guest_session_id)
    scored = []
    for event in all_events:
        if not event_matches_semantic_family(event, semantic_family, extra_families):
            continue
        if not event_satisfies_required_families(event, query, extra_families):
            continue
        # Hard blocklist check: user previously marked this (query, item) pair as wrong
        if is_blocklisted(query, event.get("item_original", ""), blocklist):
            continue
        scores = [(variant, item_match_score(variant, event["item_original"], event.get("code"))) for variant in query_variants]
        matched_query, score = max(scores, key=lambda item: item[1]) if scores else (query, 0.0)
        learned_adjustment = learned_rank_adjustment(query, event, feedback_examples)
        embedding_adjustment = embedding_boosts.get(receipt_event_key(event), 0.0)
        adjusted_score = max(0.0, min(1.0, score + learned_adjustment + embedding_adjustment))
        match_level = verified_match_level(event, query, score, extra_families)
        if match_level != "none" and adjusted_score >= match_threshold:
            event_copy = dict(event)
            event_copy["match_score"] = score
            event_copy["learned_rank_adjustment"] = round(learned_adjustment, 4)
            event_copy["embedding_rank_adjustment"] = round(embedding_adjustment, 4)
            event_copy["adjusted_match_score"] = round(adjusted_score, 4)
            event_copy["matched_query"] = matched_query
            event_copy["match_confidence"] = match_level
            scored.append(event_copy)

    scored.sort(
        key=lambda x: (
            x.get("adjusted_match_score", x["match_score"]),
            x.get("learned_rank_adjustment", 0.0) + x.get("embedding_rank_adjustment", 0.0),
            x["match_score"],
            x.get("date") or "",
            x.get("created_at") or "",
        ),
        reverse=True,
    )
    matches = scored[:limit]

    if not matches:
        # Return only meaningful candidates. Weak fuzzy matches are worse than no match.
        candidates = []
        for event in all_events:
            if not event_matches_semantic_family(event, semantic_family, extra_families):
                continue
            if not event_satisfies_required_families(event, query, extra_families):
                continue
            scores = [(variant, item_match_score(variant, event["item_original"], event.get("code"))) for variant in query_variants]
            matched_query, score = max(scores, key=lambda item: item[1]) if scores else (query, 0.0)
            learned_adjustment = learned_rank_adjustment(query, event, feedback_examples)
            embedding_adjustment = embedding_boosts.get(receipt_event_key(event), 0.0)
            adjusted_score = max(0.0, min(1.0, score + learned_adjustment + embedding_adjustment))
            match_level = verified_match_level(event, query, score, extra_families)
            if match_level != "none" and adjusted_score >= candidate_threshold:
                candidates.append({
                    "item": event["item_original"],
                    "store": event["store"],
                    "date": event["date"],
                    "price": event["line_price"],
                    "match_score": score,
                    "learned_rank_adjustment": round(learned_adjustment, 4),
                    "embedding_rank_adjustment": round(embedding_adjustment, 4),
                    "adjusted_match_score": round(adjusted_score, 4),
                    "matched_query": matched_query,
                    "match_confidence": match_level,
                })
        candidates.sort(
            key=lambda x: (
                x.get("adjusted_match_score", x["match_score"]),
                x.get("learned_rank_adjustment", 0.0) + x.get("embedding_rank_adjustment", 0.0),
                x["match_score"],
            ),
            reverse=True,
        )
        return {
            "query": item_query,
            "normalized_query": query,
            "query_variants": query_variants,
            "semantic_family": semantic_family,
            "match_threshold": match_threshold,
            "count": 0,
            "events": [],
            "closest_candidates": candidates[:8],
            "message": f"No strong receipt item matches found for '{item_query}'.",
        }

    prices = [e["line_price"] for e in matches if isinstance(e.get("line_price"), (int, float)) and e.get("line_price") is not None]
    return {
        "query": item_query,
        "normalized_query": query,
        "query_variants": query_variants,
        "semantic_family": semantic_family,
        "match_threshold": match_threshold,
        "count": len(matches),
        "events": matches,
        "lowest_price": min(prices) if prices else None,
        "highest_price": max(prices) if prices else None,
        "important_quantity_rule": "Each event is one receipt line. Product sizes like 2.00-GAL are packaging, not purchase quantity. Do not combine separate receipt events into quantity 2.",
    }


def looks_like_item_history_question(message: str) -> bool:
    m = correct_query_words(normalize_text(message))
    if looks_like_global_price_question(m):
        return False
    trigger_words = [
        "how many", "times", "bought", "buy", "purchase", "purchased", "price", "prices", "paid", "history",
        "best price", "best", "rate", "cheap", "cheapest", "cheaper", "low", "lowest", "highest", "where", "same product", "same item", "rose", "pink", "prem", "frame"
    ]
    return any(t in m for t in trigger_words)


def looks_like_price_or_item_question(message: str) -> bool:
    m = correct_query_words(normalize_text(message))
    tokens = set(m.split())
    price_terms = {
        "price", "prices", "cheap", "cheapest", "cheaper", "best", "lowest",
        "low", "highest", "cost", "rate", "paid", "buy", "bought", "purchase",
    }
    item_terms = {"item", "items", "product", "products", "store", "stores"} | KNOWN_ITEM_TERMS | BROAD_CATEGORY_QUERY_TERMS
    question_terms = {"what", "which", "where", "show", "tell", "find"}
    return bool(
        (tokens & price_terms and (tokens & item_terms or len(tokens - STOP_WORDS) >= 1))
        or (tokens & item_terms and (tokens & question_terms or len(tokens - STOP_WORDS) >= 1))
    )


def looks_like_smalltalk_or_help(message: str) -> bool:
    m = correct_query_words(normalize_text(message))
    tokens = set(m.split())
    if not tokens:
        return True
    if looks_like_price_or_item_question(message):
        return False
    help_terms = {"help", "examples", "example", "what", "can", "ask", "questions", "question", "do"}
    greetings = {"hi", "hello", "hey", "thanks", "thank", "ok", "okay"}
    return bool(tokens <= greetings or ("help" in tokens and len(tokens) <= 4) or (tokens & help_terms and len(tokens) <= 5))


def should_use_item_rag(message: str) -> bool:
    if looks_like_global_price_question(message) or looks_like_overview_question(message):
        return False
    extracted = extract_query_item(message)
    tokens = token_set(extracted)
    if not tokens:
        return False
    if looks_like_smalltalk_or_help(message):
        return False
    if looks_like_item_history_question(message):
        return True
    if tokens & KNOWN_ITEM_TERMS:
        return True
    # Strong default: any remaining meaningful text may be an imperfect product/store question.
    # Try structured receipt retrieval before allowing a general answer.
    return True


def looks_like_global_price_question(message: str) -> bool:
    m = correct_item_typos(correct_query_words(normalize_text(message)))
    tokens = set(m.split())
    global_terms = ["all item", "all items", "everything", "overall", "entire"]
    price_terms = ["least price", "lowest price", "cheapest", "minimum price", "min price"]
    cheap_terms = {"least", "lowest", "cheapest", "cheap", "low"}
    has_specific_item = bool(tokens & (KNOWN_ITEM_TERMS | BROAD_CATEGORY_QUERY_TERMS))
    rough_lowest_item_question = (
        bool(tokens & cheap_terms)
        and ("item" in tokens or "items" in tokens)
        and not has_specific_item
        and not any(term in m for term in ["bought the", "buy the", "purchase the"])
    )
    unknown_item_terms = tokens - STOP_WORDS - cheap_terms
    incomplete_lowest_question = bool(tokens & cheap_terms) and not has_specific_item and not unknown_item_terms
    return (
        any(term in m for term in global_terms) and any(term in m for term in price_terms)
    ) or rough_lowest_item_question or incomplete_lowest_question


def clean_item_query_for_display(query: str) -> str:
    text = correct_item_typos(normalize_text(query))
    words = [w for w in text.split() if w not in STOP_WORDS]
    display = " ".join(words) or text or "that item"
    display_replacements = {
        "garammasala": "garam masala",
        "blackpepper": "black pepper",
        "chilipowder": "chili powder",
        "coriandrpowder": "coriander powder",
        "turmericpowder": "turmeric powder",
    }
    for compact, spaced in display_replacements.items():
        display = re.sub(rf"\b{compact}\b", spaced, display)
    return display


QUERY_UNDERSTANDING_INTENTS = {
    "item_price",
    "item_count",
    "category_price",
    "global_cheapest",
    "spending_summary",
    "monthly_report",
    "shopping_plan",
    "store_compare",
    "general_advice",
    "help",
    "unknown",
}

GENERAL_ADVICE_TERMS = {
    "temperature", "heat", "heated", "cook", "cooking", "boil", "boiled",
    "bacteria", "safe", "safety", "storage", "store", "expire", "expired",
    "fresh", "freeze", "frozen", "thaw", "recipe", "prepare", "pasteurize",
    "pasteurized", "milk", "food", "eat", "drink", "healthy", "health",
    "nutrition", "nutritious", "basmati", "rice", "vegetable", "vegetables",
    "curry", "go", "goes", "meaning", "mean", "cheaper", "save",
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
        "text": "Freeze meat tightly wrapped at 0°F / -18°C. Ground meat is best used within 3-4 months for quality; larger cuts often keep quality for 6-12 months.",
    },
    {
        "id": "milk_pasteurization",
        "title": "Milk pasteurization temperature",
        "keywords": {"milk", "temperature", "heat", "heated", "bacteria", "pasteurize", "pasteurized", "safe", "safety"},
        "text": "Common milk pasteurization references are 161°F / 72°C for 15 seconds or 145°F / 63°C for 30 minutes, followed by quick cooling and refrigeration. Pasteurization does not make spoiled milk safe.",
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


def query_understanding_enabled() -> bool:
    value = os.getenv("AGENT_QUERY_UNDERSTANDING_ENABLED", "true").strip().lower()
    return value not in {"0", "false", "no", "off"} and claude_client is not None


def parse_json_object(text: str) -> dict:
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.IGNORECASE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def recent_user_context(conversation_history: list[dict] | None) -> str:
    rows = []
    for row in (conversation_history or [])[-6:]:
        role = row.get("role")
        content = str(row.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            rows.append(f"{role}: {content[:220]}")
    return "\n".join(rows)


def local_understand_user_query(message: str, conversation_history: list[dict] | None = None) -> dict:
    """
    Fast deterministic intent router for the most common mobile chat patterns.
    It prevents obvious general/help/category questions from being forced into item RAG.
    """
    raw_message = message or ""
    normalized = correct_item_typos(correct_query_words(normalize_text(raw_message)))
    tokens = set(normalized.split())
    meaningful = token_set(raw_message)

    if looks_like_global_price_question(raw_message):
        return {
            "intent": "global_cheapest",
            "canonical_message": "cheapest item",
            "item_query": "",
            "category": "",
            "is_receipt_question": True,
        }

    action = classify_receipt_action(raw_message)
    if action:
        return {
            "intent": "spending_summary",
            "canonical_message": raw_message,
            "item_query": "",
            "category": "",
            "is_receipt_question": True,
        }

    category_terms = meaningful & BROAD_CATEGORY_QUERY_TERMS
    question_or_price_terms = {
        "where", "show", "tell", "find", "cheap", "cheapest",
        "lowest", "best", "price", "prices", "cost", "rate",
        "bought", "buy", "purchase", "purchased",
    }
    advice_scope_terms = {
        "healthy", "health", "nutrition", "nutritious", "safe", "safety",
        "cook", "cooking", "boil", "store", "storage", "fresh", "recipe",
        "with", "go", "goes",
    }
    raw_meat_category = bool(
        (meaningful & BROAD_MEAT_QUERY_TERMS)
        and (
            (tokens & {"type", "types"})
            or ((tokens & {"what", "which", "show", "tell", "find"}) and (tokens & {"bought", "buy", "purchase", "purchased"}))
        )
        and not (tokens & advice_scope_terms)
    )
    if (category_terms or raw_meat_category) and (tokens & question_or_price_terms or raw_meat_category or (len(meaningful) <= 3 and not tokens & advice_scope_terms)):
        category = "meat" if raw_meat_category else sorted(category_terms)[0]
        return {
            "intent": "category_price",
            "canonical_message": f"cheap {category}",
            "item_query": "",
            "category": category,
            "is_receipt_question": True,
        }

    if looks_like_general_advice_question(raw_message):
        return {
            "intent": "general_advice",
            "canonical_message": raw_message,
            "item_query": "",
            "category": "",
            "is_receipt_question": False,
        }

    if looks_like_overview_question(raw_message):
        if any(term in normalized for term in [
            "shopping plan", "buy this month", "need soon", "next trip",
            "items to purchase", "purchase this month", "this month items",
            "want", "want i should", "next coming month", "coming month",
            "shopping",
        ]):
            intent = "shopping_plan"
            canonical = "shopping plan"
        elif looks_like_category_spending_question(raw_message):
            intent = "spending_summary"
            canonical = "category-wise spending"
        elif looks_like_weekly_question(raw_message):
            intent = "spending_summary"
            canonical = "weekly spending report"
        elif any(term in normalized for term in ["spend the most", "spent the most", "spend most", "spent most", "store did i spend", "where did i spend", "which store did i spend"]):
            intent = "spending_summary"
            canonical = "which store did i spend the most at"
        elif any(term in normalized for term in ["monthly", "month", "report"]):
            intent = "monthly_report"
            canonical = "this month expense chart" if "this month" in normalized else "monthly spending report"
        elif any(term in normalized for term in [
            "price trend", "price trends", "buy regularly", "regularly",
            "mostly purchased", "mostly purchase", "most purchased",
            "frequently purchasing", "frequently purchased", "frequent purchases",
            "frequent items", "repeat items", "repeat purchases",
        ]):
            intent = "spending_summary"
            canonical = "price trends"
        elif any(term in normalized for term in ["top 3 ways", "save money", "saving", "best deals", "best deal", "deals recently"]):
            intent = "spending_summary"
            canonical = "save money"
        elif any(term in normalized for term in ["price memory", "price dna", "avoid above", "avoid price", "good price"]):
            intent = "spending_summary"
            canonical = "price memory"
        elif any(term in normalized for term in ["market price", "market prices", "current market", "overpaid", "over pay", "overpay"]):
            intent = "spending_summary"
            canonical = "market price comparison"
        else:
            intent = "spending_summary"
            canonical = "spending summary"
        return {"intent": intent, "canonical_message": canonical, "item_query": "", "category": "", "is_receipt_question": True}

    if looks_like_smalltalk_or_help(raw_message):
        return {
            "intent": "help",
            "canonical_message": raw_message,
            "item_query": "",
            "category": "",
            "is_receipt_question": False,
        }

    if not meaningful:
        return {"intent": "help", "canonical_message": raw_message, "item_query": "", "category": "", "is_receipt_question": False}

    if category_terms and (tokens & question_or_price_terms or len(meaningful) <= 3):
        category = sorted(category_terms)[0]
        return {
            "intent": "category_price",
            "canonical_message": f"cheap {category}",
            "item_query": "",
            "category": category,
            "is_receipt_question": True,
        }

    if looks_like_item_history_question(raw_message) or looks_like_price_or_item_question(raw_message):
        item = extract_query_item(raw_message)
        item_tokens = token_set(item)
        if item_tokens:
            intent = "item_count" if query_asks_for_count(raw_message) else "item_price"
            canonical = f"how many times bought {item}" if intent == "item_count" else f"best price for {item}"
            return {
                "intent": intent,
                "canonical_message": canonical,
                "item_query": item,
                "category": "",
                "is_receipt_question": True,
            }

    return {}


def query_understanding_prompt(message: str, conversation_history: list[dict] | None = None) -> str:
    return f"""You are only a query-understanding layer for a receipt shopping app.
Return strict JSON only.

Goal:
- Understand messy grammar, typos, short phrases, and multilingual item names.
- Convert the user into a clean receipt-search intent.
- Do not answer the user. Do not invent prices, stores, or purchases.
- If the user asks for a specific item, extract only that item.
- If the user lists MULTIPLE items (space-separated, comma-separated, or newline-separated), put each item
  in the "items" array. Never combine two separate items into one string.
  Example: "cinnamon stick saffron turmeric cardamom" → items: ["cinnamon stick", "saffron", "turmeric", "cardamom"]
  Example: "coconut oil, rice, dal" → items: ["coconut oil", "rice", "dal"]
  Compound items that belong together stay together: "coconut oil" stays as one item, "cinnamon stick" stays as one item.
- If the user asks a broad category like meat, vegetables, groceries, snacks, drinks, dairy, return category_price.
- If the user says only "cheapest item" or "what is cheap" with no item/category, return global_cheapest.
- If the user asks general shopping, cooking, food safety, storage, or product-meaning advice, return general_advice and is_receipt_question false.
- Use recent context only for true follow-ups like "where cheapest", "what about that", or "same item".
- Do not reuse old context when the user names a new item.

Allowed intents:
item_price, item_count, category_price, global_cheapest, spending_summary, monthly_report, shopping_plan, store_compare, general_advice, help, unknown

JSON schema (single item):
{{
  "intent": "item_price",
  "canonical_message": "best price for cilantro",
  "item_query": "cilantro",
  "items": ["cilantro"],
  "category": "",
  "is_receipt_question": true
}}

JSON schema (multiple items):
{{
  "intent": "item_price",
  "canonical_message": "best price for cinnamon stick, saffron, turmeric, cardamom",
  "item_query": "cinnamon stick",
  "items": ["cinnamon stick", "saffron", "turmeric", "cardamom"],
  "category": "",
  "is_receipt_question": true
}}

Recent context:
{recent_user_context(conversation_history)}

User message:
{message}
"""


def normalize_understanding_payload(data: dict) -> dict:
    intent = str(data.get("intent") or "").strip().lower()
    if intent not in QUERY_UNDERSTANDING_INTENTS:
        intent = "unknown"
    item_query = clean_item_query_for_display(str(data.get("item_query") or ""))
    category = clean_item_query_for_display(str(data.get("category") or ""))
    canonical = str(data.get("canonical_message") or "").strip()

    # Normalize the items array returned by the LLM intent classifier.
    raw_items = data.get("items")
    if isinstance(raw_items, list):
        items = [clean_item_query_for_display(str(i)) for i in raw_items if i]
        items = [i for i in items if i and i != "that item"]
    else:
        items = []

    # Fall back: if classifier returned no items array but gave a single item_query, seed items from it.
    if not items and item_query and item_query != "that item":
        items = [item_query]

    return {
        "intent": intent,
        "canonical_message": canonical,
        "item_query": "" if item_query == "that item" else item_query,
        "items": items,
        "category": "" if category == "that item" else category,
        "is_receipt_question": bool(data.get("is_receipt_question", intent != "help")),
    }


def understand_user_query(message: str, conversation_history: list[dict] | None = None) -> dict:
    """
    Normalize messy user wording into a receipt-search intent.
    This layer may understand typos/language/context, but never answers prices.
    """
    local = local_understand_user_query(message, conversation_history)
    if local:
        return local

    if not query_understanding_enabled():
        return {}

    prompt = query_understanding_prompt(message, conversation_history)
    if claude_client is None:
        return {}

    try:
        response = claude_client.messages.create(
            model=SONNET_MODEL,
            max_tokens=260,
            temperature=0,
            messages=[{
                "role": "user",
                "content": prompt,
            }],
        )
        text = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        data = parse_json_object(text)
    except Exception as e:
        print(f"[query_understanding] unavailable: {e}")
        return {}

    return normalize_understanding_payload(data)


def canonicalize_message_with_understanding(message: str, understanding: dict | None) -> str:
    data = understanding or {}
    intent = str(data.get("intent") or "").lower()
    item = clean_item_query_for_display(str(data.get("item_query") or ""))
    category = clean_item_query_for_display(str(data.get("category") or ""))
    canonical = str(data.get("canonical_message") or "").strip()

    if intent in {"item_price", "item_count"} and item and item != "that item":
        if intent == "item_count":
            return f"how many times bought {item}"
        return f"best price for {item}"
    if intent == "category_price" and category and category != "that item":
        return f"cheap {category}"
    if intent == "global_cheapest":
        return "cheapest item"
    if intent == "spending_summary":
        return canonical or "spending summary"
    if intent == "monthly_report":
        return canonical or "monthly report"
    if intent == "shopping_plan":
        return canonical or "shopping plan"
    if intent == "store_compare":
        return canonical or "compare stores"
    return canonical or message


def broad_category_from_message(message: str, understanding: dict | None = None) -> str:
    data = understanding or {}
    category = clean_item_query_for_display(str(data.get("category") or ""))
    normalized = correct_query_words(correct_item_typos(normalize_text(message)))
    tokens = set(normalized.split())
    broad_terms = BROAD_CATEGORY_QUERY_TERMS | BROAD_MEAT_QUERY_TERMS | {"meat"}
    scope_terms = {
        "what", "which", "where", "cheap", "cheapest", "cheaper", "best", "price", "prices",
        "bought", "buy", "purchase", "purchased", "is", "the", "was", "were", "found",
        "type", "types", "kind", "kinds", "category", "categories", "of", "i",
        "now", "please", "pls",
        "did", "do", "have", "has",
    }
    specific_tokens = tokens - broad_terms - scope_terms - STOP_WORDS
    if specific_tokens:
        return ""
    if str(data.get("intent") or "").lower() == "category_price" and category and category != "that item":
        return normalize_text(category)

    if "meat" in tokens:
        return "meat"
    if (
        tokens & BROAD_MEAT_QUERY_TERMS
        and tokens <= (BROAD_MEAT_QUERY_TERMS | scope_terms)
        and ((tokens & {"type", "types"}) or ((tokens & {"what", "which", "show", "tell", "find"}) and (tokens & {"bought", "buy", "purchase", "purchased"})))
    ):
        return "meat"
    for term in BROAD_CATEGORY_QUERY_TERMS - {"meat"}:
        if term in tokens:
            return term
    return ""


def category_with_include_from_message(message: str) -> str:
    normalized = correct_query_words(correct_item_typos(normalize_text(message)))
    tokens = set(normalized.split())
    if not (tokens & {"include", "including", "with", "also"}):
        return ""
    if not (tokens & {"price", "prices", "cheap", "cheapest", "show", "list"}):
        return ""
    if tokens & {"vegetable", "vegetables", "veggie", "veggies", "produce"}:
        return "vegetable"
    if tokens & {"meat", "mutton", "beef", "chicken", "goat", "lamb"} and "include" in tokens:
        return "meat"
    for term in BROAD_CATEGORY_QUERY_TERMS - {"meat", "vegetable", "vegetables", "veggie", "veggies", "produce"}:
        if term in tokens:
            return term
    return ""


def looks_like_general_advice_question(message: str) -> bool:
    return agent_general.looks_like_general_advice_question(
        message,
        normalize_text=normalize_text,
        correct_item_typos=correct_item_typos,
        correct_query_words=correct_query_words,
        broad_category_terms=BROAD_CATEGORY_QUERY_TERMS,
    )


def retrieve_general_context(message: str, limit: int = 3) -> list[dict]:
    return agent_general.retrieve_general_context(
        message,
        token_set=token_set,
        correct_query_words=correct_query_words,
        normalize_text=normalize_text,
        limit=limit,
    )


def general_context_text(context: list[dict]) -> str:
    return agent_general.general_context_text(context)


def general_advice_answer(message: str, context: list[dict] | None = None) -> str:
    return agent_general.general_advice_answer(
        message,
        context,
        retrieve_context=retrieve_general_context,
        claude_client=claude_client,
        claude_model=SONNET_MODEL,
        correct_query_words=correct_query_words,
        normalize_text=normalize_text,
    )


def find_recent_item_topic(conversation_history: list[dict] | None) -> str | None:
    """Find the last concrete item/category the user asked about for follow-up questions."""
    for row in reversed(conversation_history or []):
        if row.get("role") != "user":
            continue
        content = str(row.get("content") or "")
        if (
            looks_like_general_advice_question(content)
            or looks_like_global_price_question(content)
            or classify_receipt_action(content)
        ):
            continue
        item = extract_query_item(content)
        tokens = token_set(item)
        if tokens and not looks_like_global_price_question(item) and not looks_like_smalltalk_or_help(item):
            return item
    return None


def find_recent_receipt_topic(conversation_history: list[dict] | None) -> str | None:
    """Prefer the latest concrete receipt topic, including assistant-confirmed topics."""
    for row in reversed(conversation_history or []):
        content = str(row.get("content") or "")
        if not content:
            continue
        found = re.search(r"\b(?:i found|you bought)\s+\d+\s+(.+?)\s+purchases?\b", content, re.IGNORECASE)
        if found:
            topic = extract_query_item(found.group(1))
            if token_set(topic):
                return topic
        found = re.search(r"\byou bought\s+(.+?)\s+\d+\s+times?\b", content, re.IGNORECASE)
        if found:
            topic = extract_query_item(found.group(1))
            if token_set(topic):
                return topic
        found = re.search(r"^\s*[-*]?\s*([A-Za-z][A-Za-z0-9 &*'-]{2,40})\s*$", content)
        if found and row.get("role") == "assistant":
            topic = extract_query_item(found.group(1))
            if token_set(topic) and not looks_like_smalltalk_or_help(topic):
                return topic
        if row.get("role") == "user":
            topic = find_recent_item_topic([row])
            if topic:
                return topic
    return None


def resolve_followup_message(message: str, conversation_history: list[dict] | None) -> str:
    """
    Make short follow-ups interactive without guessing wildly.
    Example: user asks "mutton", then "where cheapest" -> "where cheapest mutton".
    """
    m = correct_query_words(normalize_text(message))
    tokens = set(m.split())
    if (looks_like_global_price_question(message) and "where" not in tokens) or looks_like_general_advice_question(message):
        return message
    meaningful = tokens - STOP_WORDS
    followup_terms = {"where", "cheap", "cheapest", "cheaper", "best", "lowest", "price", "cost", "it", "that", "this", "them", "those", "show", "list", "history", "all", "evidence", "receipt", "receipts", "open"}
    pronoun_terms = {"it", "that", "this", "them", "those"}
    # "same item / same thing / same product" — treat as pronoun reference to last topic
    same_item_phrases = ["same item", "same thing", "same product", "same one", "that item", "that thing"]
    is_same_item_ref = any(phrase in m for phrase in same_item_phrases)
    # Bare "which store" / "what store" with no item = followup on last topic
    is_bare_store_q = bool(tokens & {"store", "stores"}) and not bool(meaningful - {"where", "which", "what", "store", "stores", "was", "cheapest", "cheap", "best", "lowest"})
    item_text = extract_query_item(message)
    item_tokens = token_set(item_text)
    has_new_item_text = bool(item_tokens)
    is_pronoun_followup = bool(tokens & pronoun_terms) and not (item_tokens - pronoun_terms)
    is_bare_price_followup = bool(tokens & followup_terms) and not has_new_item_text
    is_list_followup = bool(tokens & {"show", "list", "history", "all", "evidence", "receipt", "receipts", "them", "those", "open"}) and len(meaningful - {"show", "list", "history", "all", "evidence", "receipt", "receipts", "them", "those", "open"}) == 0
    if is_pronoun_followup or is_bare_price_followup or is_same_item_ref or is_bare_store_q:
        topic = find_recent_receipt_topic(conversation_history)
        if topic:
            resolved = f"{message} {topic}" if not is_same_item_ref else f"how many times bought {topic}"
            return resolved
    if is_list_followup:
        topic = find_recent_receipt_topic(conversation_history)
        if topic:
            return f"{message} {topic}"
    return message


def has_regional_meat_alias(query: str, events: list[dict]) -> bool:
    q_tokens = token_set(query)
    if "mutton" not in q_tokens:
        return False
    for event in events:
        item_tokens = token_set(event.get("item_original") or "")
        if {"goat", "lamb", "sheep", "chevon"} & item_tokens:
            return True
    return False


def query_asks_for_best_price(message: str) -> bool:
    m = correct_query_words(normalize_text(message))
    tokens = set(m.split())
    return bool(tokens & {"where", "cheap", "cheapest", "cheaper", "best", "lowest", "least", "low"})


def query_asks_for_count(message: str) -> bool:
    m = correct_query_words(normalize_text(message))
    return any(term in m for term in ["how many", "times", "count", "often"])


def query_asks_for_history(message: str) -> bool:
    m = correct_query_words(normalize_text(message))
    tokens = set(m.split())
    if tokens <= {"list", "them", "those", "show", "all", "history"}:
        return True
    if (tokens & {"show", "list", "give"}) and (tokens & {"them", "those", "these"}):
        return True
    return any(
        term in m
        for term in [
            "history", "all purchases", "all bought", "every purchase", "each purchase",
            "compare", "comparison", "trend", "trends", "list all", "show all",
            "previous prices", "price changes", "highest", "lowest and highest",
            "show the list", "show list", "list purchases", "purchase list",
            " list", "list ", "receipt with", "receipts with", "find receipt", "all receipts", "show me", "evidence",
        ]
    )


def semantic_alias_note(query: str, events: list[dict]) -> str | None:
    q_tokens = token_set(query)
    if not q_tokens:
        return None
    event_tokens = set()
    for event in events:
        event_tokens |= token_set(event.get("item_original") or "")
    if "mutton" in q_tokens and {"goat", "lamb", "sheep", "chevon"} & event_tokens:
        return None
    if "cilantro" in q_tokens and "coriander" in event_tokens:
        return None
    if "coriander" in q_tokens and "cilantro" in event_tokens:
        return None
    for group in ITEM_SYNONYM_GROUPS:
        if q_tokens & group and event_tokens & group and not (q_tokens & event_tokens):
            return None
    return None


def best_price_event(events: list[dict]) -> dict | None:
    priced = [e for e in events if price_memory_event_price(e) > 0]
    if not priced:
        return None
    return min(priced, key=price_memory_event_price)


def event_price_text(event: dict, price: float | None = None) -> str:
    value = _safe_float(price, None)
    if value is None:
        value = price_memory_event_price(event)
    if not value:
        return "price not shown"
    unit = normalize_text(event.get("unit") or "each")
    unit_text = f"/{unit}" if unit and unit != "each" else ""
    return f"{money(value)}{unit_text}"


def item_line_detail(event: dict) -> str:
    quantity = _safe_float(event.get("quantity"), 1.0) or 1.0
    unit = normalize_text(event.get("unit") or "each")
    line_price = _safe_float(event.get("line_price"), 0.0)
    if unit and unit != "each":
        return f"{quantity:g} {unit}, total {money(line_price)}"
    if quantity != 1:
        return f"qty {quantity:g}, total {money(line_price)}"
    return f"receipt total {money(line_price)}"


def multimodal_source_evidence(event: dict) -> dict:
    bbox = event.get("source_bbox")
    return {
        "source": "receipt_image_or_pdf",
        "available": bool(event.get("source_page") is not None or bbox or event.get("source_text") or event.get("source_image_hash")),
        "page": event.get("source_page"),
        "bbox": bbox,
        "line_text": event.get("source_text") or event.get("item_original"),
        "image_hash": event.get("source_image_hash"),
        "can_highlight_line": bool(bbox),
    }


def event_answer_card(event: dict, title: str, kind: str = "best_price", note: str | None = None) -> dict:
    quantity = _safe_float(event.get("quantity"), 1.0) or 1.0
    unit = normalize_text(event.get("unit") or "each")
    return {
        "type": kind,
        "title": title,
        "item": event.get("item_original"),
        "price": event_price_text(event),
        "store": event.get("store") or "Unknown store",
        "date": event.get("date") or "unknown date",
        "quantity": quantity,
        "unit": unit or "each",
        "line_total": money(event.get("line_price")),
        "receipt_id": event.get("receipt_id"),
        "line_index": event.get("line_index"),
        "detail": item_line_detail(event),
        "evidence": {
            "receipt_id": event.get("receipt_id"),
            "line_index": event.get("line_index"),
            "source": "receipt_item_event",
            "openable": bool(event.get("receipt_id")),
            "match_confidence": event.get("match_confidence") or event.get("confidence"),
            "compare_price": price_memory_event_price(event),
            "multimodal": multimodal_source_evidence(event),
        },
        "multimodal_evidence": multimodal_source_evidence(event),
        "note": note,
    }


def dedupe_item_events(events: list[dict]) -> list[dict]:
    unique: list[dict] = []
    seen: set[tuple] = set()
    for event in events:
        key = (
            event.get("receipt_id"),
            event.get("line_index"),
            normalize_text(event.get("item_original") or ""),
            event.get("store") or "",
            event.get("date") or "",
            round(price_memory_event_price(event), 2),
            round(_safe_float(event.get("line_price"), 0.0), 2),
            round(_safe_float(event.get("quantity"), 1.0), 3),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def looks_like_prepared_dish(event: dict) -> bool:
    text = normalize_text(event.get("item_original") or "")
    if not text:
        return False
    return any(phrase in text for phrase in PREPARED_DISH_PHRASES)


def looks_like_non_raw_grocery_event(event: dict) -> bool:
    text = normalize_text(event.get("item_original") or "")
    if not text:
        return False
    non_raw_terms = {
        "gummies", "trolli", "medley", "candy", "chocolate",
        "tablet", "tablets", "capsule", "capsules", "supplement", "supplements",
        "vitamin", "vitamins", "pill", "pills",
        "noodle", "noodles", "ramen", "fried rice", "schezwan",
        "biryani", "dosa", "naan", "samosa", "burger", "pizza",
        "sandwich", "combo", "meal", "plate",
    }
    return any(term in text for term in non_raw_terms)


def looks_like_raw_meat_event(event: dict) -> bool:
    text = normalize_text(event.get("item_original") or "")
    tokens = token_set(text)
    if not tokens or looks_like_prepared_dish(event):
        return False
    if tokens & RAW_MEAT_TERMS & {"fish", "seafood", "mackerel", "sardine", "anchovy", "shrimp", "prawn"}:
        return True
    if tokens & RAW_MEAT_TERMS & {"goat", "mutton", "lamb", "sheep", "chevon", "beef", "pork", "turkey"}:
        return True
    if "chicken" in tokens and (tokens & RAW_MEAT_CUT_TERMS or normalize_text(event.get("unit") or "") in {"lb", "lbs", "pound", "pounds"}):
        return True
    if tokens & {"keema", "kheema", "qeema"} and not looks_like_prepared_dish(event):
        return True
    return False


def trusted_item_events_for_answer(query: str, events: list[dict]) -> list[dict]:
    """Final answer guard: never claim prices from rows that lost the user's item meaning."""
    anchors = required_anchor_tokens(query)
    required = required_query_families(query)
    if not anchors and not required:
        return events

    trusted = []
    for event in events:
        if anchors & (RAW_PRODUCE_TERMS | RAW_STAPLE_TERMS) and looks_like_non_raw_grocery_event(event):
            continue
        if not event_satisfies_required_families(event, query):
            continue
        if AGENT_STRICT_MATCHING and is_specific_item_query(query):
            confidence = event.get("match_confidence") or verified_match_level(event, query, event.get("match_score"))
            if confidence == "none":
                continue
            score = event.get("match_score")
            if confidence == "medium" and isinstance(score, (int, float)) and score < STRICT_ITEM_MIN_SCORE:
                continue
        trusted.append(event)
    return trusted


def _legacy_deterministic_item_answer(message: str, rag: dict) -> str:
    events = rag.get("events") or []
    if not events:
        candidates = rag.get("closest_candidates") or []
        if candidates:
            lines = [f"I could not find a strong match for **{rag.get('query')}**. Closest receipt text I found:"]
            for c in candidates[:5]:
                lines.append(f"- {c['item']} — {c['store']} on {c.get('date') or 'unknown date'} — ${c.get('price')}")
            lines.append("Try asking with one of those item names if the receipt text looks different than expected.")
            return "\n".join(lines)
        return f"I could not find any matching purchases for **{rag.get('query')}** in your receipts."

    # Group by normalized item name, but keep each receipt line separate.
    item_label = events[0].get("item_original", rag.get("query"))
    count = len(events)
    prices = [e["line_price"] for e in events if e.get("line_price") is not None]
    lowest = min(prices) if prices else None
    highest = max(prices) if prices else None

    lines = [f"I found **{count} separate purchase event{'s' if count != 1 else ''}** matching **{rag.get('query')}**.", ""]
    lines.append("| # | Item scanned | Store | Date | Qty | Price | Note |")
    lines.append("|---|---|---|---|---:|---:|---|")
    for i, e in enumerate(events, 1):
        price = f"${e['line_price']:.2f}" if isinstance(e.get("line_price"), (int, float)) else "N/A"
        qty = int(e["quantity"]) if e.get("quantity") == int(e.get("quantity", 1)) else e.get("quantity")
        note = e.get("quantity_note") or "receipt line"
        lines.append(f"| {i} | {e['item_original']} | {e['store']} | {e.get('date') or ''} | {qty} | {price} | {note} |")

    if lowest is not None and highest is not None:
        lines.append("")
        if lowest == highest:
            lines.append(f"Both matching purchases have the same price: **${lowest:.2f}**.")
        else:
            diff = highest - lowest
            lines.append(f"Lowest price: **${lowest:.2f}**. Highest price: **${highest:.2f}**. Difference: **${diff:.2f}**.")

    if any(e.get("product_size") for e in events):
        sizes = sorted({e.get("product_size") for e in events if e.get("product_size")})
        lines.append("")
        lines.append(f"Important: **{', '.join(sizes)}** is the product size/packaging, not the quantity bought. I treated each matching receipt line as quantity **1** unless the receipt explicitly showed quantity 2, `2 @`, or `QTY 2`.")

    return "\n".join(lines)


def deterministic_item_answer(message: str, rag: dict) -> str:
    display_query = clean_item_query_for_display(rag.get("normalized_query") or rag.get("query") or message)
    events = dedupe_item_events(trusted_item_events_for_answer(display_query, rag.get("events") or []))
    if not events:
        base_msg = f"No clear {display_query} purchase found in your receipts."
        candidates = [
            c for c in (rag.get("closest_candidates") or [])
            if event_satisfies_required_families({"item_original": c.get("item") or ""}, display_query)
        ]
        if candidates:
            lines = [f"No exact {display_query} found. Closest receipt matches:"]
            for c in candidates[:3]:
                price_val = c.get("price")
                price = f"${price_val:.2f}" if isinstance(price_val, (int, float)) else ""
                store = c.get("store") or ""
                date  = c.get("date") or ""
                meta  = "  |  ".join(x for x in [store, date, price] if x)
                lines.append(f"  {c['item']}  —  {meta}" if meta else f"  {c['item']}")
            return "\n".join(lines)
        return base_msg

    count = len(events)
    prices = [price_memory_event_price(e) for e in events if price_memory_event_price(e) > 0]
    lowest = min(prices) if prices else None
    highest = max(prices) if prices else None
    best_event = best_price_event(events)
    alias_note = semantic_alias_note(rag.get("normalized_query") or rag.get("query") or message, events)
    asks_history = query_asks_for_history(message)
    asks_best = query_asks_for_best_price(message)

    if asks_best and best_event:
        item = best_event.get("item_original") or display_query
        store = best_event.get("store") or "Unknown store"
        date = best_event.get("date") or "unknown date"
        qty = _safe_float(best_event.get("quantity"), 1.0) or 1.0
        lines = [f"Best price found: {item} at {store} for {event_price_text(best_event)}."]
        lines.append(f"Bought on {date}; quantity {qty:g}.")
        if count > 1 and prices:
            hi = max(prices)
            lo = min(prices)
            if hi != lo:
                lines.append(f"Price range across {count} purchases: {event_price_text(best_event, lo)} — {event_price_text(best_event, hi)}.")
        if alias_note:
            lines.append(alias_note)
    elif query_asks_for_count(message):
        lines = [f"You bought {display_query} {count} time{'s' if count != 1 else ''}."]
        if alias_note:
            lines.append(alias_note)
    else:
        lines = [f"I found {count} {display_query} purchase{'s' if count != 1 else ''}."]
        if alias_note:
            lines.append(alias_note)

    if asks_history:
        lines.append("")
        lines.append("Price history:")

    for i, e in enumerate(events[:6], 1):
        date = e.get("date") or "unknown date"
        store = e.get("store") or "Unknown store"
        item = e.get("item_original") or rag.get("query")
        qty = _safe_float(e.get("quantity"), 1.0) or 1.0
        if count > 1 and not asks_history:
            if i > 4:
                break
            lines.append(f"{i}. {item} - {event_price_text(e)} at {store} ({date})")
        elif count > 1:
            lines.append(f"{i}. {item} - {event_price_text(e)} at {store} ({date}, qty {qty:g})")
        elif not query_asks_for_best_price(message):
            lines.append(f"{item} - {event_price_text(e)} at {store} ({date}, qty {qty:g})")

    comparison_prices = [price_memory_event_price(e) for e in events if price_memory_event_price(e) > 0]
    if comparison_prices:
        lowest_cmp = min(comparison_prices)
        highest_cmp = max(comparison_prices)
        if lowest_cmp == highest_cmp and count > 1 and asks_history:
            lines.append(f"Price seen: {event_price_text(events[0], lowest_cmp)}.")
        elif lowest_cmp != highest_cmp and asks_history:
            diff = highest_cmp - lowest_cmp
            if not asks_best:
                best_store = (best_event or {}).get("store") or "Unknown store"
                lines.append("")
                lines.append(f"Best price: {event_price_text(best_event or {}, lowest_cmp)} at {best_store}.")
            lines.append(f"Highest seen: {event_price_text(best_event or {}, highest_cmp)}. Difference: {money(diff)}.")

    if any(e.get("product_size") for e in events) and count > 1:
        lines.append("Note: product size is packaging, not quantity.")

    return "\n".join(lines)


def deterministic_item_answer_card(message: str, rag: dict) -> dict | None:
    display_query = clean_item_query_for_display(rag.get("normalized_query") or rag.get("query") or message)
    events = dedupe_item_events(trusted_item_events_for_answer(display_query, rag.get("events") or []))
    if not events or not query_asks_for_best_price(message):
        return None
    best_event = best_price_event(events)
    if not best_event:
        return None
    title = f"Best {display_query} price"
    return event_answer_card(best_event, title, "best_price")


def shopping_list_price_answer(
    message: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    extra_families: list[set[str]] | None = None,
) -> tuple[str, dict]:
    items = extract_shopping_list_items(message)
    rows = []
    missing = []
    row_keys: set[tuple] = set()

    def row_key_for_found(event: dict) -> tuple:
        if event.get("receipt_id") is not None or event.get("line_index") is not None:
            return ("receipt_line", event.get("receipt_id"), event.get("line_index"))
        return ("item", normalize_text(event.get("item_original") or ""), event_price_text(event), event.get("store") or "")

    def row_key_for_missing(display_item: str) -> tuple:
        return ("missing", normalize_text(display_item))

    def add_row_for_item(item: str, allow_self_heal: bool = True) -> None:
        rag = retrieve_item_events(f"best price for {item}", user_id, guest_session_id, limit=12, extra_families=extra_families)
        if not (rag.get("events") or rag.get("closest_candidates")):
            public_families = public_meaning_alias_families(item)
            if public_families:
                rag = retrieve_item_events(
                    f"best price for {item}",
                    user_id,
                    guest_session_id,
                    limit=12,
                    extra_families=(extra_families or []) + public_families,
                )

        display_item = clean_item_query_for_display(item)
        events = dedupe_item_events(trusted_item_events_for_answer(display_item, rag.get("events") or []))
        best = best_price_event(events)
        if not best:
            if allow_self_heal:
                split_items = split_failed_shopping_item(display_item)
                if split_items:
                    for split_item in split_items:
                        add_row_for_item(split_item, allow_self_heal=False)
                    return
            key = row_key_for_missing(display_item)
            if key in row_keys:
                return
            row_keys.add(key)
            missing.append(display_item)
            rows.append({
                "requested_item": display_item,
                "item": display_item,
                "match": "Not found",
                "price": "Not found",
                "store": "",
                "date": "",
                "receipt_id": None,
                "line_index": None,
                "detail": "No clear matching receipt purchase",
            })
            return

        key = row_key_for_found(best)
        if key in row_keys:
            return
        row_keys.add(key)
        rows.append({
            "requested_item": display_item,
            "item": best.get("item_original") or display_item,
            "match": best.get("item_original") or display_item,
            "price": event_price_text(best),
            "store": best.get("store") or "Unknown store",
            "date": best.get("date") or "unknown date",
            "receipt_id": best.get("receipt_id"),
            "line_index": best.get("line_index"),
            "detail": item_line_detail(best),
            "multimodal_evidence": multimodal_source_evidence(best),
        })

    for item in items:
        add_row_for_item(item)

    lines = ["Best receipt prices"]
    lines.append("| Requested item | Best match | Store | Price | Date |")
    lines.append("|---|---|---|---:|---|")
    for row in rows:
        lines.append(
            f"| {row['requested_item']} | {row['match']} | {row.get('store') or '-'} | {row['price']} | {row.get('date') or '-'} |"
        )
    if missing:
        lines.append("")
        lines.append(f"Not found in receipts: {', '.join(missing)}.")

    card = {
        "type": "shopping_list_prices",
        "title": "Best receipt prices",
        "rows": rows,
        "note": "Only matched receipt purchases are priced; unmatched items are not guessed.",
    }
    return "\n".join(lines), card


def recovery_candidate_item_spans(message: str) -> list[tuple[str, int, int]]:
    """Generate conservative alternate item interpretations for a failed receipt query."""
    base = clean_shopping_list_item(extract_query_item(message))
    tokens = [token for token in base.split() if token and token not in SHOPPING_LIST_NOISE_WORDS]
    candidates: list[tuple[str, int, int]] = []
    seen: set[str] = set()

    def add(candidate: str, start: int, end: int) -> None:
        cleaned = clean_shopping_list_item(candidate)
        if not cleaned or cleaned in seen or cleaned == base:
            return
        if not token_set(cleaned) or len(token_set(cleaned)) > 5:
            return
        seen.add(cleaned)
        candidates.append((cleaned, start, end))

    for item in extract_shopping_list_items(message):
        add(item, -1, -1)
        for split_item in split_failed_shopping_item(item):
            add(split_item, -1, -1)

    for split_item in split_failed_shopping_item(base):
        add(split_item, -1, -1)

    for size in range(min(4, len(tokens)), 0, -1):
        for start in range(0, len(tokens) - size + 1):
            span = tokens[start:start + size]
            if size == 1 and span[0] not in SHOPPING_LIST_BOUNDARY_TERMS and span[0] not in KNOWN_ITEM_TERMS:
                continue
            add(" ".join(span), start, start + size)

    return candidates[:40]


def adaptive_failed_query_recovery(
    message: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    extra_families: list[set[str]] | None = None,
) -> tuple[str, dict] | None:
    """Retry a failed item query as smaller evidence-backed item interpretations."""
    accepted: list[tuple[str, int, int]] = []
    occupied: set[int] = set()
    accepted_event_keys: set[tuple] = set()

    for candidate, start, end in recovery_candidate_item_spans(message):
        if start >= 0 and occupied.intersection(range(start, end)):
            continue
        rag = retrieve_item_events(f"best price for {candidate}", user_id, guest_session_id, limit=8, extra_families=extra_families)
        display = clean_item_query_for_display(candidate)
        events = dedupe_item_events(trusted_item_events_for_answer(display, rag.get("events") or []))
        best = best_price_event(events)
        if not best:
            continue
        event_key = (best.get("receipt_id"), best.get("line_index"), normalize_text(best.get("item_original") or ""))
        if event_key in accepted_event_keys:
            continue
        accepted_event_keys.add(event_key)
        accepted.append((candidate, start, end))
        if start >= 0:
            occupied.update(range(start, end))
        if len(accepted) >= 8:
            break

    if not accepted:
        return None

    recovered_items = [candidate for candidate, _, _ in accepted]
    for item in extract_shopping_list_items(message):
        split_items = split_failed_shopping_item(item) or [item]
        for split_item in split_items:
            cleaned = clean_shopping_list_item(split_item)
            if cleaned and cleaned not in recovered_items:
                recovered_items.append(cleaned)
    answer, card = shopping_list_price_answer(
        "best price for listed items\n" + "\n".join(recovered_items),
        user_id,
        guest_session_id,
        extra_families,
    )
    card["type"] = "adaptive_recovered_prices"
    card["title"] = "Recovered receipt prices"
    card["note"] = "The first interpretation did not match, so ReceiptAI retried smaller item candidates and answered only from receipt evidence."
    return answer, card


def category_price_answer(category: str, item_events: list[dict], message: str) -> str:
    display_category = clean_item_query_for_display(category or "items")
    normalized_category = normalize_text(display_category)
    matched: list[dict] = []

    for event in item_events:
        if price_memory_event_price(event) <= 0:
            continue
        if normalized_category == "meat":
            if looks_like_prepared_dish(event):
                continue
            if not looks_like_raw_meat_event(event):
                continue
        elif normalized_category in {"vegetable", "vegetables", "veggie", "veggies", "produce"} and looks_like_non_raw_grocery_event(event):
            continue
        elif not event_matches_semantic_family(event, normalized_category, None):
            continue
        matched.append(event)

    if not matched:
        if normalized_category == "meat":
            return "I did not find grocery/raw meat purchases in your receipts yet. Prepared dishes were not counted as meat prices."
        return f"I did not find clear {display_category} purchases in your receipts yet."

    matched = dedupe_item_events(matched)
    matched.sort(key=lambda event: (price_memory_event_price(event), event.get("date") or "", event.get("store") or ""))
    asks_best = query_asks_for_best_price(message)
    asks_history = query_asks_for_history(message)

    if asks_best:
        best = matched[0]
        lines = [
            f"Cheapest {display_category} found: {best.get('item_original') or display_category}",
            metric_line("Price", event_price_text(best)),
            metric_line("Store", compact_text(best.get("store") or "Unknown store", 28)),
            metric_line("Date", best.get("date") or "unknown"),
            metric_line("Receipt line", item_line_detail(best)),
        ]
        if asks_history:
            lines.extend(["", f"Lowest {display_category} prices"])
            for index, event in enumerate(matched[:6], 1):
                lines.append(
                    f"{index}. {compact_text(event.get('item_original'), 28)} - {event_price_text(event)}"
                )
                lines.append(
                    f"   {compact_text(event.get('store') or 'Unknown store', 24)} | {event.get('date') or 'unknown'} | {item_line_detail(event)}"
                )
    else:
        grouped: dict[str, dict] = {}
        for event in matched:
            key = normalize_text(event.get("item_original") or "")
            current = grouped.get(key)
            if not current or price_memory_event_price(event) < price_memory_event_price(current):
                grouped[key] = event
        representative_events = sorted(grouped.values(), key=lambda event: price_memory_event_price(event))
        lines = [f"{display_category.title()} purchases found"]
        for index, event in enumerate(representative_events[:8], 1):
            lines.append(
                f"{index}. {compact_text(event.get('item_original'), 28)} - lowest {event_price_text(event)}"
            )
            lines.append(
                f"   {compact_text(event.get('store') or 'Unknown store', 24)} | {event.get('date') or 'unknown'} | {item_line_detail(event)}"
            )

    return "\n".join(lines)


def category_price_answer_card(category: str, item_events: list[dict], message: str) -> dict | None:
    display_category = clean_item_query_for_display(category or "items")
    normalized_category = normalize_text(display_category)
    matched: list[dict] = []

    for event in item_events:
        if price_memory_event_price(event) <= 0:
            continue
        if normalized_category == "meat":
            if looks_like_prepared_dish(event):
                continue
            if not looks_like_raw_meat_event(event):
                continue
        elif normalized_category in {"vegetable", "vegetables", "veggie", "veggies", "produce"} and looks_like_non_raw_grocery_event(event):
            continue
        elif not event_matches_semantic_family(event, normalized_category, None):
            continue
        matched.append(event)

    matched = dedupe_item_events(matched)
    if not matched:
        return None

    matched.sort(key=lambda event: (price_memory_event_price(event), event.get("date") or "", event.get("store") or ""))
    if query_asks_for_best_price(message):
        return event_answer_card(matched[0], f"Cheapest {display_category}", "category_best_price")

    rows = []
    grouped: dict[str, dict] = {}
    for event in matched:
        key = normalize_text(event.get("item_original") or "")
        current = grouped.get(key)
        if not current or price_memory_event_price(event) < price_memory_event_price(current):
            grouped[key] = event
    for event in sorted(grouped.values(), key=price_memory_event_price)[:6]:
        rows.append({
            "item": event.get("item_original"),
            "price": event_price_text(event),
            "store": event.get("store") or "Unknown store",
            "date": event.get("date") or "unknown date",
            "receipt_id": event.get("receipt_id"),
            "line_index": event.get("line_index"),
            "detail": item_line_detail(event),
        })
    return {
        "type": "category_list",
        "title": f"{display_category.title()} purchases",
        "rows": rows,
        "note": None,
    }


def category_with_included_items_answer(
    category: str,
    item_events: list[dict],
    message: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    extra_families: list[set[str]] | None = None,
) -> tuple[str, dict]:
    base_card = category_price_answer_card(category, item_events, f"show {category} prices") or {
        "type": "category_list",
        "title": f"{clean_item_query_for_display(category).title()} purchases",
        "rows": [],
        "note": None,
    }
    rows = []
    row_keys: set[tuple] = set()

    def row_key(row: dict) -> tuple:
        if row.get("receipt_id") is not None or row.get("line_index") is not None:
            return ("receipt_line", row.get("receipt_id"), row.get("line_index"))
        return ("missing", normalize_text(row.get("item") or ""))

    for row in base_card.get("rows") or []:
        key = row_key(row)
        if key in row_keys:
            continue
        row_keys.add(key)
        rows.append(row)
    seen_items = {normalize_text(row.get("item") or "") for row in rows}

    for item in extract_shopping_list_items(message):
        item_key = normalize_text(item)
        if not item_key or item_key in seen_items:
            continue
        if token_set(item_key) <= (BROAD_CATEGORY_QUERY_TERMS | BROAD_MEAT_QUERY_TERMS | {"grocery", "raw"}):
            continue
        rag = retrieve_item_events(f"best price for {item}", user_id, guest_session_id, limit=12, extra_families=extra_families)
        display_item = clean_item_query_for_display(item)
        events = dedupe_item_events(trusted_item_events_for_answer(display_item, rag.get("events") or []))
        best = best_price_event(events)
        if best:
            row = {
                "item": best.get("item_original") or display_item,
                "price": event_price_text(best),
                "store": best.get("store") or "Unknown store",
                "date": best.get("date") or "unknown date",
                "receipt_id": best.get("receipt_id"),
                "line_index": best.get("line_index"),
                "detail": item_line_detail(best),
            }
            key = row_key(row)
            if key in row_keys:
                continue
            row_keys.add(key)
            rows.append(row)
            seen_items.add(normalize_text(best.get("item_original") or display_item))
        else:
            row = {
                "item": display_item,
                "price": "Not found",
                "store": "",
                "date": "",
                "receipt_id": None,
                "line_index": None,
                "detail": "No clear matching receipt purchase",
            }
            key = row_key(row)
            if key in row_keys:
                continue
            row_keys.add(key)
            rows.append(row)
            seen_items.add(item_key)

    display_category = clean_item_query_for_display(category or "items").title()
    card = {
        "type": "category_list",
        "title": f"{display_category} prices with requested items",
        "rows": rows[:12],
        "note": "Includes category matches from receipts plus requested items when they were named.",
    }
    lines = [card["title"]]
    for index, row in enumerate(card["rows"], 1):
        price = row.get("price") or "Not found"
        item = row.get("item") or "Item"
        if price == "Not found":
            lines.append(f"{index}. {item} - Not found")
        else:
            lines.append(f"{index}. {item} - {price}")
            lines.append(f"   {row.get('store') or 'Unknown store'} | {row.get('date') or 'unknown'} | {row.get('detail') or ''}")
    return "\n".join(lines), card


def money(value: Any) -> str:
    return f"${_safe_float(value):.2f}"


def compact_text(value: Any, limit: int = 24) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)].rstrip() + "..."


def metric_line(label: str, value: Any) -> str:
    return f"{label:<14} {value}"


def ranked_money_rows(rows: list[tuple[str, Any, str]], limit: int = 5) -> list[str]:
    output = []
    for index, row in enumerate(rows[:limit], 1):
        if len(row) == 2:
            name, value = row
            detail = ""
        else:
            name, value, detail = row
        output.append(f"{index}. {compact_text(name, 24):<24} {money(value):>8}")
        if detail:
            output.append(f"   {detail}")
    return output


def receipt_count_text(count: Any) -> str:
    value = int(_safe_float(count, 0))
    return f"{value} receipt" if value == 1 else f"{value} receipts"


def receipt_text(receipt: dict) -> str:
    item_text = " ".join(
        " ".join(str(item.get(k, "")) for k in ("name", "item", "code"))
        for item in (receipt.get("items") or [])
        if isinstance(item, dict)
    )
    return normalize_text(" ".join([
        str(receipt.get("store") or ""),
        str(receipt.get("address") or ""),
        str(receipt.get("payment_method") or ""),
        item_text,
    ]))


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def receipt_category(receipt: dict) -> str:
    text = receipt_text(receipt)
    if _has_any(text, ["bank", "atm", "withdrawal", "deposit", "credit union", "chase", "wells fargo", "bank of america", "capital one"]):
        return "Bank & Finance"
    if _has_any(text, ["hospital", "clinic", "medical center", "urgent care", "doctor", "dental", "dentist", "labcorp", "quest diagnostics", "patient"]):
        return "Hospital & Medical"
    if _has_any(text, ["cvs", "walgreens", "pharmacy", "rx", "medicine", "vitamin", "health"]):
        return "Pharmacy & Health"
    if _has_any(text, ["lowes", "home depot", "tractor supply", "garden", "mulch", "soil", "plant", "rose", "fertilizer", "hardware", "paint", "lumber"]):
        return "Gardening & Hardware"
    if _has_any(text, ["restaurant", "cafe", "pizza", "burger", "taco", "mcdonald", "starbucks", "subway", "doordash", "uber eats", "grubhub"]):
        return "Restaurants"
    if _has_any(text, ["walmart", "wal mart", "kroger", "aldi", "costco", "sam club", "supermarket", "market", "grocery", "food", "seafood", "milk", "bread", "egg"] + INDIAN_GROCERY_TERMS):
        return "Food & Grocery"
    if _has_any(text, ["shell", "exxon", "chevron", "circle k", "speedway", "gas", "fuel", "auto", "oil change", "tire"]):
        return "Fuel & Auto"
    if _has_any(text, ["ikea", "household", "cleaner", "detergent", "furniture", "kitchen"]):
        return "Home & Household"
    if _has_any(text, ["amazon", "best buy", "tj maxx", "marshalls", "mall", "clothing", "shoes", "apparel", "electronics"]):
        return "Retail Shopping"
    return "Other"


def parse_receipt_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def receipt_month_key(receipt: dict) -> str:
    parsed = receipt_analysis_date(receipt)
    if parsed:
        return parsed.strftime("%Y-%m")
    raw = receipt.get("date") or receipt.get("created_at") or "Unknown"
    return str(raw)[:7]


def receipt_analysis_date(receipt: dict) -> datetime | None:
    parsed = parse_receipt_date(receipt.get("date"))
    today = datetime.now()
    if parsed and datetime(2000, 1, 1) <= parsed <= today + timedelta(days=1):
        return parsed
    fallback = parse_receipt_date((receipt.get("created_at") or "")[:10])
    if fallback and datetime(2000, 1, 1) <= fallback <= today + timedelta(days=1):
        return fallback
    return parsed or fallback


def receipt_week_key(receipt: dict) -> tuple[str, str, str]:
    parsed = receipt_analysis_date(receipt)
    if not parsed:
        raw = str(receipt.get("date") or receipt.get("created_at") or "Unknown date")
        return raw, raw, raw
    start = parsed - timedelta(days=parsed.weekday())
    end = start + timedelta(days=6)
    return (
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
        f"{start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}",
    )


def event_date(event: dict) -> datetime | None:
    return parse_receipt_date(event.get("date")) or parse_receipt_date((event.get("created_at") or "")[:10])


def price_memory_event_price(event: dict) -> float:
    line_price = _safe_float(event.get("line_price"), 0.0)
    unit_price = _safe_float(event.get("unit_price"), 0.0)
    quantity = _safe_float(event.get("quantity"), 1.0) or 1.0
    unit = normalize_text(event.get("unit") or "each")
    if unit and unit != "each" and line_price > 0 and quantity > 0:
        derived_unit_price = round(line_price / quantity, 2)
        if unit_price > 0 and abs(unit_price - line_price) > 0.01:
            return unit_price
        return derived_unit_price
    if unit_price > 0 and quantity > 1:
        return unit_price
    if line_price > 0 and quantity > 1 and event.get("explicit_quantity"):
        return round(line_price / quantity, 2)
    return line_price


def receipt_item_name_fingerprint(receipt: dict) -> set[str]:
    names: set[str] = set()
    for item in receipt.get("items") or []:
        if not isinstance(item, dict):
            continue
        name = normalize_text(item.get("name") or item.get("item") or "")
        if not name or "discount" in name or "coupon" in name:
            continue
        names.add(name)
    return names


def receipt_item_token_fingerprint(receipt: dict) -> set[str]:
    tokens: set[str] = set()
    for name in receipt_item_name_fingerprint(receipt):
        tokens.update(token_set(name))
    return {token for token in tokens if len(token) > 2 and not token.isdigit()}


def looks_like_same_receipt(scanned: dict, existing: dict) -> bool:
    scanned_total = _safe_float(scanned.get("total"), None)
    existing_total = _safe_float(existing.get("total"), None)
    if scanned_total is None or existing_total is None or abs(scanned_total - existing_total) > 0.05:
        return False

    scanned_date = parse_receipt_date(scanned.get("date"))
    existing_date = parse_receipt_date(existing.get("date"))
    dates_match = bool(scanned_date and existing_date and scanned_date.date() == existing_date.date())
    if scanned_date and existing_date and not dates_match:
        return False

    scanned_store = normalize_text(scanned.get("store") or "")
    existing_store = normalize_text(existing.get("store") or "")
    store_matches = bool(
        scanned_store
        and existing_store
        and (scanned_store == existing_store or scanned_store in existing_store or existing_store in scanned_store)
    )

    scanned_items = receipt_item_name_fingerprint(scanned)
    existing_items = receipt_item_name_fingerprint(existing)
    if scanned_items and existing_items:
        common = scanned_items & existing_items
        overlap = len(common) / max(1, min(len(scanned_items), len(existing_items)))
        if store_matches and (len(common) >= 2 or overlap >= 0.45):
            return True
        scanned_tokens = receipt_item_token_fingerprint(scanned)
        existing_tokens = receipt_item_token_fingerprint(existing)
        token_common = scanned_tokens & existing_tokens
        token_overlap = len(token_common) / max(1, min(len(scanned_tokens), len(existing_tokens)))
        return dates_match and store_matches and token_overlap >= 0.55

    return store_matches and dates_match


def build_price_memory(user_id: str | None = None, guest_session_id: str | None = None, limit: int = 1000) -> list[dict]:
    """Create personal Price DNA profiles from real receipt item events."""
    item_events = fetch_owner_item_events(user_id, guest_session_id, limit=limit)
    if not item_events:
        receipts = fetch_owner_receipts(user_id, guest_session_id, limit=300)
        item_events = build_item_events(receipts)

    grouped: dict[str, dict[str, Any]] = {}
    for event in item_events:
        price = price_memory_event_price(event)
        name = str(event.get("item_original") or "").strip()
        if not name or price <= 0:
            continue
        if name.upper().startswith("DISCOUNT") or "discount" in name.lower() or "coupon" in name.lower():
            continue

        normalized = event.get("item_normalized") or normalize_text(name)
        product_size = event.get("product_size") or ""
        key = f"{normalized}|{product_size}"
        grouped.setdefault(key, {
            "item_name": name,
            "item_name_normalized": normalized,
            "product_size": product_size or None,
            "events": [],
            "stores": {},
            "dates": [],
        })
        grouped[key]["events"].append(event)
        grouped[key]["stores"].setdefault(event.get("store") or "Unknown store", [])
        grouped[key]["stores"][event.get("store") or "Unknown store"].append(price)
        parsed_date = event_date(event)
        if parsed_date:
            grouped[key]["dates"].append(parsed_date)

    profiles = []
    today = datetime.now()
    for data in grouped.values():
        events = data["events"]
        prices = [price_memory_event_price(e) for e in events if price_memory_event_price(e) > 0]
        if not prices:
            continue

        sorted_prices = sorted(prices)
        lowest = min(sorted_prices)
        highest = max(sorted_prices)
        avg = sum(sorted_prices) / len(sorted_prices)
        usual = median(sorted_prices)
        spread = highest - lowest
        volatility_pct = (spread / usual * 100) if usual else 0

        cheapest_event = min(events, key=lambda e: price_memory_event_price(e) or 999999)
        latest_event = max(events, key=lambda e: event_date(e) or datetime.min)
        dates = sorted(data["dates"])
        frequency_days = None
        next_expected_date = None
        if len(dates) >= 2:
            gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates)) if (dates[i] - dates[i - 1]).days >= 0]
            if gaps:
                frequency_days = round(sum(gaps) / len(gaps), 1)
                next_expected = dates[-1] + (dates[-1] - dates[-2] if len(dates) >= 2 else today - today)
                next_expected_date = next_expected.strftime("%Y-%m-%d")

        store_averages = {
            store: round(sum(vals) / len(vals), 2)
            for store, vals in data["stores"].items()
            if vals
        }
        cheapest_store = min(store_averages, key=store_averages.get) if store_averages else cheapest_event.get("store")

        good_deal_price = lowest if len(prices) == 1 else round(min(usual * 0.9, avg - (spread * 0.25)), 2)
        avoid_above_price = round(max(usual * 1.15, avg + (spread * 0.35)), 2)
        days_since_last = None
        last_date = event_date(latest_event)
        if last_date:
            days_since_last = max(0, (today - last_date).days)

        recommendation = "watch"
        if len(prices) >= 2 and spread > 0 and volatility_pct >= 20:
            recommendation = "compare before buying"
        if frequency_days and days_since_last is not None and days_since_last >= max(1, frequency_days * 0.8):
            recommendation = "may need soon"
        if len(prices) == 1:
            recommendation = "needs more history"

        profiles.append({
            "item_name": data["item_name"],
            "item_name_normalized": data["item_name_normalized"],
            "product_size": data["product_size"],
            "times_bought": len(events),
            "lowest_price": round(lowest, 2),
            "highest_price": round(highest, 2),
            "average_price": round(avg, 2),
            "usual_price": round(usual, 2),
            "price_range": round(spread, 2),
            "volatility_pct": round(volatility_pct, 1),
            "good_deal_price": round(good_deal_price, 2),
            "avoid_above_price": round(avoid_above_price, 2),
            "cheapest_store": cheapest_store,
            "cheapest_store_average": store_averages.get(cheapest_store) if cheapest_store else None,
            "last_bought_date": latest_event.get("date") or (latest_event.get("created_at") or "")[:10],
            "last_receipt_id": latest_event.get("receipt_id"),
            "last_line_index": latest_event.get("line_index"),
            "cheapest_receipt_id": cheapest_event.get("receipt_id"),
            "cheapest_line_index": cheapest_event.get("line_index"),
            "buy_frequency_days": frequency_days,
            "next_expected_date": next_expected_date,
            "days_since_last_buy": days_since_last,
            "recommendation": recommendation,
            "recent_events": [
                {
                    "store": e.get("store"),
                    "date": e.get("date"),
                    "price": e.get("line_price"),
                    "compare_price": price_memory_event_price(e),
                    "quantity": e.get("quantity"),
                    "unit": e.get("unit"),
                    "unit_price": e.get("unit_price"),
                    "receipt_id": e.get("receipt_id"),
                }
                for e in sorted(events, key=lambda e: e.get("created_at") or e.get("date") or "", reverse=True)[:5]
            ],
            "price_events": [
                {
                    "store": e.get("store"),
                    "date": e.get("date"),
                    "price": e.get("line_price"),
                    "compare_price": price_memory_event_price(e),
                    "quantity": e.get("quantity"),
                    "unit": e.get("unit"),
                    "unit_price": e.get("unit_price"),
                    "receipt_id": e.get("receipt_id"),
                    "line_index": e.get("line_index"),
                }
                for e in events
            ],
        })

    profiles.sort(key=lambda p: (p["recommendation"] == "may need soon", p["times_bought"], p["price_range"]), reverse=True)
    return profiles


def search_price_memory(item_query: str, user_id: str | None = None, guest_session_id: str | None = None, limit: int = 8) -> dict:
    profiles = build_price_memory(user_id, guest_session_id)
    query = extract_query_item(item_query)
    comparable_tokens = price_memory_compare_tokens(query)
    score_query = " ".join(sorted(comparable_tokens)) if comparable_tokens else query
    query_tokens = token_set(score_query)
    scored = []
    for profile in profiles:
        score = item_match_score(score_query, profile["item_name"], None)
        profile_tokens = token_set(profile["item_name"])
        query_coverage = len(query_tokens & profile_tokens) / max(1, len(query_tokens))
        is_specific_long_query = len(query_tokens) >= 3
        if is_specific_long_query and query_coverage < 0.5:
            continue
        min_score = 0.62 if is_specific_long_query else 0.35
        if score >= min_score and price_memory_match_is_comparable(score_query, profile["item_name"], score):
            scored.append({**profile, "match_score": score})
    scored.sort(key=lambda p: (p["match_score"], p["times_bought"]), reverse=True)
    return {
        "query": item_query,
        "normalized_query": query,
        "matches": scored[:limit],
        "count": len(scored),
    }


def build_next_shopping_plan(user_id: str | None = None, guest_session_id: str | None = None) -> dict:
    """Turn Price Memory into a next-purchase shopping plan."""
    profiles = build_price_memory(user_id, guest_session_id)
    may_need = [p for p in profiles if p.get("recommendation") == "may need soon"]
    compare = sorted(
        [p for p in profiles if p.get("recommendation") == "compare before buying"],
        key=lambda p: p.get("price_range") or 0,
        reverse=True,
    )

    plan_items = []
    for profile in may_need[:10]:
        plan_items.append({
            "item_name": profile["item_name"],
            "usual_price": profile["usual_price"],
            "good_deal_price": profile["good_deal_price"],
            "avoid_above_price": profile["avoid_above_price"],
            "cheapest_store": profile.get("cheapest_store"),
            "last_bought_date": profile.get("last_bought_date"),
            "receipt_id": profile.get("last_receipt_id") or profile.get("cheapest_receipt_id"),
            "line_index": profile.get("last_line_index") if profile.get("last_receipt_id") else profile.get("cheapest_line_index"),
            "buy_frequency_days": profile.get("buy_frequency_days"),
            "next_expected_date": profile.get("next_expected_date"),
            "reason": "You buy this repeatedly and it looks close to your normal buying rhythm.",
        })

    compare_items = []
    for profile in compare[:8]:
        compare_items.append({
            "item_name": profile["item_name"],
            "usual_price": profile["usual_price"],
            "lowest_price": profile["lowest_price"],
            "highest_price": profile["highest_price"],
            "price_range": profile["price_range"],
            "cheapest_store": profile.get("cheapest_store"),
            "receipt_id": profile.get("cheapest_receipt_id") or profile.get("last_receipt_id"),
            "line_index": profile.get("cheapest_line_index") if profile.get("cheapest_receipt_id") else profile.get("last_line_index"),
            "reason": f"Your price has moved by {money(profile.get('price_range'))}, so compare before buying.",
        })

    watch_items = []
    for profile in sorted(profiles, key=lambda p: (p.get("times_bought") or 0, p.get("price_range") or 0), reverse=True)[:8]:
        watch_items.append({
            "item_name": profile["item_name"],
            "usual_price": profile["usual_price"],
            "good_deal_price": profile["good_deal_price"],
            "avoid_above_price": profile["avoid_above_price"],
            "cheapest_store": profile.get("cheapest_store"),
            "last_bought_date": profile.get("last_bought_date"),
            "receipt_id": profile.get("last_receipt_id") or profile.get("cheapest_receipt_id"),
            "line_index": profile.get("last_line_index") if profile.get("last_receipt_id") else profile.get("cheapest_line_index"),
            "reason": "Useful watch item from your receipt history.",
        })

    estimated_total = round(sum(_safe_float(item.get("usual_price")) for item in plan_items), 2)
    best_case_total = round(sum(_safe_float(item.get("good_deal_price")) for item in plan_items), 2)
    estimated_savings = round(max(0, estimated_total - best_case_total), 2)

    stores: dict[str, float] = {}
    for item in plan_items:
        store = item.get("cheapest_store") or "Unknown store"
        stores[store] = stores.get(store, 0) + _safe_float(item.get("usual_price"))

    return {
        "plan_items": plan_items,
        "compare_items": compare_items,
        "watch_items": watch_items,
        "estimated_total": estimated_total,
        "best_case_total": best_case_total,
        "estimated_savings": estimated_savings,
        "stores_to_visit": [{"store": s, "estimated_total": round(v, 2)} for s, v in sorted(stores.items(), key=lambda x: -x[1])],
        "message": "No repeat item looks due yet." if not plan_items else "Next shopping plan built from your personal Price Memory.",
    }


def next_shopping_plan_answer(user_id: str | None = None, guest_session_id: str | None = None) -> str:
    plan = build_next_shopping_plan(user_id, guest_session_id)
    items = plan.get("plan_items") or []
    compare_items = plan.get("compare_items") or []
    watch_items = plan.get("watch_items") or []
    if not items and not compare_items:
        if not watch_items:
            return "Shopping plan\nNo repeat item looks due yet. Keep scanning receipts and I will learn your buying rhythm."
        lines = ["Shopping plan", "No repeat item looks due yet, but these are worth checking before your next trip:"]
        for item in watch_items[:6]:
            lines.append(
                f"- {item['item_name']}: target {money(item['good_deal_price'])}, store {item.get('cheapest_store') or 'unknown'}"
            )
        return "\n".join(lines)

    lines = ["Next shopping plan"]
    if items:
        lines.append(f"Estimated usual total: {money(plan['estimated_total'])}")
        if plan.get("estimated_savings", 0) > 0:
            lines.append(f"Good-deal target could save about {money(plan['estimated_savings'])}.")
        lines.append("")
        lines.append("May need soon")
        for item in items[:6]:
            lines.append(
                f"- {item['item_name']}: usual {money(item['usual_price'])}, good deal {money(item['good_deal_price'])}, store {item.get('cheapest_store') or 'unknown'}"
            )

    if compare_items:
        lines.append("")
        lines.append("Compare before buying")
        for item in compare_items[:4]:
            lines.append(f"- {item['item_name']}: price swing {money(item['price_range'])}")

    return "\n".join(lines)


def shopping_plan_answer_card(user_id: str | None = None, guest_session_id: str | None = None) -> dict | None:
    """Structured card for Agent shopping-plan answers with receipt tap-through evidence."""
    plan = build_next_shopping_plan(user_id, guest_session_id)
    rows = []
    for item in (plan.get("plan_items") or [])[:6]:
        rows.append({
            "item": item.get("item_name"),
            "price": f"Target {money(item.get('good_deal_price'))}",
            "store": item.get("cheapest_store") or "Unknown store",
            "date": item.get("last_bought_date") or "",
            "receipt_id": item.get("receipt_id"),
            "line_index": item.get("line_index"),
            "detail": f"Usual {money(item.get('usual_price'))}; avoid above {money(item.get('avoid_above_price'))}",
        })

    if not rows:
        for item in (plan.get("compare_items") or [])[:6]:
            rows.append({
                "item": item.get("item_name"),
                "price": f"Low {money(item.get('lowest_price'))}",
                "store": item.get("cheapest_store") or "Unknown store",
                "date": "",
                "receipt_id": item.get("receipt_id"),
                "line_index": item.get("line_index"),
                "detail": f"Price swing {money(item.get('price_range'))}; usual {money(item.get('usual_price'))}",
            })

    if not rows:
        for item in (plan.get("watch_items") or [])[:6]:
            rows.append({
                "item": item.get("item_name"),
                "price": f"Target {money(item.get('good_deal_price'))}",
                "store": item.get("cheapest_store") or "Unknown store",
                "date": item.get("last_bought_date") or "",
                "receipt_id": item.get("receipt_id"),
                "line_index": item.get("line_index"),
                "detail": f"Usual {money(item.get('usual_price'))}; avoid above {money(item.get('avoid_above_price'))}",
            })

    if not rows:
        return None

    return {
        "type": "shopping_plan",
        "title": "This month buy list",
        "item": "Repeat purchases from your receipt memory",
        "price": money(plan.get("estimated_total")),
        "store": (plan.get("stores_to_visit") or [{}])[0].get("store") or "Best known stores",
        "detail": f"Good-deal savings target {money(plan.get('estimated_savings'))}",
        "receipt_id": rows[0].get("receipt_id"),
        "line_index": rows[0].get("line_index"),
        "note": "Tap any row to review the receipt behind that suggestion.",
        "rows": rows,
    }


def price_memory_answer_card(user_id: str | None = None, guest_session_id: str | None = None) -> dict | None:
    profiles = build_price_memory(user_id, guest_session_id)
    rows = []
    for profile in profiles[:6]:
        rows.append({
            "item": profile.get("item_name"),
            "price": f"Low {money(profile.get('lowest_price'))}",
            "store": profile.get("cheapest_store") or "Unknown store",
            "date": profile.get("last_bought_date") or "",
            "receipt_id": profile.get("cheapest_receipt_id") or profile.get("last_receipt_id"),
            "line_index": profile.get("cheapest_line_index") if profile.get("cheapest_receipt_id") else profile.get("last_line_index"),
            "detail": f"Usual {money(profile.get('usual_price'))}; avoid above {money(profile.get('avoid_above_price'))}",
        })

    if not rows:
        return None

    return {
        "type": "price_memory",
        "title": "Price Memory",
        "item": "Verified receipt prices",
        "price": f"{len(profiles)} items",
        "store": "Your receipts",
        "detail": "Lowest, usual, and avoid-above prices",
        "receipt_id": rows[0].get("receipt_id"),
        "line_index": rows[0].get("line_index"),
        "note": "Open receipt evidence before trusting a deal.",
        "rows": rows,
    }


def build_price_alerts(user_id: str | None = None, guest_session_id: str | None = None) -> dict:
    """Create proactive alerts from Price Memory."""
    profiles = build_price_memory(user_id, guest_session_id)
    alerts = []

    for profile in profiles:
        if profile.get("recommendation") == "may need soon":
            alerts.append({
                "type": "may_need_soon",
                "severity": "info",
                "title": f"You may need {profile['item_name']} soon",
                "message": f"You usually buy it about every {profile.get('buy_frequency_days')} days. Good deal is {money(profile.get('good_deal_price'))}.",
                "item_name": profile["item_name"],
                "target_price": profile.get("good_deal_price"),
                "store": profile.get("cheapest_store"),
            })

        if profile.get("price_range", 0) >= 5 or profile.get("volatility_pct", 0) >= 25:
            alerts.append({
                "type": "price_swing",
                "severity": "warning",
                "title": f"Compare before buying {profile['item_name']}",
                "message": f"Your price has ranged from {money(profile.get('lowest_price'))} to {money(profile.get('highest_price'))}. Avoid above {money(profile.get('avoid_above_price'))}.",
                "item_name": profile["item_name"],
                "target_price": profile.get("good_deal_price"),
                "avoid_above_price": profile.get("avoid_above_price"),
                "store": profile.get("cheapest_store"),
            })

        if profile.get("times_bought", 0) >= 2 and profile.get("cheapest_store"):
            alerts.append({
                "type": "best_store",
                "severity": "tip",
                "title": f"{profile.get('cheapest_store')} has been best for {profile['item_name']}",
                "message": f"Your lowest price is {money(profile.get('lowest_price'))}. Usual price is {money(profile.get('usual_price'))}.",
                "item_name": profile["item_name"],
                "store": profile.get("cheapest_store"),
            })

    severity_order = {"warning": 3, "info": 2, "tip": 1}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 0), reverse=True)
    return {
        "alerts": alerts[:20],
        "count": len(alerts[:20]),
        "message": "No price alerts yet." if not alerts else "Price alerts built from your personal Price Memory.",
    }


def short_bar(value: float, max_value: float, width: int = 12) -> str:
    if max_value <= 0:
        return ""
    filled = max(1, round((value / max_value) * width))
    return "#" * filled + "-" * max(0, width - filled)


def rank_price_opportunities(item_events: list[dict], limit: int = 5) -> list[dict]:
    """Rank repeat items by practical savings opportunity."""
    by_item: dict[str, dict[str, Any]] = {}
    for event in item_events:
        price = _safe_float(event.get("line_price"), 0.0)
        name = str(event.get("item_original") or "").strip()
        if not name or price <= 0:
            continue
        if name.upper().startswith("DISCOUNT") or "discount" in name.lower() or "coupon" in name.lower():
            continue

        key = event.get("item_normalized") or normalize_text(name)
        by_item.setdefault(key, {"name": name, "prices": [], "stores": {}, "events": []})
        by_item[key]["prices"].append(price)
        store = event.get("store") or "Unknown store"
        by_item[key]["stores"].setdefault(store, [])
        by_item[key]["stores"][store].append(price)
        by_item[key]["events"].append(event)

    opportunities = []
    for data in by_item.values():
        prices = data["prices"]
        if len(prices) < 2:
            continue
        low = min(prices)
        high = max(prices)
        spread = high - low
        if spread <= 0:
            continue
        cheapest_store = min(
            data["stores"],
            key=lambda store: sum(data["stores"][store]) / max(len(data["stores"][store]), 1),
        )
        opportunities.append({
            "name": data["name"],
            "times": len(prices),
            "low": round(low, 2),
            "high": round(high, 2),
            "spread": round(spread, 2),
            "cheapest_store": cheapest_store,
            "latest_date": max((e.get("date") or "" for e in data["events"]), default=""),
        })

    opportunities.sort(key=lambda item: (item["spread"], item["times"]), reverse=True)
    return opportunities[:limit]


def looks_like_overview_question(message: str) -> bool:
    return agent_analytics.looks_like_overview_question(
        message,
        normalize_text=normalize_text,
        correct_query_words=correct_query_words,
    )


def looks_like_weekly_question(message: str) -> bool:
    return agent_analytics.looks_like_weekly_question(message, normalize_text=normalize_text)


def looks_like_category_spending_question(message: str) -> bool:
    return agent_analytics.looks_like_category_spending_question(message, normalize_text=normalize_text)


def looks_like_monthly_expense_question(message: str) -> bool:
    return agent_analytics.looks_like_monthly_expense_question(message, normalize_text=normalize_text)


def looks_like_repeat_price_trend_question(message: str) -> bool:
    return agent_analytics.looks_like_repeat_price_trend_question(
        message,
        normalize_text=normalize_text,
        correct_query_words=correct_query_words,
    )


def classify_receipt_action(message: str) -> str:
    m = correct_query_words(normalize_text(message))
    tokens = set(m.split())
    meaningful_tokens = tokens - STOP_WORDS
    if looks_like_global_price_question(message):
        return "global_cheapest"
    if looks_like_repeat_price_trend_question(message):
        return "item_price_trends"
    if any(term in m for term in [
        "bought together", "buy together", "usually buy with", "bought with",
        "items together", "common basket", "basket pattern", "graph memory",
        "relationship", "relationships", "category from", "categories from",
        "categories do i buy from", "what categories",
    ]):
        return "graph_memory"
    if looks_like_category_spending_question(message):
        return "category_spending"
    if looks_like_weekly_question(message):
        return "weekly_spending"
    if "price memory" in m or "price dna" in m or "avoid above prices" in m:
        return "price_memory"
    if "avoid" in tokens and "above" in tokens and "price" in tokens:
        return "price_memory"
    polite_stripped_tokens = tokens - {"please", "pls", "now"}
    if polite_stripped_tokens <= {"product", "products", "item", "items"} and polite_stripped_tokens:
        return "price_memory"
    if (polite_stripped_tokens <= {"receipt", "receipts"} and polite_stripped_tokens) or any(term in m for term in ["show me all receipts", "all receipts"]):
        return "recent_receipts"
    if any(term in m for term in [
        "next shopping", "shopping plan", "shopping list", "what should i buy next",
        "what should i buy this month", "items to purchase", "purchase this month",
        "this month items", "plan my next", "next grocery", "grocery shopping trip",
        "plan grocery", "plan shopping", "next coming month", "coming month",
        "want i should", "shopping",
    ]):
        return "shopping_plan"
    if looks_like_monthly_expense_question(message):
        return "monthly_spending"
    if any(term in m for term in [
        "compare before buying", "items should i compare", "what should i compare",
        "which items should i compare", "compare items before buying",
        "biggest price swing", "price swing", "biggest price difference",
        "price difference items",
    ]):
        return "best_deals"
    if any(term in m for term in [
        "market price comparison", "compare my prices", "where i overpaid",
        "overpaid", "over pay", "overpay",
    ]):
        return "market_comparison"
    if any(term in m for term in [
        "live price", "current price", "real time price", "realtime price",
        "market price", "market prices", "current market", "today price",
    ]):
        return "live_price_check"
    if any(term in m for term in [
        "good price", "is this a good price", "avoid price", "avoid above",
        "should i buy", "buy now", "wait to buy",
    ]):
        return "price_check"
    if "good" in tokens and re.search(r"\d+(?:\.\d+)?", m):
        return "price_check"
    if any(term in m for term in [
        "tax", "taxes", "refund", "refunds", "return", "returns", "discount", "discounts",
    ]):
        return "tax_discount"
    if any(term in m for term in ["recent receipts", "latest receipts", "last receipts"]):
        return "recent_receipts"
    if any(term in m for term in [
        "store visits", "visit most", "where do i shop", "where i shop",
        "frequent store", "frequent stores", "go most often", "visit often",
        "shop most", "most often",
    ]):
        return "store_frequency"
    if any(term in m for term in [
        "spend the most", "spent the most", "spend most", "spent most",
        "store did i spend", "where did i spend", "which store did i spend",
        "top spend", "spending too much", "spend too much",
    ]):
        return "store_spend"
    if any(term in m for term in [
        "best store", "best value", "store breakdown", "stores by spend",
        "stores by spending", "table of stores", "store spend table",
        "spending by store", "break down my spending by store", "breakdown by store",
    ]):
        return "store_breakdown"
    if any(term in m for term in ["best deal", "best deals", "deals recently"]):
        return "best_deals"
    if any(term in m for term in [
        "mostly purchased", "mostly purchase", "most purchased",
        "frequently purchasing", "frequently purchased", "frequent purchases",
        "frequent items", "repeat items", "repeat purchases",
        "items purchased most", "products purchased most",
    ]):
        return "item_price_trends"
    if any(term in m for term in ["save money", "top 3 ways", "saving"]):
        return "save_money"
    if any(term in m for term in [
        "category", "categories", "categorize", "food receipts", "bank receipts",
        "hospital receipts", "medical receipts", "gardening receipts", "garden receipts",
    ]):
        return "category_spending"
    if any(term in m for term in [
        "analyze my spending", "analyse my spending", "analyze spending",
        "analyse spending", "spending analysis", "spend analysis",
    ]):
        return "open_analysis"
    if looks_like_overview_question(message):
        return "open_analysis"
    return ""


def regular_item_stats_from_events(events: list[dict]) -> list[dict]:
    by_item: dict[str, dict] = {}
    for event in events:
        key = event["item_normalized"]
        if not key or event.get("line_price") is None:
            continue
        by_item.setdefault(key, {"name": event["item_original"], "prices": [], "stores": set(), "dates": []})
        by_item[key]["prices"].append(_safe_float(event["line_price"]))
        by_item[key]["stores"].add(event["store"])
        by_item[key]["dates"].append(event.get("date") or "")

    regular = []
    for data in by_item.values():
        prices = data["prices"]
        if len(prices) >= 2:
            regular.append({
                "name": data["name"],
                "count": len(prices),
                "low": min(prices),
                "high": max(prices),
                "spread": max(prices) - min(prices),
                "stores": sorted(data["stores"]),
                "last_date": sorted([d for d in data["dates"] if d])[-1] if any(data["dates"]) else "",
            })
    regular.sort(key=lambda item: (item["count"], item["spread"]), reverse=True)
    return regular


def regular_item_stats(receipts: list[dict]) -> list[dict]:
    return regular_item_stats_from_events(build_item_events(receipts))


def monthly_expense_answer(receipts: list[dict], message: str) -> str:
    month_totals: dict[str, float] = {}
    month_counts: dict[str, int] = {}
    store_totals: dict[str, float] = {}
    item_totals: dict[str, float] = {}

    for receipt in receipts:
        month = receipt_month_key(receipt)
        total = _safe_float(receipt.get("total"))
        month_totals[month] = month_totals.get(month, 0) + total
        month_counts[month] = month_counts.get(month, 0) + 1

    if not month_totals:
        return "I do not see enough receipt data for a monthly analysis."

    target_month = datetime.now().strftime("%Y-%m")
    if target_month not in month_totals:
        target_month = sorted(month_totals)[-1]

    for receipt in receipts:
        if receipt_month_key(receipt) != target_month:
            continue
        store = receipt.get("store") or "Unknown store"
        store_totals[store] = store_totals.get(store, 0) + _safe_float(receipt.get("total"))
        for item in receipt.get("items") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or "Unknown item"
            item_totals[name] = item_totals.get(name, 0) + _safe_float(item.get("price"))

    lines = [f"Monthly expense analysis ({target_month})"]
    lines.append(metric_line("Total spent", money(month_totals[target_month])))
    lines.append(metric_line("Receipts", month_counts[target_month]))
    if "this month" not in normalize_text(message):
        lines.append("")
        lines.append("Month trend")
        for month, total in sorted(month_totals.items())[-6:]:
            lines.append(f"- {month}: {money(total)} across {receipt_count_text(month_counts.get(month, 0))}")

    if store_totals:
        lines.append("")
        lines.append("Store breakdown")
        store_rows = []
        for store, total in sorted(store_totals.items(), key=lambda x: x[1], reverse=True)[:5]:
            pct = (total / month_totals[target_month]) * 100 if month_totals[target_month] else 0
            store_rows.append((store, total, f"{pct:.0f}% of this month"))
        lines.extend(ranked_money_rows(store_rows))

    if item_totals:
        lines.append("")
        lines.append("Highest item spend")
        lines.extend(ranked_money_rows(sorted(item_totals.items(), key=lambda x: x[1], reverse=True), limit=5))

    return "\n".join(lines)


def weekly_expense_answer(receipts: list[dict], message: str) -> str:
    week_totals: dict[str, float] = {}
    week_counts: dict[str, int] = {}
    week_starts: dict[str, str] = {}

    for receipt in receipts:
        start, _end, label = receipt_week_key(receipt)
        total = _safe_float(receipt.get("total"))
        week_totals[label] = week_totals.get(label, 0.0) + total
        week_counts[label] = week_counts.get(label, 0) + 1
        week_starts[label] = start

    if not week_totals:
        return "I do not see enough receipt data for a weekly spending graph."

    ordered_labels = sorted(week_totals, key=lambda label: week_starts.get(label, label))
    latest_label = ordered_labels[-1]
    latest_store_totals: dict[str, float] = {}
    for receipt in receipts:
        _start, _end, label = receipt_week_key(receipt)
        if label != latest_label:
            continue
        store = receipt.get("store") or "Unknown store"
        latest_store_totals[store] = latest_store_totals.get(store, 0.0) + _safe_float(receipt.get("total"))

    lines = ["Weekly spending"]
    for label in ordered_labels[-8:]:
        lines.append(f"- {label}: {money(week_totals[label])} across {receipt_count_text(week_counts.get(label, 0))}")

    lines.append("")
    lines.append("Latest week")
    lines.append(metric_line("Range", latest_label))
    lines.append(metric_line("Total", money(week_totals[latest_label])))
    lines.append(metric_line("Receipts", week_counts[latest_label]))

    if latest_store_totals:
        lines.append("")
        lines.append("Top stores this week")
        rows = sorted(latest_store_totals.items(), key=lambda item: item[1], reverse=True)
        lines.extend(ranked_money_rows(rows, limit=4))

    return "\n".join(lines)


def receipt_memory_context(receipts: list[dict], item_events: list[dict]) -> dict:
    total_spent = sum(_safe_float(r.get("total")) for r in receipts)
    total_saved = sum(_safe_float(r.get("total_savings")) for r in receipts)
    store_totals: dict[str, float] = {}
    category_totals: dict[str, float] = {}
    month_totals: dict[str, float] = {}
    week_totals: dict[str, float] = {}
    week_counts: dict[str, int] = {}
    week_starts: dict[str, str] = {}

    for receipt in receipts:
        total = _safe_float(receipt.get("total"))
        store = receipt.get("store") or "Unknown store"
        category = receipt_category(receipt)
        month = receipt_month_key(receipt)
        start, _end, week_label = receipt_week_key(receipt)
        store_totals[store] = store_totals.get(store, 0.0) + total
        category_totals[category] = category_totals.get(category, 0.0) + total
        month_totals[month] = month_totals.get(month, 0.0) + total
        week_totals[week_label] = week_totals.get(week_label, 0.0) + total
        week_counts[week_label] = week_counts.get(week_label, 0) + 1
        week_starts[week_label] = start

    repeat_items = regular_item_stats_from_events(item_events)[:10]
    opportunities = rank_price_opportunities(item_events, limit=8)
    cheapest_events = sorted(
        [
            event for event in item_events
            if _safe_float(event.get("line_price")) > 0
            and not str(event.get("item_original") or "").lower().startswith("discount")
        ],
        key=lambda event: _safe_float(event.get("line_price")),
    )[:8]

    recent_receipts = sorted(
        receipts,
        key=lambda receipt: str(receipt.get("date") or receipt.get("created_at") or ""),
        reverse=True,
    )[:10]

    week_labels = sorted(week_totals, key=lambda label: week_starts.get(label, label))[-10:]
    month_labels = sorted(month_totals)[-8:]

    return {
        "receipt_count": len(receipts),
        "total_spent": round(total_spent, 2),
        "average_trip": round(total_spent / max(len(receipts), 1), 2),
        "recorded_savings": round(total_saved, 2),
        "weekly_spending": [
            {"week": label, "total": round(week_totals[label], 2), "receipts": week_counts[label]}
            for label in week_labels
        ],
        "monthly_spending": [
            {"month": label, "total": round(month_totals[label], 2)}
            for label in month_labels
        ],
        "store_breakdown": [
            {"store": store, "total": round(total, 2)}
            for store, total in sorted(store_totals.items(), key=lambda item: item[1], reverse=True)[:8]
        ],
        "category_breakdown": [
            {"category": category, "total": round(total, 2)}
            for category, total in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:8]
        ],
        "repeat_items": [
            {
                "item": item["name"],
                "count": item["count"],
                "low": round(item["low"], 2),
                "high": round(item["high"], 2),
                "spread": round(item["spread"], 2),
                "stores": item["stores"][:3],
                "last_date": item["last_date"],
            }
            for item in repeat_items
        ],
        "price_opportunities": opportunities,
        "lowest_priced_items": [
            {
                "item": event.get("item_original"),
                "store": event.get("store"),
                "date": event.get("date"),
                "price": round(_safe_float(event.get("line_price")), 2),
                "quantity": event.get("quantity"),
                "unit": event.get("unit"),
            }
            for event in cheapest_events
        ],
        "recent_receipts": [
            {
                "store": receipt.get("store"),
                "date": receipt.get("date") or (receipt.get("created_at") or "")[:10],
                "total": round(_safe_float(receipt.get("total")), 2),
                "category": receipt_category(receipt),
            }
            for receipt in recent_receipts
        ],
    }


def flexible_receipt_memory_answer(message: str, receipts: list[dict], item_events: list[dict]) -> str:
    if not AGENT_FLEXIBLE_MEMORY_ENABLED or not receipts:
        return ""

    context = receipt_memory_context(receipts, item_events)
    prompt = f"""
You are ReceiptAI, a consumer shopping-memory assistant.
Answer the user's request using ONLY the JSON receipt memory below.

Rules:
- If the user asks for week-wise/weekly, use weekly_spending and show full week ranges.
- If the user asks for month-wise/monthly, use monthly_spending.
- If the user asks for graph/chart, use compact ranked rows with totals; do not use ASCII bars or repeated block characters.
- If the user asks for a table, use aligned plain text rows, not markdown pipe tables.
- If the request is broad, infer the most useful receipt analysis instead of asking a clarification.
- Do not say you cannot access purchase history; the JSON is the purchase history.
- Do not recommend external apps or spreadsheets.
- Never invent stores, prices, dates, quantities, or totals.
- Keep the answer concise, polished, and useful on a phone.
- For saving tips, give exactly 3 actionable recommendations from the data.
- If the data is insufficient for the exact request, say what is missing and provide the closest useful receipt-based answer.

User request:
{message}

Receipt memory JSON:
{json.dumps(context, ensure_ascii=True)}
""".strip()

    if claude_client is not None:
        try:
            response = claude_client.messages.create(
                model=SONNET_MODEL,
                max_tokens=900,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
            if answer:
                return answer
        except Exception as e:
            print(f"[memory_assistant] unavailable: {e}")

    return ""


def smart_spending_overview_answer(receipts: list[dict], item_events: list[dict]) -> str:
    total_spent = sum(_safe_float(r.get("total")) for r in receipts)
    total_saved = sum(_safe_float(r.get("total_savings")) for r in receipts)
    avg_trip = total_spent / max(len(receipts), 1)

    store_totals: dict[str, float] = {}
    category_totals: dict[str, float] = {}
    month_totals: dict[str, float] = {}
    for receipt in receipts:
        store = receipt.get("store") or "Unknown store"
        store_totals[store] = store_totals.get(store, 0.0) + _safe_float(receipt.get("total"))
        category = receipt_category(receipt)
        category_totals[category] = category_totals.get(category, 0.0) + _safe_float(receipt.get("total"))
        month = receipt_month_key(receipt)
        month_totals[month] = month_totals.get(month, 0.0) + _safe_float(receipt.get("total"))

    top_store = max(store_totals, key=store_totals.get) if store_totals else "Unknown store"
    top_category = max(category_totals, key=category_totals.get) if category_totals else "Other"
    opportunities = rank_price_opportunities(item_events, limit=3)

    lines = [
        "Spending snapshot",
        metric_line("Total", f"{money(total_spent)} across {receipt_count_text(len(receipts))}"),
        metric_line("Avg trip", money(avg_trip)),
        metric_line("Top store", compact_text(top_store, 28)),
        metric_line("Top category", compact_text(top_category, 28)),
    ]
    if total_saved > 0:
        lines.append(metric_line("Saved", money(total_saved)))

    if month_totals:
        lines.append("")
        lines.append("Recent trend")
        for month, total in sorted(month_totals.items())[-4:]:
            lines.append(f"- {month}: {money(total)}")

    if category_totals:
        lines.append("")
        lines.append("Category mix")
        for category, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)[:4]:
            share = (total / total_spent * 100) if total_spent else 0
            lines.append(f"- {compact_text(category, 24)}: {money(total)} ({share:.0f}%)")

    if opportunities:
        lines.append("")
        lines.append("Best next moves")
        for i, item in enumerate(opportunities, 1):
            lines.append(
                f"{i}. {compact_text(item['name'], 28)}"
            )
            lines.append(f"   swing {money(item['spread'])} | best {compact_text(item['cheapest_store'], 22)}")
    else:
        lines.append("")
        lines.append("Best next move: compare repeat items before checkout.")

    return "\n".join(lines)


def purchase_suggestions_answer(receipts: list[dict], item_events: list[dict] | None = None) -> str:
    regular = regular_item_stats_from_events(item_events) if item_events else regular_item_stats(receipts)
    if not regular:
        return "I do not see enough repeat purchases yet to suggest a monthly list."

    lines = ["This month shopping ideas"]
    for i, item in enumerate(regular[:8], 1):
        store = item["stores"][0] if item["stores"] else "your usual store"
        lines.append(f"{i}. {compact_text(item['name'], 28)}")
        lines.append(f"   target {money(item['low'])} | store {compact_text(store, 22)}")

    lines.append("")
    lines.append("Tip: check the items with the biggest price range first before buying.")
    return "\n".join(lines)


def cheapest_items_answer(receipts: list[dict], item_events: list[dict] | None = None) -> str:
    events = []
    source_events = item_events if item_events else build_item_events(receipts)
    for event in source_events:
        price = _safe_float(event.get("line_price"))
        name = str(event.get("item_original") or "")
        if price <= 0:
            continue
        if name.upper().startswith("DISCOUNT") or "discount" in name.lower():
            continue
        events.append({**event, "line_price": price})

    if not events:
        return "I could not find any positive item prices in your receipts yet."

    events.sort(key=lambda event: (event["line_price"], event.get("date") or ""))
    cheapest = events[0]
    lines = [
        f"Cheapest found: {compact_text(cheapest['item_original'], 32)}",
        metric_line("Price", money(cheapest["line_price"])),
        metric_line("Store", compact_text(cheapest["store"], 28)),
        metric_line("Date", cheapest.get("date") or "unknown"),
        "",
        "Lowest priced items:",
    ]

    lines.extend(
        ranked_money_rows(
            [(event["item_original"], event["line_price"], f"{compact_text(event['store'], 24)} | {event.get('date') or 'unknown date'}") for event in events[:5]]
        )
    )

    lines.append("")
    lines.append("Discounts and negative adjustments were ignored.")
    return "\n".join(lines)


def category_spending_answer(receipts: list[dict]) -> str:
    category_totals: dict[str, float] = {}
    category_counts: dict[str, int] = {}
    category_examples: dict[str, list[str]] = {}

    for receipt in receipts:
        category = receipt_category(receipt)
        total = _safe_float(receipt.get("total"))
        category_totals[category] = category_totals.get(category, 0) + total
        category_counts[category] = category_counts.get(category, 0) + 1
        category_examples.setdefault(category, [])
        store = receipt.get("store") or "Unknown store"
        if store not in category_examples[category]:
            category_examples[category].append(store)

    if not category_totals:
        return "I do not see enough receipts to categorize spending yet."

    grand_total = sum(category_totals.values())
    lines = ["Receipt categories"]
    for category, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (total / grand_total * 100) if grand_total else 0
        stores = ", ".join(category_examples.get(category, [])[:2])
        lines.append(f"- {compact_text(category, 24)}: {money(total)} ({pct:.0f}%)")
        if stores:
            lines.append(f"  {category_counts[category]} receipt(s) | {compact_text(stores, 36)}")
    return "\n".join(lines)


def tax_discount_refund_answer(receipts: list[dict]) -> str:
    subtotal = sum(_safe_float(r.get("subtotal")) for r in receipts)
    tax = sum(_safe_float(r.get("tax")) for r in receipts)
    discount = sum(_safe_float(r.get("discount")) for r in receipts)
    savings = sum(_safe_float(r.get("total_savings")) for r in receipts)
    total = sum(_safe_float(r.get("total")) for r in receipts)
    refund_lines = []

    for receipt in receipts:
        for item in receipt.get("items") or []:
            if not isinstance(item, dict):
                continue
            price = _safe_float(item.get("price"))
            name = str(item.get("name") or item.get("item") or "Unknown item")
            if price < 0 or item.get("is_return"):
                refund_lines.append((name, receipt.get("store") or "Unknown store", receipt.get("date") or "", price))

    lines = [
        "Receipt money breakdown",
        metric_line("Subtotal", money(subtotal)),
        metric_line("Tax", money(tax)),
        metric_line("Discounts", money(discount)),
        metric_line("Savings", money(savings)),
        metric_line("Total paid", money(total)),
    ]
    if refund_lines:
        lines.append("")
        lines.append("Returns/refunds found")
        for name, store, date, price in refund_lines[:6]:
            lines.append(f"- {name}: {money(price)} at {store} ({date or 'unknown date'})")
    else:
        lines.append("")
        lines.append("I did not find clear return/refund lines in the receipts available.")
    return "\n".join(lines)


def recent_receipts_answer(receipts: list[dict]) -> str:
    recent = sorted(receipts, key=lambda r: r.get("created_at") or r.get("date") or "", reverse=True)[:8]
    if not recent:
        return "I do not see any receipts yet."
    lines = ["Recent receipts"]
    for receipt in recent:
        date = receipt.get("date") or (receipt.get("created_at") or "")[:10] or "unknown date"
        lines.append(
            f"- {date}: {receipt.get('store') or 'Unknown store'} - {money(receipt.get('total'))} - {receipt_category(receipt)}"
        )
    return "\n".join(lines)


def store_frequency_answer(receipts: list[dict]) -> str:
    stores: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        store = receipt.get("store") or "Unknown store"
        stores.setdefault(store, {"count": 0, "total": 0.0, "last_date": ""})
        stores[store]["count"] += 1
        stores[store]["total"] += _safe_float(receipt.get("total"))
        date = receipt.get("date") or (receipt.get("created_at") or "")[:10]
        if date and date > stores[store]["last_date"]:
            stores[store]["last_date"] = date

    ranked = sorted(stores.items(), key=lambda x: (x[1]["count"], x[1]["total"]), reverse=True)
    if not ranked:
        return "I do not see store history yet."

    lines = ["Stores you visit most"]
    for store, data in ranked[:8]:
        avg = data["total"] / max(data["count"], 1)
        lines.append(f"{compact_text(store, 24):<24} {data['count']:>2} trip(s)")
        lines.append(f"   total {money(data['total'])} | avg {money(avg)} | last {data['last_date'] or 'unknown'}")
    return "\n".join(lines)


def price_memory_answer(user_id: str | None = None, guest_session_id: str | None = None) -> str:
    profiles = build_price_memory(user_id, guest_session_id)
    if not profiles:
        return "I do not have enough item history to build your Price Memory yet."

    lines = ["Price Memory"]
    for profile in profiles[:8]:
        lines.append(f"- {compact_text(profile['item_name'], 28)}")
        lines.append(
            f"  low {money(profile['lowest_price'])} | usual {money(profile['usual_price'])} | avoid {money(profile['avoid_above_price'])}"
        )
        lines.append(f"  best store {compact_text(profile.get('cheapest_store') or 'unknown', 28)}")
    return "\n".join(lines)


def market_comparison_overview_answer(item_events: list[dict]) -> str:
    opportunities = rank_price_opportunities(item_events, limit=5)
    lines = [
        "Market comparison needs a product",
        "I can compare live/current prices when you ask with a specific item or shelf price, like: `is $4.99 good for eggs?`",
    ]
    if opportunities:
        lines.append("")
        lines.append("From your receipts, check these first:")
        for item in opportunities[:3]:
            lines.append(
                f"- {compact_text(item['name'], 28)}"
            )
            lines.append(f"  range {money(item['low'])}-{money(item['high'])} | best {compact_text(item['cheapest_store'], 22)}")
    return "\n".join(lines)


def extract_current_price(message: str) -> float | None:
    """Extract a user-provided live/current price from a chat message."""
    if not message:
        return None
    text = str(message).lower()
    patterns = [
        r"(?:current|today|shelf|live|now|price|priced|costs?|at)\s*(?:price\s*)?(?:is|=|:)?\s*\$?\s*(\d+(?:\.\d{1,2})?)",
        r"\b(?:is|for)\s+(\d+(?:\.\d{1,2})?)\s+good\b",
        r"\b(\d+(?:\.\d{1,2})?)\s+good\b",
        r"\$\s*(\d+(?:\.\d{1,2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = _safe_float(match.group(1))
            if value > 0:
                return round(value, 2)
    return None


def live_price_decision(profile: dict, current_price: float) -> dict:
    good_deal = _safe_float(profile.get("good_deal_price"))
    avoid_above = _safe_float(profile.get("avoid_above_price"))
    usual = _safe_float(profile.get("usual_price"))
    lowest = _safe_float(profile.get("lowest_price"))
    highest = _safe_float(profile.get("highest_price"))

    if good_deal and current_price <= good_deal:
        verdict = "Buy"
        reason = f"The current price is at or below your good-deal price of {money(good_deal)}."
    elif avoid_above and current_price >= avoid_above:
        verdict = "Wait or compare"
        reason = f"The current price is above your avoid-above price of {money(avoid_above)}."
    elif usual and current_price <= usual:
        verdict = "Fair price"
        reason = f"The current price is near or below your usual paid price of {money(usual)}."
    else:
        verdict = "Compare first"
        reason = f"The current price is above your usual paid price of {money(usual)}."

    return {
        "verdict": verdict,
        "reason": reason,
        "delta_vs_lowest": round(current_price - lowest, 2) if lowest else None,
        "delta_vs_usual": round(current_price - usual, 2) if usual else None,
        "delta_vs_highest": round(current_price - highest, 2) if highest else None,
    }


def build_live_price_check(
    item_query: str,
    current_price: float | None = None,
    store: str | None = None,
    source_url: str | None = None,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    live_search: bool = False,
) -> dict:
    """Compare a current price evidence point against receipt-based Price Memory."""
    memory = search_price_memory(item_query, user_id, guest_session_id, limit=3)
    matches = memory.get("matches") or []
    market_info = None

    if live_search and not current_price:
        market = execute_search_market_prices({"item_name": item_query})
        market_info = market.get("market_info") or market.get("error")
        found_prices = [_safe_float(p) for p in re.findall(r"\$\s*(\d+(?:\.\d{1,2})?)", market_info or "")]
        found_prices = [p for p in found_prices if p > 0]
        if found_prices:
            current_price = round(min(found_prices), 2)

    if not matches:
        return {
            "success": False,
            "item_query": item_query,
            "current_price": current_price,
            "store": store,
            "source_url": source_url,
            "market_info": market_info,
            "message": "No matching receipt price memory found for this item.",
        }

    profile = matches[0]
    response = {
        "success": True,
        "item_query": item_query,
        "matched_item": profile.get("item_name"),
        "match_score": profile.get("match_score"),
        "current_price": round(_safe_float(current_price), 2) if current_price else None,
        "current_store": store,
        "source_url": source_url,
        "market_info": market_info,
        "receipt_memory": {
            "lowest_price": profile.get("lowest_price"),
            "highest_price": profile.get("highest_price"),
            "usual_price": profile.get("usual_price"),
            "good_deal_price": profile.get("good_deal_price"),
            "avoid_above_price": profile.get("avoid_above_price"),
            "cheapest_store": profile.get("cheapest_store"),
            "times_bought": profile.get("times_bought"),
            "product_size": profile.get("product_size"),
        },
        "recent_events": profile.get("recent_events") or [],
    }

    if current_price:
        response["decision"] = live_price_decision(profile, _safe_float(current_price))
    else:
        response["decision"] = {
            "verdict": "Need current price",
            "reason": "I found your receipt price memory, but need a current shelf/web price to compare.",
        }
    return response


def live_price_check_answer(
    message: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    force_live_search: bool = False,
) -> str | None:
    current_price = extract_current_price(message)
    item_tokens = token_set(extract_query_item(message))
    generic_tokens = {
        "market", "current", "live", "today", "compare", "comparison", "overpaid",
        "overpay", "realtime", "real", "shelf", "web",
    }
    if not item_tokens or item_tokens <= generic_tokens:
        if force_live_search:
            return "Market comparison needs a product. Ask with an item, like `current market price for eggs`."
        return None
    result = build_live_price_check(
        item_query=message,
        current_price=current_price,
        user_id=user_id,
        guest_session_id=guest_session_id,
        live_search=force_live_search,
    )
    if not result.get("success"):
        if force_live_search and result.get("market_info"):
            return f"I found live market info, but I could not match it to your receipt history yet.\n{result['market_info']}"
        return None

    memory = result["receipt_memory"]
    decision = result["decision"]
    lines = [f"{decision['verdict']}: {result['matched_item']}"]
    if result.get("current_price"):
        lines.append(f"Current price: {money(result['current_price'])}")
    lines.append(f"Your usual price: {money(memory.get('usual_price'))}")
    lines.append(f"Lowest paid: {money(memory.get('lowest_price'))} at {memory.get('cheapest_store') or 'unknown store'}")
    lines.append(f"Good deal: {money(memory.get('good_deal_price'))} or less")
    lines.append(f"Avoid above: {money(memory.get('avoid_above_price'))}")
    lines.append(decision["reason"])

    if result.get("market_info") and not result.get("current_price"):
        lines.append("")
        lines.append("Live market note:")
        lines.append(result["market_info"])
    return "\n".join(lines)


def price_check_answer(message: str, user_id: str | None = None, guest_session_id: str | None = None) -> str | None:
    live_answer = live_price_check_answer(message, user_id, guest_session_id)
    if live_answer and extract_current_price(message):
        return live_answer

    memory = search_price_memory(message, user_id, guest_session_id, limit=3)
    matches = memory.get("matches") or []
    if not matches:
        return None

    profile = matches[0]
    lines = [
        f"Price memory for {profile['item_name']}",
        f"- Usual price: {money(profile['usual_price'])}",
        f"- Lowest paid: {money(profile['lowest_price'])} at {profile.get('cheapest_store') or 'unknown store'}",
        f"- Highest paid: {money(profile['highest_price'])}",
        f"- Good deal: {money(profile['good_deal_price'])} or less",
        f"- Avoid above: {money(profile['avoid_above_price'])}",
    ]
    if profile.get("buy_frequency_days"):
        lines.append(f"- Buying rhythm: about every {profile['buy_frequency_days']} days")
    if profile.get("next_expected_date"):
        lines.append(f"- You may need it around: {profile['next_expected_date']}")
    if profile.get("price_range", 0) > 0:
        lines.append(f"Price swing: {money(profile['price_range'])}. Compare before buying.")
    return "\n".join(lines)


def graph_category_for_event(event: dict) -> str:
    tokens = token_set(event.get("item_original") or event.get("item_normalized") or "")
    if tokens & RAW_MEAT_TERMS or event_matches_semantic_family(event, "meat", None):
        return "meat"
    if event_matches_semantic_family(event, "vegetable", None) or tokens & {"onion", "carrot", "tomato", "okra", "cilantro", "chilli", "pepper"}:
        return "vegetables"
    if tokens & {"milk", "yogurt", "dahi", "cheese", "paneer", "cream"}:
        return "dairy"
    if tokens & {"rice", "atta", "flour", "noodles", "pasta", "dal", "lentil"}:
        return "pantry"
    if tokens & {"cake", "candy", "biscuit", "biscuits", "cookies", "icecream", "ice", "cream"}:
        return "snacks"
    return "other"


def build_graph_memory(item_events: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    item_store: dict[tuple[str, str], list[float]] = {}
    store_category: dict[tuple[str, str], dict[str, Any]] = {}
    receipt_items: dict[Any, list[dict]] = {}
    receipt_id_counts: dict[Any, int] = {}
    for event in item_events:
        receipt_id = event.get("receipt_id")
        if receipt_id is not None:
            receipt_id_counts[receipt_id] = receipt_id_counts.get(receipt_id, 0) + 1

    for event in item_events:
        item_key = normalize_text(event.get("item_original") or "")
        if not item_key:
            continue
        store = event.get("store") or "Unknown store"
        category = graph_category_for_event(event)
        price = price_memory_event_price(event)
        nodes.setdefault(item_key, {
            "item": event.get("item_original"),
            "category": category,
            "stores": set(),
            "receipts": set(),
            "events": [],
        })
        nodes[item_key]["stores"].add(store)
        nodes[item_key]["receipts"].add(event.get("receipt_id"))
        nodes[item_key]["events"].append(event)
        if price > 0:
            item_store.setdefault((item_key, store), []).append(price)
            bucket = store_category.setdefault((store, category), {"store": store, "category": category, "count": 0, "total": 0.0, "items": set()})
            bucket["count"] += 1
            bucket["total"] += price
            bucket["items"].add(event.get("item_original"))
        receipt_id = event.get("receipt_id")
        trip_key = receipt_id if receipt_id_counts.get(receipt_id, 0) > 1 else f"{event.get('store') or ''}|{event.get('date') or ''}"
        receipt_items.setdefault(trip_key, []).append(event)

    co_bought: dict[tuple[str, str], dict[str, Any]] = {}
    for events in receipt_items.values():
        unique = {}
        for event in events:
            key = normalize_text(event.get("item_original") or "")
            if key:
                unique[key] = event
        keys = sorted(unique)
        for index, left in enumerate(keys):
            for right in keys[index + 1:]:
                pair = (left, right)
                co_bought.setdefault(pair, {
                    "left": unique[left].get("item_original"),
                    "right": unique[right].get("item_original"),
                    "count": 0,
                    "receipt_ids": set(),
                })
                co_bought[pair]["count"] += 1
                co_bought[pair]["receipt_ids"].add(unique[left].get("receipt_id"))

    return {
        "items": nodes,
        "item_store_prices": item_store,
        "store_categories": store_category,
        "co_bought": co_bought,
    }


def graph_memory_answer(message: str, item_events: list[dict]) -> str:
    graph = build_graph_memory(item_events)
    m = normalize_text(message)
    if any(term in m for term in ["together", "combo", "combination", "usually buy with", "bought with"]):
        pairs = sorted(graph["co_bought"].values(), key=lambda row: row["count"], reverse=True)
        if not pairs:
            return "I do not have enough same-receipt item relationships yet."
        lines = ["Items commonly bought together"]
        for pair in pairs[:5]:
            lines.append(f"- {compact_text(pair['left'], 24)} + {compact_text(pair['right'], 24)} ({pair['count']} receipt{'s' if pair['count'] != 1 else ''})")
        return "\n".join(lines)

    if ("category" in m or "categories" in m) and ("store" in m or "from" in m):
        store_hint = ""
        for store, _category in graph["store_categories"]:
            if normalize_text(store) in m:
                store_hint = store
                break
        rows = [
            row for row in graph["store_categories"].values()
            if not store_hint or row["store"] == store_hint
        ]
        rows.sort(key=lambda row: (row["count"], row["total"]), reverse=True)
        if not rows:
            return "I do not see enough store-category relationships yet."
        title = f"Categories from {store_hint}" if store_hint else "Store category relationships"
        lines = [title]
        for row in rows[:6]:
            examples = ", ".join(sorted(row["items"])[:3])
            lines.append(f"- {row['category'].title()} at {compact_text(row['store'], 24)}: {row['count']} items, {money(row['total'])}")
            if examples:
                lines.append(f"  examples {compact_text(examples, 42)}")
        return "\n".join(lines)

    rows = sorted(graph["store_categories"].values(), key=lambda row: (row["count"], row["total"]), reverse=True)
    lines = ["Graph memory"]
    for row in rows[:5]:
        lines.append(f"- {row['category'].title()} -> {compact_text(row['store'], 24)} ({row['count']} item links)")
    return "\n".join(lines)


def receipt_action_answer(
    action: str,
    message: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> str | None:
    receipts = fetch_owner_receipts(user_id, guest_session_id, limit=300)
    if not receipts:
        return "I do not see any receipts yet."
    item_events = fetch_owner_item_events(user_id, guest_session_id)
    if not item_events:
        item_events = build_item_events(receipts)

    store_totals: dict[str, float] = {}
    store_counts: dict[str, int] = {}
    for receipt in receipts:
        store = receipt.get("store") or "Unknown store"
        store_totals[store] = store_totals.get(store, 0.0) + _safe_float(receipt.get("total"))
        store_counts[store] = store_counts.get(store, 0) + 1

    if action == "global_cheapest":
        return cheapest_items_answer(receipts, item_events)
    if action == "price_memory":
        return price_memory_answer(user_id, guest_session_id)
    if action == "shopping_plan":
        return next_shopping_plan_answer(user_id, guest_session_id)
    if action == "graph_memory":
        return graph_memory_answer(message, item_events)
    if action == "category_spending":
        return category_spending_answer(receipts)
    if action == "weekly_spending":
        return weekly_expense_answer(receipts, message)
    if action == "monthly_spending":
        return monthly_expense_answer(receipts, message)
    if action == "tax_discount":
        return tax_discount_refund_answer(receipts)
    if action == "recent_receipts":
        return recent_receipts_answer(receipts)
    if action == "store_frequency":
        return store_frequency_answer(receipts)
    if action == "store_spend":
        ranked = sorted(store_totals.items(), key=lambda x: x[1], reverse=True)
        if not ranked:
            return "I do not see store totals yet."
        top_store, top_total = ranked[0]
        lines = [f"You spent the most at {top_store}: {money(top_total)}."]
        lines.append("")
        lines.append("Top stores by spend")
        for store, total in ranked[:5]:
            avg = total / max(store_counts[store], 1)
            lines.append(f"- {compact_text(store, 28)}: {money(total)} across {store_counts[store]} trips, avg {money(avg)}")
        return "\n".join(lines)
    if action == "store_breakdown":
        ranked = sorted(store_totals.items(), key=lambda x: x[1], reverse=True)
        lines = ["Store breakdown"]
        for store, total in ranked[:5]:
            avg = total / max(store_counts[store], 1)
            lines.append(f"- {store}: {money(total)} across {store_counts[store]} trips, avg {money(avg)}")
        return "\n".join(lines)
    if action == "item_price_trends":
        regular = regular_item_stats_from_events(item_events)
        if not regular:
            return "I do not see enough repeat purchases yet to show price trends."
        lines = ["Price trends for items you bought more than once"]
        for item in sorted(regular, key=lambda x: x["spread"], reverse=True)[:5]:
            store_text = ", ".join(item["stores"][:2])
            lines.append(f"- {compact_text(item['name'], 28)}")
            lines.append(f"  {item['count']} buys | low {money(item['low'])} | high {money(item['high'])} | swing {money(item['spread'])}")
            lines.append(f"  stores {compact_text(store_text, 34)}")
        return "\n".join(lines)
    if action == "best_deals":
        opportunities = rank_price_opportunities(item_events, limit=5)
        if not opportunities:
            return (
                "I do not see enough repeat prices yet to rank price swings.\n\n"
                "Once the same item appears at different prices, I can show the biggest swings and best stores."
            )
        lines = ["Best recent deal opportunities"]
        for item in opportunities[:5]:
            lines.append(f"- {compact_text(item['name'], 28)}")
            lines.append(f"  low {money(item['low'])} | high {money(item['high'])} | swing {money(item['spread'])}")
            lines.append(f"  best store {compact_text(item['cheapest_store'], 28)}")
        return "\n".join(lines)
    if action == "save_money":
        opportunities = rank_price_opportunities(item_events, limit=2)
        top_store = max(store_totals, key=store_totals.get)
        avg_top = store_totals[top_store] / max(store_counts[top_store], 1)
        lines = ["Top 3 ways to save"]
        if opportunities:
            first = opportunities[0]
            lines.append(f"1. Compare {compact_text(first['name'], 26)}")
            lines.append(f"   swing {money(first['spread'])} | best {compact_text(first['cheapest_store'], 24)}")
        else:
            lines.append("1. Compare repeat items before checkout. Those are where your price memory becomes most useful.")
        lines.append(f"2. Watch {compact_text(top_store, 26)}")
        lines.append(f"   {money(store_totals[top_store])} total | {store_counts[top_store]} trips | avg {money(avg_top)}")
        if len(opportunities) > 1:
            second = opportunities[1]
            lines.append(f"3. Set target for {compact_text(second['name'], 22)}")
            lines.append(f"   buy near {money(second['low'])} | avoid near {money(second['high'])}")
        else:
            lines.append("3. Use store-brand or coupon checks on your most repeated items.")
        return "\n".join(lines)
    if action == "market_comparison":
        return market_comparison_overview_answer(item_events)
    if action == "live_price_check":
        return live_price_check_answer(message, user_id, guest_session_id, force_live_search=True)
    if action == "price_check":
        answer = price_check_answer(message, user_id, guest_session_id)
        if answer:
            return answer
        return (
            "Tell me the item and current price to judge it.\n"
            "Example: `is $4.99 good for eggs?`\n\n"
            + price_memory_answer(user_id, guest_session_id)
        )
    if action == "open_analysis":
        flexible_answer = flexible_receipt_memory_answer(message, receipts, item_events)
        if flexible_answer:
            return flexible_answer
        return smart_spending_overview_answer(receipts, item_events)
    return None


def deterministic_overview_answer(message: str, user_id: str | None = None, guest_session_id: str | None = None) -> str | None:
    action = classify_receipt_action(message)
    if action:
        locked_answer = receipt_action_answer(action, message, user_id, guest_session_id)
        if locked_answer:
            return locked_answer

    receipts = fetch_owner_receipts(user_id, guest_session_id, limit=300)
    if not receipts:
        return "I do not see any receipts yet."
    item_events = fetch_owner_item_events(user_id, guest_session_id)
    if not item_events:
        item_events = build_item_events(receipts)

    m = normalize_text(message)
    total_spent = sum(_safe_float(r.get("total")) for r in receipts)
    total_saved = sum(_safe_float(r.get("total_savings")) for r in receipts)
    store_totals: dict[str, float] = {}
    store_counts: dict[str, int] = {}
    for receipt in receipts:
        store = receipt.get("store") or "Unknown store"
        store_totals[store] = store_totals.get(store, 0) + _safe_float(receipt.get("total"))
        store_counts[store] = store_counts.get(store, 0) + 1

    if looks_like_global_price_question(message):
        return cheapest_items_answer(receipts, item_events)

    if "price memory" in m or "price dna" in m:
        return price_memory_answer(user_id, guest_session_id)

    if (
        "next shopping" in m
        or "shopping plan" in m
        or "shopping list" in m
        or "what should i buy next" in m
        or "what should i buy this month" in m
        or "items to purchase" in m
        or "purchase this month" in m
        or "this month items" in m
    ):
        return next_shopping_plan_answer(user_id, guest_session_id)

    if (
        "live price" in m
        or "current price" in m
        or "real time price" in m
        or "realtime price" in m
        or "market price" in m
        or "market prices" in m
        or "current market" in m
        or "today price" in m
        or "overpaid" in m
        or "over pay" in m
        or "overpay" in m
    ):
        if (
            not extract_current_price(message)
            and (
                "market price comparison" in m
                or "compare my prices" in m
                or "where i overpaid" in m
                or "overpaid" in m
                or "over pay" in m
                or "overpay" in m
            )
        ):
            return market_comparison_overview_answer(item_events)
        answer = live_price_check_answer(message, user_id, guest_session_id, force_live_search=True)
        if answer:
            return answer

    if (
        "good price" in m
        or "is this a good price" in m
        or "avoid price" in m
        or "avoid above" in m
        or "should i buy" in m
        or "buy now" in m
        or "wait to buy" in m
    ):
        answer = price_check_answer(message, user_id, guest_session_id)
        if answer:
            return answer
        return (
            "Tell me the item and current price to judge it.\n"
            "Example: `is $4.99 good for eggs?`\n\n"
            + price_memory_answer(user_id, guest_session_id)
        )

    if (
        "category" in m
        or "categories" in m
        or "categorize" in m
        or "food receipts" in m
        or "bank receipts" in m
        or "hospital receipts" in m
        or "medical receipts" in m
        or "gardening receipts" in m
        or "garden receipts" in m
    ):
        return category_spending_answer(receipts)

    if (
        "tax" in m
        or "taxes" in m
        or "refund" in m
        or "refunds" in m
        or "return" in m
        or "returns" in m
        or "discount" in m
        or "discounts" in m
    ):
        return tax_discount_refund_answer(receipts)

    if "recent receipts" in m or "latest receipts" in m or "last receipts" in m:
        return recent_receipts_answer(receipts)

    if (
        "store visits" in m
        or "visit most" in m
        or "where do i shop" in m
        or "where i shop" in m
        or "frequent store" in m
        or "frequent stores" in m
    ):
        return store_frequency_answer(receipts)

    if (
        "spend the most" in m
        or "spent the most" in m
        or "spend most" in m
        or "spent most" in m
        or "store did i spend" in m
        or "where did i spend" in m
        or "which store did i spend" in m
    ):
        ranked = sorted(store_totals.items(), key=lambda x: x[1], reverse=True)
        if not ranked:
            return "I do not see store totals yet."
        top_store, top_total = ranked[0]
        lines = [f"You spent the most at {top_store}: {money(top_total)}."]
        lines.append("")
        lines.append("Top stores by spend")
        for store, total in ranked[:5]:
            avg = total / max(store_counts[store], 1)
            lines.append(f"- {compact_text(store, 28)}: {money(total)} across {store_counts[store]} trips, avg {money(avg)}")
        return "\n".join(lines)

    if (
        "items to purchase" in m
        or "what should i buy" in m
        or "shopping suggestions" in m
        or "purchase this month" in m
    ):
        return purchase_suggestions_answer(receipts, item_events)

    if "price trend" in m or "price trends" in m or "buy regularly" in m:
        regular = regular_item_stats_from_events(item_events)
        if not regular:
            return "I do not see enough repeat purchases yet to show price trends."

        lines = ["Price trends for items you bought more than once:"]
        for item in sorted(regular, key=lambda x: x["spread"], reverse=True)[:5]:
            store_text = ", ".join(item["stores"][:2])
            lines.append(f"- {compact_text(item['name'], 28)}")
            lines.append(f"  {item['count']} buys | low {money(item['low'])} | high {money(item['high'])} | swing {money(item['spread'])}")
            lines.append(f"  stores {compact_text(store_text, 34)}")
        return "\n".join(lines)

    if "best deal" in m or "best deals" in m or "deals recently" in m:
        opportunities = rank_price_opportunities(item_events, limit=5)
        if not opportunities:
            return cheapest_items_answer(receipts, item_events)
        lines = ["Best recent deal opportunities"]
        for item in opportunities[:5]:
            lines.append(f"- {compact_text(item['name'], 28)}")
            lines.append(f"  low {money(item['low'])} | high {money(item['high'])} | swing {money(item['spread'])}")
            lines.append(f"  best store {compact_text(item['cheapest_store'], 28)}")
        return "\n".join(lines)

    if "save money" in m or "top 3 ways" in m or "saving" in m:
        opportunities = rank_price_opportunities(item_events, limit=2)
        top_store = max(store_totals, key=store_totals.get)
        avg_top = store_totals[top_store] / max(store_counts[top_store], 1)

        lines = ["Top 3 ways to save"]
        if opportunities:
            first = opportunities[0]
            lines.append(f"1. Compare {compact_text(first['name'], 26)}")
            lines.append(f"   swing {money(first['spread'])} | best {compact_text(first['cheapest_store'], 24)}")
        else:
            lines.append("1. Compare repeat items before checkout. Those are where your price memory becomes most useful.")

        lines.append(f"2. Watch {compact_text(top_store, 26)}")
        lines.append(f"   {money(store_totals[top_store])} total | {store_counts[top_store]} trips | avg {money(avg_top)}")
        if len(opportunities) > 1:
            second = opportunities[1]
            lines.append(f"3. Set target for {compact_text(second['name'], 22)}")
            lines.append(f"   buy near {money(second['low'])} | avoid near {money(second['high'])}")
        elif total_saved > 0:
            lines.append(f"3. Keep using discounts/coupons. Your receipts already show {money(total_saved)} saved.")
        else:
            lines.append("3. Use store-brand or coupon checks on your most repeated items.")
        return "\n".join(lines)

    if looks_like_weekly_question(message):
        return weekly_expense_answer(receipts, message)

    if (
        "monthly" in m
        or "monthly spending report" in m
        or "this month" in m
        or "spent analysis" in m
        or "expense analysis" in m
        or "graph" in m
        or "chart" in m
        or "table" in m
    ):
        return monthly_expense_answer(receipts, message)

    if "best store" in m or "best value" in m:
        ranked = sorted(store_totals.items(), key=lambda x: x[1], reverse=True)
        lines = ["Store breakdown:"]
        for store, total in ranked[:5]:
            avg = total / max(store_counts[store], 1)
            lines.append(f"- {store}: {money(total)} across {store_counts[store]} trips, avg {money(avg)}")
        return "\n".join(lines)

    if "monthly" in m:
        months: dict[str, float] = {}
        for receipt in receipts:
            month = (receipt.get("date") or receipt.get("created_at") or "Unknown")[:7]
            months[month] = months.get(month, 0) + _safe_float(receipt.get("total"))
        lines = ["Monthly spending:"]
        for month, total in sorted(months.items(), reverse=True)[:6]:
            lines.append(f"- {month}: {money(total)}")
        return "\n".join(lines)

    return smart_spending_overview_answer(receipts, item_events)


def deterministic_overview_answer_card(message: str, user_id: str | None = None, guest_session_id: str | None = None) -> dict | None:
    """Optional structured evidence card for deterministic overview answers."""
    m = normalize_text(message)
    if (
        "next shopping" in m
        or "shopping plan" in m
        or "shopping list" in m
        or "what should i buy next" in m
        or "what should i buy this month" in m
        or "items to purchase" in m
        or "purchase this month" in m
        or "this month items" in m
        or "what should i buy" in m
    ):
        return shopping_plan_answer_card(user_id, guest_session_id)

    if "price memory" in m or "price dna" in m or "avoid above" in m:
        return price_memory_answer_card(user_id, guest_session_id)

    return None


def execute_query_receipts(params: dict, user_id: str = None, guest_session_id: str = None) -> dict:
    try:
        query_type = params.get("query_type", "all")
        limit = params.get("limit", 20)
        receipts = fetch_owner_receipts(user_id, guest_session_id, limit=max(limit, 100))

        if query_type == "by_store" and params.get("store_name"):
            store_term = normalize_text(params["store_name"])
            receipts = [r for r in receipts if store_term in normalize_text(r.get("store", ""))]

        if query_type == "by_item" and params.get("item_name"):
            return retrieve_item_events(params["item_name"], user_id, guest_session_id, limit=limit)

        if query_type == "summary":
            total_spent = sum(_safe_float(r.get("total"), 0) for r in receipts)
            total_saved = sum(_safe_float(r.get("total_savings"), 0) for r in receipts)
            stores = {}
            for r in receipts:
                s = r.get("store", "Unknown")
                stores[s] = stores.get(s, 0) + _safe_float(r.get("total"), 0)
            return {
                "total_receipts": len(receipts),
                "total_spent": round(total_spent, 2),
                "total_saved": round(total_saved, 2),
                "top_stores": sorted(stores.items(), key=lambda x: -x[1])[:5],
            }

        return {"receipts": receipts[:limit], "count": len(receipts[:limit])}
    except Exception as e:
        return {"error": str(e)}


def execute_get_price_history(params: dict, user_id: str = None, guest_session_id: str = None) -> dict:
    return retrieve_item_events(params.get("item_name", ""), user_id, guest_session_id, limit=params.get("limit", 25))


def execute_analyze_spending(params: dict, user_id: str = None, guest_session_id: str = None) -> dict:
    try:
        analysis_type = params.get("analysis_type", "overview")
        receipts = fetch_owner_receipts(user_id, guest_session_id)
        if not receipts:
            return {"message": "No receipts found."}

        if analysis_type == "by_store":
            stores = {}
            for r in receipts:
                s = r.get("store", "Unknown")
                stores.setdefault(s, {"total": 0, "visits": 0, "saved": 0})
                stores[s]["total"] += _safe_float(r.get("total"), 0)
                stores[s]["visits"] += 1
                stores[s]["saved"] += _safe_float(r.get("total_savings"), 0)
            return {"by_store": [{"store": s, "total": round(d["total"], 2), "visits": d["visits"], "saved": round(d["saved"], 2)} for s, d in sorted(stores.items(), key=lambda x: -x[1]["total"])]}

        if analysis_type == "top_items":
            events = fetch_owner_item_events(user_id, guest_session_id) or build_item_events(receipts)
            counts = {}
            for e in events:
                key = e["item_normalized"]
                if not key:
                    continue
                counts.setdefault(key, {"item": e["item_original"], "times_bought": 0, "total_spent": 0})
                counts[key]["times_bought"] += 1
                counts[key]["total_spent"] += _safe_float(e.get("line_price"), 0)
            return {"top_items": sorted(counts.values(), key=lambda x: (-x["times_bought"], -x["total_spent"]))[:10]}

        if analysis_type == "savings":
            total_saved = sum(_safe_float(r.get("total_savings"), 0) for r in receipts)
            return {"total_saved": round(total_saved, 2), "receipts_with_savings": sum(1 for r in receipts if _safe_float(r.get("total_savings"), 0) > 0)}

        if analysis_type == "by_month":
            months = {}
            for r in receipts:
                month = (r.get("created_at") or r.get("date") or "")[:7]
                if month:
                    months[month] = months.get(month, 0) + _safe_float(r.get("total"), 0)
            return {"by_month": [{"month": m, "total": round(t, 2)} for m, t in sorted(months.items())]}

        if analysis_type == "by_category":
            categories = {}
            for r in receipts:
                category = receipt_category(r)
                categories.setdefault(category, {"total": 0, "receipts": 0})
                categories[category]["total"] += _safe_float(r.get("total"), 0)
                categories[category]["receipts"] += 1
            return {"by_category": [{"category": c, "total": round(d["total"], 2), "receipts": d["receipts"]} for c, d in sorted(categories.items(), key=lambda x: -x[1]["total"])]}

        if analysis_type == "tax_discount":
            return {
                "subtotal": round(sum(_safe_float(r.get("subtotal"), 0) for r in receipts), 2),
                "tax": round(sum(_safe_float(r.get("tax"), 0) for r in receipts), 2),
                "discount": round(sum(_safe_float(r.get("discount"), 0) for r in receipts), 2),
                "total_savings": round(sum(_safe_float(r.get("total_savings"), 0) for r in receipts), 2),
                "total_paid": round(sum(_safe_float(r.get("total"), 0) for r in receipts), 2),
            }

        if analysis_type == "recent_receipts":
            return {"recent_receipts": [
                {
                    "store": r.get("store"),
                    "date": r.get("date") or (r.get("created_at") or "")[:10],
                    "total": r.get("total"),
                    "category": receipt_category(r),
                }
                for r in sorted(receipts, key=lambda row: row.get("created_at") or row.get("date") or "", reverse=True)[:10]
            ]}

        if analysis_type == "store_frequency":
            stores = {}
            for r in receipts:
                store = r.get("store", "Unknown")
                stores.setdefault(store, {"visits": 0, "total": 0})
                stores[store]["visits"] += 1
                stores[store]["total"] += _safe_float(r.get("total"), 0)
            return {"store_frequency": [{"store": s, "visits": d["visits"], "total": round(d["total"], 2)} for s, d in sorted(stores.items(), key=lambda x: (-x[1]["visits"], -x[1]["total"]))]}

        total_spent = sum(_safe_float(r.get("total"), 0) for r in receipts)
        total_saved = sum(_safe_float(r.get("total_savings"), 0) for r in receipts)
        return {"total_receipts": len(receipts), "total_spent": round(total_spent, 2), "total_saved": round(total_saved, 2), "avg_per_trip": round(total_spent / len(receipts), 2) if receipts else 0}
    except Exception as e:
        return {"error": str(e)}


def execute_find_best_deals(params: dict, user_id: str = None, guest_session_id: str = None) -> dict:
    try:
        recommendations = []
        for item_name in params.get("items", []):
            rag = retrieve_item_events(item_name, user_id, guest_session_id, limit=50)
            events = rag.get("events", [])
            if not events:
                recommendations.append({"item": item_name, "found": False, "message": "No purchase history"})
                continue
            by_store = {}
            for e in events:
                if e.get("line_price") is None:
                    continue
                by_store.setdefault(e["store"], []).append(e["line_price"])
            avgs = {s: round(sum(v) / len(v), 2) for s, v in by_store.items() if v}
            best = min(avgs, key=avgs.get) if avgs else None
            recommendations.append({"item": item_name, "found": bool(best), "best_store": best, "best_price": avgs.get(best) if best else None, "all_stores": avgs, "events_used": len(events)})
        return {"recommendations": recommendations}
    except Exception as e:
        return {"error": str(e)}


def execute_search_market_prices(params: dict) -> dict:
    try:
        item_name = params.get("item_name", "")
        response = claude_client.messages.create(
            model=SONNET_MODEL, max_tokens=400,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
            messages=[{"role": "user", "content": f"Current average store price for {item_name} in USA 2026? Give specific prices from major stores. Brief."}]
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text") and b.text)
        return {"item": item_name, "market_info": text.strip() or f"No current prices found for {item_name}"}
    except Exception as e:
        return {"error": str(e)}


def execute_live_price_check(params: dict, user_id: str = None, guest_session_id: str = None) -> dict:
    try:
        return build_live_price_check(
            item_query=params.get("item_name", ""),
            current_price=_safe_float(params.get("current_price")) if params.get("current_price") is not None else None,
            store=params.get("store"),
            source_url=params.get("source_url"),
            user_id=user_id,
            guest_session_id=guest_session_id,
            live_search=bool(params.get("live_search")),
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


def compact_tool_result(result: Any) -> Any:
    if isinstance(result, dict) and "receipts" in result:
        compact_receipts = []
        for receipt in (result.get("receipts") or [])[:10]:
            compact_receipts.append({
                "store": receipt.get("store"),
                "date": receipt.get("date"),
                "total": receipt.get("total"),
                "total_savings": receipt.get("total_savings"),
                "items": [
                    {
                        "name": item.get("name"),
                        "price": item.get("price"),
                        "quantity": item.get("quantity", 1),
                        "unit": item.get("unit", "each"),
                    }
                    for item in (receipt.get("items") or [])[:8]
                    if isinstance(item, dict)
                ],
            })
        return {**result, "receipts": compact_receipts}

    if isinstance(result, dict) and "events" in result:
        return {**result, "events": (result.get("events") or [])[:12]}

    return result


def evidence_rows_from_events(events: list[dict], limit: int = 5) -> list[dict]:
    rows = []
    for event in dedupe_item_events(events or [])[:limit]:
        rows.append({
            "item": event.get("item_original"),
            "store": event.get("store") or "Unknown store",
            "date": event.get("date") or "unknown date",
            "price": event_price_text(event),
            "receipt_id": event.get("receipt_id"),
            "line_index": event.get("line_index"),
            "openable": bool(event.get("receipt_id")),
            "match_score": event.get("adjusted_match_score") or event.get("match_score"),
            "match_confidence": event.get("match_confidence") or event.get("confidence"),
            "multimodal": multimodal_source_evidence(event),
        })
    return rows


def evidence_rows_from_card(card: dict | None, limit: int = 5) -> list[dict]:
    if not card:
        return []
    if card.get("rows"):
        rows = []
        for row in (card.get("rows") or [])[:limit]:
            rows.append({
                "item": row.get("item") or row.get("label") or row.get("title"),
                "store": row.get("store"),
                "date": row.get("date"),
                "price": row.get("price"),
                "receipt_id": row.get("receipt_id"),
                "line_index": row.get("line_index"),
                "openable": bool(row.get("receipt_id")),
                "multimodal": row.get("multimodal_evidence") or row.get("multimodal"),
            })
        return rows
    if card.get("receipt_id"):
        return [{
            "item": card.get("item"),
            "store": card.get("store"),
            "date": card.get("date"),
            "price": card.get("price"),
            "receipt_id": card.get("receipt_id"),
            "line_index": card.get("line_index"),
            "openable": True,
            "multimodal": card.get("multimodal_evidence"),
        }]
    return []


def should_use_receipt_intelligence_v2(query: Any, message: str, understanding: dict) -> bool:
    """Use the lightweight deterministic layer only for safe lookup-style questions."""
    normalized = correct_query_words(normalize_text(message))
    tokens = set(normalized.split())

    if query.intent == receipt_intelligence.INTENT_UNCLEAR:
        return False

    advanced_action = classify_receipt_action(message)
    if advanced_action:
        return False
    if looks_like_overview_question(message) or looks_like_global_price_question(message):
        return False
    if looks_like_shopping_list_price_request(message):
        return False
    if looks_like_general_advice_question(message):
        return False

    if understanding.get("intent") in {
        "category_price",
        "global_cheapest",
        "monthly_report",
        "shopping_plan",
        "store_compare",
        "spending_summary",
    }:
        return False

    if query.intent == receipt_intelligence.INTENT_SPENDING_SUMMARY:
        return False

    if query.intent == receipt_intelligence.INTENT_ITEM_LOOKUP:
        advanced_item_terms = {
            "history", "trend", "trends", "list", "show", "all", "evidence",
            "receipt", "receipts", "them", "those", "same", "good", "avoid",
            "above", "now", "current", "market", "compare", "comparison",
            "find", "cheap", "cheapest", "cheaper", "best", "price", "prices",
        }
        if tokens & advanced_item_terms:
            return False
        if tokens & BROAD_CATEGORY_QUERY_TERMS:
            return False
        return True

    if query.intent == receipt_intelligence.INTENT_GENERAL:
        return True

    return query.intent in {
        receipt_intelligence.INTENT_STORE_LOOKUP,
        receipt_intelligence.INTENT_MISSING_ITEM_LOOKUP,
    }


def run_agent(message: str, conversation_history: list, user_id: str = None, guest_session_id: str = None) -> dict:
    """Run the ReceiptAI agent. Receipt data questions are answered with deterministic RAG first."""
    tools_used: list[str] = []
    _RECEIPT_CACHE.clear()
    _ITEM_EVENT_CACHE.clear()
    message = resolve_followup_message(message, conversation_history)
    original_message = message
    understanding = understand_user_query(message, conversation_history)
    message = canonicalize_message_with_understanding(message, understanding)
    if understanding.get("intent") == "help" or (
        understanding.get("is_receipt_question") is not True and looks_like_smalltalk_or_help(message)
    ):
        help_text = normalize_text(message)
        if any(term in help_text.split() for term in ["thanks", "thank", "thx"]):
            response = "You're welcome. Ask me anytime about prices, stores, spending, or what to buy next."
        else:
            response = (
                "I can help with your receipt memory: cheapest stores, item price history, "
                "weekly or monthly spending, category totals, savings ideas, and before-you-buy checks."
            )
        return {
            "response": response,
            "tools_used": [],
            "thinking": "",
        }

    deterministic_general = receipt_intelligence.parse_receipt_query(original_message)
    if (
        deterministic_general.intent == receipt_intelligence.INTENT_GENERAL
        and should_use_receipt_intelligence_v2(deterministic_general, original_message, understanding)
    ):
        general_context = retrieve_general_context(original_message)
        try:
            general_response = general_advice_answer(original_message, general_context)
        except TypeError:
            general_response = general_advice_answer(original_message)
        return {
            "response": general_response,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                agent_mode="general",
                intent="general_advice",
                retrieval="general_context_rag",
                original_message=original_message,
                normalized_query=original_message,
                evidence=general_context,
                strict=False,
                note="General Mode: deterministic parser classified this as non-receipt advice before receipt RAG.",
            ),
        }

    understood_item = normalize_text(str(understanding.get("item_query") or ""))
    raw_message_norm = normalize_text(original_message)
    understood_tokens = token_set(understood_item)
    def _rough_singular(token: str) -> str:
        if len(token) > 4 and token.endswith("ies"):
            return token[:-3] + "y"
        if len(token) > 4 and token.endswith("oes"):
            return token[:-2]
        if len(token) > 3 and token.endswith("es"):
            return token[:-2]
        if len(token) > 3 and token.endswith("s"):
            return token[:-1]
        return token
    raw_tokens = {
        _rough_singular(token)
        for token in raw_message_norm.split()
        if token and token not in STOP_WORDS
    }
    skip_v2_for_canonical_item = bool(
        understood_item
        and understanding.get("intent") in {"item_price", "item_count"}
        and understood_tokens
        and not (understood_tokens & raw_tokens)
    )
    v2_should_answer = should_use_receipt_intelligence_v2(deterministic_general, original_message, understanding)
    v2_lookup_error = False
    try:
        receipts_for_v2 = fetch_owner_receipts(user_id, guest_session_id, limit=300)
        events_for_v2 = fetch_owner_item_events(user_id, guest_session_id, limit=1500)
        if not events_for_v2:
            events_for_v2 = build_item_events(receipts_for_v2)
        if (
            not skip_v2_for_canonical_item
            and v2_should_answer
        ):
            deterministic_v2 = receipt_intelligence.answer_receipt_query(
                original_message,
                receipts_for_v2,
                events_for_v2,
            )
            if deterministic_v2:
                return finalize_agent_result(deterministic_v2, original_message)
    except Exception as e:
        v2_lookup_error = True
        print(f"[receipt_intelligence_v2] fallback to legacy agent: {e}")

    if v2_should_answer and v2_lookup_error:
        return finalize_agent_result({
            "response": "I had trouble reading your receipt data for that question. Please try again in a moment.",
            "answer_card": None,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                intent="receipt_lookup_error",
                retrieval="deterministic_receipt_router",
                original_message=original_message,
                normalized_query=original_message,
                evidence=[],
                strict=True,
                note="Receipt-intent question was not allowed to fall back to general advice after a receipt data read error.",
            ),
        }, original_message)

    if (
        understanding.get("intent") == "general_advice"
        or understanding.get("is_receipt_question") is False
        or looks_like_general_advice_question(message)
    ):
        general_context = retrieve_general_context(original_message)
        try:
            general_response = general_advice_answer(message, general_context)
        except TypeError:
            general_response = general_advice_answer(message)
        return {
            "response": general_response,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                agent_mode="general",
                intent="general_advice",
                retrieval="general_context_rag",
                original_message=original_message,
                normalized_query=message,
                evidence=general_context,
                strict=False,
                note="General Mode: used curated non-receipt context RAG; no receipt retrieval or receipt price claims.",
            ),
        }

    current_learned_families = learned_alias_families([], message)
    if current_learned_families:
        save_owner_alias_families(current_learned_families, user_id, guest_session_id)
    extra_families = (
        fetch_owner_alias_families(user_id, guest_session_id)
        + learned_alias_families(conversation_history, message)
    )

    # ── Multi-item intent split ──
    # If the classifier returned 2+ distinct items (e.g. "cinnamon stick saffron turmeric cardamom"),
    # rewrite the message so the shopping-list path picks it up correctly instead of treating
    # all words as one combined item name.
    classifier_items = [i for i in (understanding.get("items") or []) if i]
    if len(classifier_items) >= 2 and not looks_like_shopping_list_price_request(original_message):
        rejoined = ", ".join(classifier_items)
        # Rebuild the message so extract_shopping_list_items can split it cleanly
        original_message = f"price for {rejoined}"
        message = original_message
        answer, card = shopping_list_price_answer(original_message, user_id, guest_session_id, extra_families)
        evidence = evidence_rows_from_card(card)
        return finalize_agent_result({
            "response": answer,
            "answer_card": card,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                intent="multi_item_price_from_classifier",
                retrieval="multi_item_hybrid_rag",
                original_message=original_message,
                normalized_query=rejoined,
                evidence=evidence,
                strict=AGENT_STRICT_MATCHING,
                note=f"Intent classifier split query into {len(classifier_items)} items: {rejoined}",
            ),
        }, original_message)

    # If the classifier already locked onto a single item with high confidence,
    # bypass the shopping-list splitter. Without this, multi-word item names like
    # "rose pink prem cheepest" get shredded into fake separate items.
    _history_or_count_pattern = re.search(
        r"\b(history|histories|trend|trends|how many|count|times|all prices|price history|"
        r"full history|complete history|how often|how much did i pay)\b",
        normalize_text(original_message),
    )
    _looks_shopping_list = looks_like_shopping_list_price_request(original_message)
    _single_item_intent = (
        (
            understanding.get("intent") in ("item_price", "item_count")
            and bool(understanding.get("item_query"))
            and len(understanding.get("items") or []) <= 1
            and not _looks_shopping_list
        )
        or bool(_history_or_count_pattern)
    )

    category_query = category_with_include_from_message(original_message) or broad_category_from_message(original_message, understanding)
    if category_query and looks_like_shopping_list_price_request(original_message):
        receipts = fetch_owner_receipts(user_id, guest_session_id, limit=300)
        item_events = fetch_owner_item_events(user_id, guest_session_id)
        if not item_events:
            item_events = build_item_events(receipts)
        answer, card = category_with_included_items_answer(
            category_query,
            item_events,
            original_message,
            user_id,
            guest_session_id,
            extra_families,
        )
        evidence = evidence_rows_from_card(card)
        return finalize_agent_result({
            "response": answer,
            "answer_card": card,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                intent="category_price_with_includes",
                retrieval="structured_category_rag_plus_item_rag",
                original_message=original_message,
                normalized_query=f"{category_query}: {', '.join(extract_shopping_list_items(original_message))}",
                evidence=evidence,
                strict=True,
                note="Answered category prices from receipts, then included explicitly named items.",
            ),
        }, original_message)

    if not _single_item_intent and _looks_shopping_list:
        answer, card = shopping_list_price_answer(original_message, user_id, guest_session_id, extra_families)
        evidence = evidence_rows_from_card(card)
        return finalize_agent_result({
            "response": answer,
            "answer_card": card,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                intent="shopping_list_price",
                retrieval="multi_item_hybrid_rag",
                original_message=original_message,
                normalized_query=", ".join(extract_shopping_list_items(original_message)),
                evidence=evidence,
                strict=AGENT_STRICT_MATCHING,
                note="Split a multi-item shopping request and searched each item independently.",
            ),
        }, original_message)

    if category_query:
        receipts = fetch_owner_receipts(user_id, guest_session_id, limit=300)
        item_events = fetch_owner_item_events(user_id, guest_session_id)
        if not item_events:
            item_events = build_item_events(receipts)
        answer = category_price_answer(category_query, item_events, original_message)
        card = category_price_answer_card(category_query, item_events, original_message)
        evidence = evidence_rows_from_card(card)
        return finalize_agent_result({
            "response": answer,
            "answer_card": card,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                intent="category_price",
                retrieval="structured_category_rag",
                original_message=original_message,
                normalized_query=category_query,
                evidence=evidence,
                strict=True,
            ),
        }, original_message)

    action = classify_receipt_action(original_message) or classify_receipt_action(message)
    if action:
        answer = receipt_action_answer(action, original_message, user_id, guest_session_id)
        if answer:
            tools = ["receipt_memory"] if action == "open_analysis" else []
            card = None
            if action == "shopping_plan":
                card = shopping_plan_answer_card(user_id, guest_session_id)
            elif action == "price_memory":
                card = price_memory_answer_card(user_id, guest_session_id)
            evidence = evidence_rows_from_card(card)
            retrieval = "graph_rag_memory" if action == "graph_memory" else "structured_receipt_memory"
            return finalize_agent_result({
                "response": answer,
                "answer_card": card,
                "tools_used": tools,
                "thinking": "",
                "rag_trace": rag_trace(
                    intent=action,
                    retrieval=retrieval,
                    original_message=original_message,
                    normalized_query=message,
                    evidence=evidence,
                    strict=True,
                ),
            }, original_message)

    if looks_like_overview_question(message) and not looks_like_global_price_question(message):
        receipts = fetch_owner_receipts(user_id, guest_session_id, limit=300)
        item_events = fetch_owner_item_events(user_id, guest_session_id)
        if not item_events:
            item_events = build_item_events(receipts)
        flexible_answer = flexible_receipt_memory_answer(message, receipts, item_events)
        if flexible_answer:
            return finalize_agent_result({
                "response": flexible_answer,
                "tools_used": ["receipt_memory"],
                "thinking": "",
                "rag_trace": rag_trace(
                    intent="receipt_memory",
                    retrieval="structured_receipt_aggregation",
                    original_message=original_message,
                    normalized_query=message,
                    evidence=[],
                    strict=True,
                ),
            }, original_message)

    if looks_like_overview_question(message) or looks_like_global_price_question(message):
        answer = deterministic_overview_answer(message, user_id, guest_session_id)
        if answer:
            card = deterministic_overview_answer_card(message, user_id, guest_session_id)
            evidence = evidence_rows_from_card(card)
            return finalize_agent_result({
                "response": answer,
                "answer_card": card,
                "tools_used": [],
                "thinking": "",
                "rag_trace": rag_trace(
                    intent="overview",
                    retrieval="deterministic_overview_rag",
                    original_message=original_message,
                    normalized_query=message,
                    evidence=evidence,
                    strict=True,
                ),
            }, original_message)

    # Strong deterministic RAG path for imperfect product/store/price language.
    # Keep this before the Claude tool loop so receipt item answers still work
    # when external model clients are unavailable.
    # Determine the best item_rag_message for RAG retrieval.
    # Priority: history/count patterns always strip query modifiers first;
    # then use understanding item_query if available; else fall back to original.
    _HISTORY_STRIP_RE = re.compile(
        r"\b(full|complete|entire|all|price|prices|history|histories|"
        r"trend|trends|how many|how much|how often|how frequently|times|"
        r"count|show|tell|give|display|view|recent|latest|"
        r"for|did|i|buy|purchased|bought|spent|paid)\b",
        re.IGNORECASE,
    )
    if _single_item_intent and _history_or_count_pattern:
        # Strip history/count/modifier words; the remainder is the item name
        _stripped = _HISTORY_STRIP_RE.sub(" ", normalize_text(original_message)).strip()
        _clean_item = extract_query_item(_stripped) if _stripped else ""
        if _clean_item and token_set(_clean_item):
            item_rag_message = _clean_item
        elif understanding.get("item_query"):
            item_rag_message = str(understanding["item_query"])
        else:
            item_rag_message = original_message
    elif _single_item_intent and understanding.get("item_query"):
        # Single item intent with classifier item_query — use it directly
        item_rag_message = str(understanding["item_query"])
    else:
        item_rag_message = original_message
    extracted_item_query = extract_query_item(item_rag_message)
    if should_use_item_rag(item_rag_message) and token_set(extracted_item_query):
        rag = retrieve_item_events(item_rag_message, user_id, guest_session_id, limit=12, extra_families=extra_families)
        if not (rag.get("events") or rag.get("closest_candidates")):
            public_families = public_meaning_alias_families(extracted_item_query)
            if public_families:
                rag = retrieve_item_events(
                    item_rag_message,
                    user_id,
                    guest_session_id,
                    limit=12,
                    extra_families=extra_families + public_families,
                )
        display_query = clean_item_query_for_display(rag.get("normalized_query") or rag.get("query") or extracted_item_query)
        trusted_events = dedupe_item_events(trusted_item_events_for_answer(display_query, rag.get("events") or []))
        should_recover = (
            (not trusted_events and not (rag.get("closest_candidates") or []))
            or looks_like_partial_combined_item_match(display_query, trusted_events)
        )
        if should_recover:
            recovered = adaptive_failed_query_recovery(original_message, user_id, guest_session_id, extra_families)
            if recovered:
                answer, card = recovered
                evidence = evidence_rows_from_card(card)
                return finalize_agent_result({
                    "response": answer,
                    "answer_card": card,
                    "tools_used": [],
                    "thinking": "",
                    "rag_trace": rag_trace(
                        intent="adaptive_item_recovery",
                        retrieval="failed_query_self_correction_rag",
                        original_message=original_message,
                        normalized_query=", ".join(row.get("requested_item") or row.get("item") for row in (card.get("rows") or [])),
                        evidence=evidence,
                        strict=AGENT_STRICT_MATCHING,
                        note="Initial item interpretation failed; retried smaller candidate item phrases and answered only from receipt evidence.",
                    ),
                }, original_message)
        answer = deterministic_item_answer(original_message, rag)
        card = deterministic_item_answer_card(original_message, rag)
        evidence = evidence_rows_from_card(card) or evidence_rows_from_events(rag.get("events") or [])
        return finalize_agent_result({
            "response": answer,
            "answer_card": card,
            "tools_used": [],
            "thinking": "",
            "rag_trace": rag_trace(
                intent="item_price",
                retrieval="hybrid_item_rag",
                original_message=original_message,
                normalized_query=rag.get("normalized_query") or extracted_item_query,
                evidence=evidence,
                strict=AGENT_STRICT_MATCHING,
                note="Exact/fuzzy item retrieval with alias families, learned rank adjustments, and unit-aware price normalization.",
            ),
        }, original_message)

    if looks_like_smalltalk_or_help(message):
        return {
            "response": "Ask me about your receipts, prices, stores, spending, or what to buy next. For example: \"where is mutton cheapest\", \"best price for cilantro\", or \"monthly spending\".",
            "tools_used": [],
            "thinking": "",
        }

    # ── Claude agentic tool loop ──
    # Falls through here when no deterministic path handled the message.
    system_prompt = f"""You are ReceiptAI, a smart personal shopping assistant.
You answer questions about the user's own receipt history using the tools provided.
Never invent prices, stores, or purchase counts — only use evidence from the tools.

{AGENT_SCENARIO_PLAYBOOK}
"""
    tool_messages: list[dict] = [{"role": "user", "content": message}]
    if conversation_history:
        recent = conversation_history[-10:]
        tool_messages = [{"role": m["role"], "content": m["content"]} for m in recent] + [{"role": "user", "content": message}]

    response_text = ""
    answer_card: dict | None = None
    rag_evidence: list[dict] = []

    try:
        for _ in range(6):  # max tool-call rounds
            response = claude_client.messages.create(
                model=MODEL,
                max_tokens=1800,
                system=system_prompt,
                tools=AGENT_TOOLS,
                messages=tool_messages,
            )

            # Collect text blocks
            text_parts = [block.text for block in response.content if hasattr(block, "text") and block.text]
            if text_parts:
                response_text = "\n".join(text_parts).strip()

            if response.stop_reason != "tool_use":
                break

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_name = block.name
                tool_input = block.input or {}
                tools_used.append(tool_name)

                if tool_name == "query_receipts":
                    result = handle_query_receipts(tool_input, user_id, guest_session_id)
                elif tool_name == "get_price_history":
                    item_q = str(tool_input.get("item_name") or "")
                    limit  = int(tool_input.get("limit") or 25)
                    result = retrieve_item_events(item_q, user_id, guest_session_id, limit, extra_families)
                    if result.get("events"):
                        rag_evidence.extend(evidence_rows_from_events(result["events"]))
                        if not answer_card:
                            answer_card = event_answer_card(
                                result["events"][0],
                                title=f"Price history: {item_q}",
                            ) if result["events"] else None
                elif tool_name == "analyze_spending":
                    result = handle_analyze_spending(tool_input, user_id, guest_session_id)
                elif tool_name == "find_best_deals":
                    items_list = [str(i) for i in (tool_input.get("items") or [])]
                    answer_text, card = shopping_list_price_answer(
                        "best price for listed items\n" + "\n".join(items_list),
                        user_id, guest_session_id, extra_families,
                    )
                    rag_evidence.extend(evidence_rows_from_card(card))
                    result = {"answer": answer_text}
                    if not answer_card:
                        answer_card = card
                elif tool_name == "search_market_prices":
                    result = {"note": "Market price search unavailable in this build."}
                elif tool_name == "check_live_price":
                    result = build_live_price_check(
                        item_query=str(tool_input.get("item_name") or ""),
                        current_price=tool_input.get("current_price"),
                        store=tool_input.get("store"),
                        source_url=tool_input.get("source_url"),
                        user_id=user_id,
                        guest_session_id=guest_session_id,
                        live_search=bool(tool_input.get("live_search")),
                    )
                else:
                    result = {"error": f"Unknown tool: {tool_name}"}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })

            tool_messages.append({"role": "assistant", "content": response.content})
            tool_messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        print(f"[agent] Claude tool loop error: {e}")
        if not response_text:
            response_text = "I had trouble answering that. Please try again."

    if not response_text:
        response_text = "I could not find enough receipt data to answer that question."

    return finalize_agent_result({
        "response": response_text,
        "answer_card": answer_card,
        "tools_used": list(dict.fromkeys(tools_used)),
        "thinking": "",
        "rag_trace": rag_trace(
            intent="agentic_tool_loop",
            retrieval="claude_tool_use",
            original_message=original_message,
            normalized_query=message,
            evidence=rag_evidence,
            strict=False,
            note="Answered via Claude tool-use loop; evidence grounded in receipt RAG.",
        ),
    }, original_message)
