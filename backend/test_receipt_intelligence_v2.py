import sys
import types
from datetime import datetime


dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules["dotenv"] = dotenv

anthropic = types.ModuleType("anthropic")
anthropic.Anthropic = lambda api_key=None: None
sys.modules["anthropic"] = anthropic

supabase_module = types.ModuleType("supabase")
supabase_module.Client = object
supabase_module.create_client = lambda *args, **kwargs: None
sys.modules["supabase"] = supabase_module

from app.services import receipt_intelligence as ri


NOW = datetime(2026, 6, 10)

RECEIPTS = [
    {
        "id": 1,
        "store": "WAL*MART",
        "date": "2026-05-12",
        "created_at": "2026-05-12",
        "items": [
            {"name": "Great Value Milk", "price": 3.49},
            {"name": "Yogurt Plain", "price": 2.99},
            {"name": "Sona Masoori Rice 10LB", "price": 12.99},
            {"name": "Potato Chips", "price": 4.50},
            {"name": "Wheat Flour", "price": 8.99},
        ],
    },
    {
        "id": 2,
        "store": "India Mart",
        "date": "2026-05-20",
        "created_at": "2026-05-20",
        "items": [
            {"name": "Eggplant", "price": 1.99},
            {"name": "Tomatoes", "price": 2.49},
            {"name": "ONOIN RED", "price": 1.25},
            {"name": "Pepper Chicken", "price": 34.98},
        ],
    },
    {
        "id": 3,
        "store": "Target",
        "date": "2026-06-02",
        "created_at": "2026-06-02",
        "items": [
            {"name": "Laundry Detergent", "price": 11.99},
            {"name": "Cola 12 Pack", "price": 6.99},
            {"name": "Oil Burner", "price": 4.49},
            {"name": "Mushroom Gummies", "price": 12.49},
        ],
    },
    {
        "id": 4,
        "store": "Central Arkansas Wholesale",
        "date": "2026-05-19",
        "created_at": "2026-05-19",
        "items": [
            {"name": "Frozen Monster Synthetic Nicotine Salt E-Liquid 30ML Mango Peach Guava ICE", "price": 13.98},
            {"name": "Unknown item", "price": 9.99},
        ],
    },
]


def events_from_receipts():
    events = []
    for receipt in RECEIPTS:
        for index, item in enumerate(receipt["items"]):
            events.append({
                "receipt_id": receipt["id"],
                "line_index": index,
                "store": receipt["store"],
                "date": receipt["date"],
                "created_at": receipt["created_at"],
                "item_original": item["name"],
                "item_normalized": ri.normalize_item_name(item["name"]),
                "quantity": 1,
                "unit": "each",
                "line_price": item["price"],
            })
    return events


EVENTS = events_from_receipts()


def answer(message):
    return ri.answer_receipt_query(message, RECEIPTS, EVENTS, now=NOW)


def test_exact_item_lookup():
    result = answer("Did I buy milk?")
    assert result["rag_trace"]["intent"] == "receipt_item_lookup"
    assert "Yes" in result["response"]
    assert "Great Value Milk" in result["response"]


def test_spelling_mistake_query_and_ocr_item():
    result = answer("did i by rise")
    assert "Sona Masoori Rice" in result["response"]
    assert result["rag_trace"]["entities"]["items"] == ["rice"]

    result = answer("Did I buy onions?")
    assert "ONOIN RED" in result["response"]


def test_synonyms_and_regional_aliases():
    assert "Yogurt Plain" in answer("Did I buy curd?")["response"]
    assert "Eggplant" in answer("Did I buy brinjal?")["response"]
    assert "Laundry Detergent" in answer("Did I buy detergent or washing powder?")["response"]
    assert "Wheat Flour" in answer("atta")["response"]


def test_missing_item_no_hallucination():
    result = answer("Did I buy eggs?")
    assert "did not find a clear eggs purchase" in result["response"].lower()
    assert result["rag_trace"]["evidence_count"] == 0


def test_ambiguous_item_does_not_match_prepared_or_unrelated_product():
    result = answer("did i buy pepper")
    assert "did not find a clear pepper purchase" in result["response"].lower()
    assert "Pepper Chicken" not in result["response"]
    assert result["rag_trace"]["evidence_count"] == 0

    result = answer("did i buy oil")
    assert "did not find a clear oil purchase" in result["response"].lower()
    assert "Oil Burner" not in result["response"]

    result = answer("did i buy mushroom")
    assert "did not find a clear mushroom purchase" in result["response"].lower()
    assert "Mushroom Gummies" not in result["response"]


def test_negative_receipt_question():
    result = answer("Which receipts don't have onions?")
    assert result["rag_trace"]["intent"] == "receipt_missing_item_lookup"
    assert "Target" in result["response"]
    assert "WAL*MART" in result["response"]
    assert "India Mart" not in result["response"]


def test_store_filter():
    result = answer("What items did I buy from Walmart?")
    assert result["rag_trace"]["intent"] == "store_lookup"
    assert "Great Value Milk" in result["response"]
    assert "Eggplant" not in result["response"]
    assert result["answer_card"]["type"] == "store_items"


def test_store_first_bad_grammar_with_ocr_store_name():
    result = answer("walmart what all items i buy")
    assert result["rag_trace"]["intent"] == "store_lookup"
    assert result["rag_trace"]["entities"]["store"] == "walmart"
    assert "Great Value Milk" in result["response"]
    assert "Eggplant" not in result["response"]


def test_date_and_category_spending():
    result = answer("How much did I spend on snacks last month?")
    assert result["rag_trace"]["intent"] == "spending_summary"
    assert "$4.50" in result["response"]
    assert result["rag_trace"]["entities"]["date_range"] == ["2026-05-01", "2026-06-01"]


def test_complete_spending_summary_is_not_treated_as_item():
    result = answer("Give me a complete summary of my spending")
    response = result["response"].lower()
    assert result["rag_trace"]["intent"] == "spending_summary"
    assert "you spent" in response
    assert "complete summary spending purchase" not in response


def test_best_deals_recently_uses_receipt_summary_path():
    result = answer("What were the best deals I got recently?")
    response = result["response"].lower()
    assert result["rag_trace"]["intent"] == "spending_summary"
    assert "best receipt deals" in response
    assert result["answer_card"]["type"] == "best_deals"


def test_rice_does_not_match_nicotine_or_unknown_items():
    result = answer("what is the rice i bought")
    response = result["response"].lower()
    assert "sona masoori rice" in response
    assert "nicotine" not in response
    assert "unknown item" not in response
    evidence_text = " ".join(str(row) for row in result["rag_trace"]["evidence"]).lower()
    assert "nicotine" not in evidence_text
    assert "unknown item" not in evidence_text


def test_messy_grammar_spending_item_store_date():
    result = answer("rice walmart last week how much")
    response = result["response"].lower()
    assert "did not find" in response
    assert "rice" in response
    assert "at walmart" in response
    assert "current price" in response
    assert "walmart app or website" in response


def test_store_item_price_word_stays_grounded():
    result = answer("walmart rice price last week")
    response = result["response"].lower()
    assert "did not find" in response
    assert "rice" in response
    assert "at walmart" in response


def test_general_question_is_not_receipt_answered():
    query = ri.parse_receipt_query("What is the best way to store tomatoes?", NOW)
    assert query.intent == "general_question"
    assert answer("What is the best way to store tomatoes?") is None
