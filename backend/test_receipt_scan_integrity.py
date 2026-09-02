"""Deterministic receipt-scan integrity regressions.

These tests protect Price Memory and the AI agent from plausible-looking OCR
output that contains metadata rows, split weighted-item lines, or shifted prices.
"""

import sys
import types


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

from app.routes import receipts as receipt_routes
from app.services import agent, claude


def namaste_model_output() -> dict:
    return {
        "store": "NAMASTE INDIAN GROCERY",
        "date": "11-Aug-2026",
        "time": "7:21:35P",
        "subtotal": 14.90,
        "tax": 0.52,
        "total": 15.42,
        "items": [
            {"name": "Cashier: Shirley 2135P", "quantity": 1, "unit": "each", "price": 8.12},
            {"name": "1 Fresh Chicken(Bayani Style)", "quantity": 1, "unit": "each", "price": 6.78},
            {"name": "Cut 1.85 lb @ $4.39/lb", "quantity": 1, "unit": "each", "price": 8.12},
            {"name": "1 Halal Chicken/Drumsticks", "quantity": 1, "unit": "each", "price": 6.78},
            {"name": "1.58 lb @ $4.29/lb", "quantity": 1, "unit": "each", "price": 6.78},
        ],
        "validation": {"is_receipt": True, "confidence": 0.96},
        "validation_notes": [],
    }


def test_namaste_split_weight_lines_are_repaired_before_save():
    normalized = claude.normalize_receipt_data(namaste_model_output())

    assert [item["name"] for item in normalized["items"]] == [
        "Fresh Chicken (Biryani Style) Cut",
        "Halal Chicken Drumsticks",
    ]
    assert normalized["items"][0]["quantity"] == 1.85
    assert normalized["items"][0]["unit"] == "lb"
    assert normalized["items"][0]["unit_price"] == 4.39
    assert normalized["items"][0]["price"] == 8.12
    assert normalized["items"][1]["quantity"] == 1.58
    assert normalized["items"][1]["unit_price"] == 4.29
    assert normalized["items"][1]["price"] == 6.78
    assert round(sum(item["price"] for item in normalized["items"]), 2) == 14.90
    assert claude.scan_integrity_issues(normalized) == []
    claude.validate_scan_quality(normalized)


def test_metadata_and_unmerged_weight_rows_are_never_agent_items():
    assert agent.is_valid_receipt_item_name("Cashier: Shirley 2135P") is False
    assert agent.is_valid_receipt_item_name("Cut 1.85 lb @ $4.39/lb") is False
    assert agent.is_valid_receipt_item_name("1.58 lb @ $4.29/lb") is False
    assert agent.is_valid_receipt_item_name("Fresh Chicken Biryani Style Cut") is True


def test_historical_receipt_json_is_repaired_before_agent_retrieval():
    receipt = namaste_model_output()
    receipt.update({"id": "namaste-246", "created_at": "2026-08-11T19:22:14"})
    events = agent.build_item_events([receipt])

    assert [event["item_original"] for event in events] == [
        "Fresh Chicken (Biryani Style) Cut",
        "Halal Chicken Drumsticks",
    ]
    assert [event["line_price"] for event in events] == [8.12, 6.78]
    assert all(event["metadata"].get("merged_from_split_lines") for event in events)


def test_historical_receipt_is_repaired_for_receipt_list_display():
    receipt = namaste_model_output()
    receipt.update({"id": "namaste-246", "_private_note": "never expose"})

    repaired = receipt_routes.normalized_receipt_for_response(receipt)

    assert [item["name"] for item in repaired["items"]] == [
        "Fresh Chicken (Biryani Style) Cut",
        "Halal Chicken Drumsticks",
    ]
    assert "_private_note" not in repaired
    assert receipt["items"][0]["name"] == "Cashier: Shirley 2135P"


def test_shifted_duplicate_prices_fail_integrity_gate():
    malformed = {
        "subtotal": 14.90,
        "items": [
            {"name": "Fresh Chicken", "price": 8.12},
            {"name": "Fresh Chicken detail", "price": 8.12},
            {"name": "Halal Chicken", "price": 6.78},
            {"name": "Halal Chicken detail", "price": 6.78},
        ],
    }
    assert "item_lines_exceed_subtotal" in claude.scan_integrity_issues(malformed)


def test_positive_discount_rows_do_not_trigger_false_total_failure():
    valid = {
        "subtotal": 14.90,
        "items": [
            {"name": "Fresh Chicken", "price": 8.12},
            {"name": "Halal Chicken", "price": 6.78},
            {"name": "Store coupon", "price": 2.00, "is_discount": True, "source": "discount"},
        ],
    }
    assert claude.scan_integrity_issues(valid) == []


def test_price_memory_emits_iso_dates_for_month_name_receipts():
    receipt_event = {
        "receipt_id": "namaste-246",
        "line_index": 0,
        "store": "NAMASTE INDIAN GROCERY",
        "date": "11-Aug-2026 7:21:35P",
        "created_at": "2026-08-11T19:22:14",
        "item_original": "Fresh Chicken Biryani Style Cut",
        "item_normalized": "fresh chicken biryani style cut",
        "quantity": 1.85,
        "unit": "lb",
        "unit_price": 4.39,
        "line_price": 8.12,
    }
    original_fetch = agent.fetch_owner_item_events
    try:
        agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: [receipt_event]
        profiles = agent.build_price_memory(user_id="test-user")
    finally:
        agent.fetch_owner_item_events = original_fetch

    assert profiles[0]["last_bought_date"] == "2026-08-11"
    assert profiles[0]["price_events"][0]["date"] == "2026-08-11"
    assert profiles[0]["recent_events"][0]["date"] == "2026-08-11"
