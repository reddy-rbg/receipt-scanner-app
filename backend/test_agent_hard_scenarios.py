"""Hard-mode ReceiptAI agent regression checks.

These scenarios stress ambiguous user wording, OCR-ish item names, regional
aliases, routing collisions, and quantity parsing. They should stay offline and
deterministic so they can be run before backend changes.
"""

import test_agent_rag_regression as base
from app.services import agent
from app.services import claude


EXTRA_EVENTS = [
    {
        "receipt_id": "10",
        "line_index": 10,
        "store": "India Mart",
        "date": "5/20/26",
        "created_at": "2026-05-20",
        "code": None,
        "item_original": "FRESH OKRA",
        "item_normalized": "fresh okra",
        "quantity": 1,
        "unit": "lb",
        "line_price": 2.49,
    },
    {
        "receipt_id": "11",
        "line_index": 11,
        "store": "NWA Bharath Bazaar",
        "date": "5/17/26",
        "created_at": "2026-05-17",
        "code": None,
        "item_original": "BHINDI CUT 400G",
        "item_normalized": "bhindi cut 400g",
        "quantity": 1,
        "unit": "each",
        "line_price": 3.99,
    },
    {
        "receipt_id": "12",
        "line_index": 12,
        "store": "India Mart",
        "date": "5/20/26",
        "created_at": "2026-05-20",
        "code": None,
        "item_original": "DAHI PLAIN YOGURT 32OZ",
        "item_normalized": "dahi plain yogurt 32oz",
        "quantity": 1,
        "unit": "each",
        "line_price": 4.29,
    },
    {
        "receipt_id": "13",
        "line_index": 13,
        "store": "Whole Foods",
        "date": "5/18/26",
        "created_at": "2026-05-18",
        "code": None,
        "item_original": "GREEK YOGURT VANILLA",
        "item_normalized": "greek yogurt vanilla",
        "quantity": 1,
        "unit": "each",
        "line_price": 5.99,
    },
    {
        "receipt_id": "14",
        "line_index": 14,
        "store": "Lowes",
        "date": "5/12/26",
        "created_at": "2026-05-12",
        "code": "1234",
        "item_original": "2.00-GAL ROSE PINK PREN",
        "item_normalized": "2.00 gal rose pink pren",
        "product_size": "2.00-GAL",
        "quantity": 1,
        "unit": "each",
        "line_price": 24.98,
        "explicit_quantity": False,
    },
    {
        "receipt_id": "15",
        "line_index": 15,
        "store": "Lowes",
        "date": "5/10/26",
        "created_at": "2026-05-10",
        "code": "1235",
        "item_original": "2.00-GAL ROSE PINK PREM",
        "item_normalized": "2.00 gal rose pink prem",
        "product_size": "2.00-GAL",
        "quantity": 1,
        "unit": "each",
        "line_price": 12.49,
        "explicit_quantity": False,
    },
    {
        "receipt_id": "16",
        "line_index": 16,
        "store": "India Mart",
        "date": "5/21/26",
        "created_at": "2026-05-21",
        "code": None,
        "item_original": "LAXMI BASMATI RICE 10LB",
        "item_normalized": "laxmi basmati rice 10lb",
        "quantity": 1,
        "unit": "each",
        "line_price": 18.99,
    },
    {
        "receipt_id": "17",
        "line_index": 17,
        "store": "Walmart",
        "date": "5/14/26",
        "created_at": "2026-05-14",
        "code": None,
        "item_original": "EGG NOODLES",
        "item_normalized": "egg noodles",
        "quantity": 1,
        "unit": "each",
        "line_price": 2.29,
    },
]

_ORIGINAL_AGENT_FUNCTIONS = {
    "fetch_owner_item_events": agent.fetch_owner_item_events,
    "fetch_owner_receipts": agent.fetch_owner_receipts,
    "fetch_owner_alias_families": agent.fetch_owner_alias_families,
    "save_owner_alias_families": agent.save_owner_alias_families,
    "public_meaning_alias_families": agent.public_meaning_alias_families,
}


def setup_module():
    events = base.EVENTS + EXTRA_EVENTS
    getattr(agent, "_RECEIPT_CACHE", {}).clear()
    getattr(agent, "_ITEM_EVENT_CACHE", {}).clear()
    agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: events
    agent.fetch_owner_receipts = lambda user_id=None, guest_session_id=None, limit=300: [
        {
            "id": "hard-r1",
            "store": "India Mart",
            "date": "2026-05-21",
            "created_at": "2026-05-21",
            "total": 68.25,
            "subtotal": 65.0,
            "tax": 3.25,
            "total_savings": 2.0,
            "items": [
                {"name": event["item_original"], "price": event["line_price"]}
                for event in events
            ],
        },
        {
            "id": "hard-r2",
            "store": "Lowes",
            "date": "2026-05-10",
            "created_at": "2026-05-10",
            "total": 37.47,
            "items": [
                {"name": "2.00-GAL ROSE PINK PREM", "quantity": 2.00, "price": 12.49},
                {"name": "QTY 3 CEDAR MULCH", "quantity": 3, "price": 11.97, "unit_price": 3.99},
            ],
        },
    ]
    agent.fetch_owner_alias_families = lambda user_id=None, guest_session_id=None: []
    agent.save_owner_alias_families = lambda families, user_id=None, guest_session_id=None: None
    agent.public_meaning_alias_families = lambda query: []


def teardown_module():
    for name, value in _ORIGINAL_AGENT_FUNCTIONS.items():
        setattr(agent, name, value)
    getattr(agent, "_RECEIPT_CACHE", {}).clear()
    getattr(agent, "_ITEM_EVENT_CACHE", {}).clear()


def event_names(query):
    return [event["item_original"] for event in agent.retrieve_item_events(query)["events"]]


def response_for(message, history=None):
    return agent.run_agent(message, history or [])["response"]


def test_okra_and_bhindi_are_same_family_without_matching_random_vegetables():
    names = event_names("where is bhindi cheap")
    assert names == ["FRESH OKRA", "BHINDI CUT 400G"]
    assert "CILANTRO" not in names


def test_yogurt_and_dahi_aliases_do_not_pull_mango_or_cilantro():
    names = event_names("best dahi price")
    assert "DAHI PLAIN YOGURT 32OZ" in names
    assert "GREEK YOGURT VANILLA" in names
    assert "BHAIYAJI GREEK MANGO 341G" not in names
    assert "CILANTRO" not in names


def test_magie_typo_still_finds_maggi_not_mango():
    names = event_names("magie cheep prise")
    assert names == ["MAGGI MASALA NOODLES"]


def test_coriander_alias_locks_to_cilantro():
    names = event_names("coriander lowest price")
    assert names == ["CILANTRO"]


def test_egg_item_does_not_match_egg_noodles_for_simple_egg_price():
    names = event_names("egg best price")
    assert names == ["EGGS 12CT"]
    assert "EGG NOODLES" not in names


def test_noodles_query_can_return_maggi_and_egg_noodles_but_not_mango():
    names = event_names("cheap noodles")
    assert "MAGGI MASALA NOODLES" in names
    assert "EGG NOODLES" in names
    assert "BHAIYAJI GREEK MANGO 341G" not in names


def test_prem_ocr_variant_finds_both_paint_rows():
    names = event_names("rose pink prem price")
    assert names == ["2.00-GAL ROSE PINK PREN", "2.00-GAL ROSE PINK PREM"]


def test_product_size_scan_error_is_not_treated_as_quantity_two():
    receipts = agent.fetch_owner_receipts()
    lowes_events = agent.build_item_events([receipts[1]])
    paint = next(event for event in lowes_events if "ROSE PINK" in event["item_original"])
    assert paint["product_size"] == "2.00-GAL"
    assert paint["quantity"] == 1.0
    assert paint["line_price"] == 12.49
    assert paint["quantity_note"] == "product size detected; treated as quantity 1"


def test_final_evidence_gate_blocks_unbacked_receipt_claim():
    result = {
        "response": "Yes, you bought rice at Walmart for $9.99.",
        "answer_card": None,
        "tools_used": [],
        "rag_trace": agent.rag_trace(
            intent="item_price",
            retrieval="hybrid_item_rag",
            original_message="what rice did i buy",
            evidence=[],
            strict=True,
        ),
    }
    guarded = agent.finalize_agent_result(result, "what rice did i buy")
    assert "could not verify" in guarded["response"].lower()
    assert guarded["rag_trace"]["evidence_gate_blocked"] is True


def test_final_evidence_gate_allows_receipt_claim_with_evidence():
    result = {
        "response": "Yes, you bought LAXMI BASMATI RICE 10LB.",
        "answer_card": None,
        "tools_used": [],
        "rag_trace": agent.rag_trace(
            intent="item_price",
            retrieval="hybrid_item_rag",
            original_message="what rice did i buy",
            evidence=[{
                "receipt_id": "16",
                "item": "LAXMI BASMATI RICE 10LB",
                "store": "India Mart",
                "price": "$18.99",
            }],
            strict=True,
        ),
    }
    guarded = agent.finalize_agent_result(result, "what rice did i buy")
    assert guarded["response"] == result["response"]
    assert not guarded["rag_trace"].get("evidence_gate_blocked")


def test_final_evidence_gate_allows_analytics_without_line_evidence():
    result = {
        "response": "You spent $120.00 across 4 receipts this month.",
        "answer_card": None,
        "tools_used": [],
        "rag_trace": agent.rag_trace(
            intent="spending_summary",
            retrieval="structured_receipt_aggregation",
            original_message="complete spending summary",
            evidence=[],
            strict=True,
        ),
    }
    guarded = agent.finalize_agent_result(result, "complete spending summary")
    assert guarded["response"] == result["response"]
    assert guarded["rag_trace"]["answer_mode"] == "receipt_analytics"


def test_explicit_quantity_survives_when_receipt_says_qty():
    receipts = agent.fetch_owner_receipts()
    lowes_events = agent.build_item_events([receipts[1]])
    mulch = next(event for event in lowes_events if "MULCH" in event["item_original"])
    assert mulch["quantity"] == 3.0
    assert mulch["unit_price"] == 3.99
    assert mulch["quantity_note"] == "explicit quantity"


def test_global_cheapest_does_not_steal_unknown_item_with_typo():
    response = response_for("zaffron cheep?")
    assert "no clear zaffron" in response.lower()
    assert "cheapest" not in response.lower()
    assert "cinnamon" not in response.lower()


def test_price_check_with_amount_extracts_item_not_price_as_item():
    response = response_for("is 4.00 good for dahi")
    assert "dahi" in response.lower() or "yogurt" in response.lower()
    assert "current price" in response.lower()
    assert "cilantro" not in response.lower()


def test_should_i_buy_now_routes_to_price_check_for_specific_item():
    response = response_for("should I buy eggs now at $5")
    assert "eggs" in response.lower()
    assert "current price" in response.lower()
    assert "purchase found" not in response.lower()


def test_current_market_without_product_asks_for_product_not_random_receipt_item():
    response = response_for("current market price compare")
    assert "needs a product" in response.lower()
    assert "goat" not in response.lower()
    assert "cilantro" not in response.lower()


def test_followup_pronoun_uses_last_item_topic():
    history = [{"role": "user", "content": "best price for dahi"}]
    resolved = agent.resolve_followup_message("where was it cheapest", history)
    assert resolved == "where was it cheapest dahi"


def test_followup_after_spending_report_does_not_inherit_fake_item():
    history = [{"role": "user", "content": "show category-wise spending"}]
    resolved = agent.resolve_followup_message("where cheapest", history)
    assert resolved == "where cheapest"


def test_general_storage_question_about_bought_item_stays_general():
    response = response_for("how to store dahi fresh")
    assert "purchase found" not in response.lower()
    assert "best price" not in response.lower()


def test_receipt_price_question_about_store_word_is_not_general_advice():
    assert not agent.looks_like_general_advice_question("what store was dahi cheapest")
    response = response_for("what store was dahi cheapest")
    assert "dahi" in response.lower() or "yogurt" in response.lower()
    assert "best price found" in response.lower()


def test_category_words_do_not_trigger_spending_report_inside_item_query():
    response = response_for("cheap vegetable okra")
    assert "okra" in response.lower() or "bhindi" in response.lower()
    assert "receipt categories" not in response.lower()


def test_monthly_correction_wins_after_weekly_history():
    history = [{"role": "user", "content": "give graph spending in week wise"}]
    response = response_for("no, month wise", history)
    assert "monthly expense analysis" in response.lower()
    assert "weekly spending" not in response.lower()


def test_store_breakdown_word_table_does_not_match_vegetable():
    assert agent.classify_receipt_action("make a table of stores by spend") == "store_breakdown"
    assert agent.classify_receipt_action("cheap vegetables") != "store_breakdown"


def test_receipt_action_classifier_handles_harder_phrasings():
    cases = {
        "which store am i visiting most often": "store_frequency",
        "break down my spending by store": "store_breakdown",
        "show me discounts and taxes": "tax_discount",
        "what are my repeat purchase price trends": "item_price_trends",
        "plan grocery for next month": "shopping_plan",
        "where am i overpaying": "market_comparison",
    }
    for message, expected in cases.items():
        assert agent.classify_receipt_action(message) == expected


def test_rice_size_does_not_make_rice_query_unknown():
    names = event_names("basmati rice cheap")
    assert names == ["LAXMI BASMATI RICE 10LB"]


def test_answer_guard_removes_semantically_wrong_low_price_candidate():
    rag = {
        "query": "best dahi price",
        "normalized_query": "dahi",
        "events": [
            EXTRA_EVENTS[2],
            base.EVENTS[4],
        ],
    }
    answer = agent.deterministic_item_answer("best dahi price", rag)
    assert "DAHI PLAIN YOGURT" in answer
    assert "CILANTRO" not in answer


def test_hard_release_matrix():
    scenarios = [
        ("muttton kema loww", ["GOAT KEEMA"], ["GOAT LEG", "CINNAMON"]),
        ("clantro lowest", ["CILANTRO"], ["CINNAMON", "MANGO"]),
        ("huevos barato", ["EGGS 12CT"], ["EGG NOODLES", "CILANTRO"]),
        ("bhindi best price", ["FRESH OKRA"], ["CILANTRO", "MANGO"]),
        ("rose pink frame lowest", ["ROSE PINK"], ["CILANTRO", "GOAT"]),
    ]
    failures = []
    for query, must_include, must_not_include in scenarios:
        answer = response_for(query)
        answer_upper = answer.upper()
        for expected in must_include:
            if expected not in answer_upper:
                failures.append(f"{query}: missing {expected}\n{answer}")
        for forbidden in must_not_include:
            if forbidden in answer_upper:
                failures.append(f"{query}: included forbidden {forbidden}\n{answer}")
    assert not failures, "\n\n".join(failures)


def test_price_memory_keeps_full_history_for_instant_price_check():
    old_low = {
        "receipt_id": "green-old-low",
        "line_index": 1,
        "store": "India Mart",
        "date": "4/01/26",
        "created_at": "2026-04-01",
        "code": None,
        "item_original": "AMERICAN GREEN ONION",
        "item_normalized": "american greenonion",
        "quantity": 1,
        "unit": "each",
        "line_price": 0.49,
    }
    newer_events = [
        {
            **old_low,
            "receipt_id": f"green-new-{index}",
            "date": f"5/{10 + index}/26",
            "created_at": f"2026-05-{10 + index:02d}",
            "line_price": price,
        }
        for index, price in enumerate([2.47, 2.39, 2.29, 2.19, 2.09, 1.99], start=1)
    ]
    current_scan = {
        **old_low,
        "receipt_id": "current-scan",
        "date": "5/23/26",
        "created_at": "2026-05-23",
        "line_price": 0.69,
    }

    original_events = agent.fetch_owner_item_events
    try:
        agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: [
            old_low,
            *newer_events,
            current_scan,
        ]
        result = agent.search_price_memory("AMERICAN GREEN ONION")
        match = result["matches"][0]
        previous_prices = [
            event["price"]
            for event in match["price_events"]
            if event["receipt_id"] != "current-scan"
        ]
        recent_previous_prices = [
            event["price"]
            for event in match["recent_events"]
            if event["receipt_id"] != "current-scan"
        ]
        assert min(previous_prices) == 0.49
        assert min(recent_previous_prices) != 0.49
        assert match["lowest_price"] == 0.49
    finally:
        agent.fetch_owner_item_events = original_events


def test_price_memory_uses_unit_price_for_multi_each_lines():
    event = {
        "receipt_id": "cilantro-pack",
        "line_index": 1,
        "store": "India Mart",
        "date": "5/23/26",
        "created_at": "2026-05-23",
        "code": None,
        "item_original": "CILANTRO",
        "item_normalized": "cilantro",
        "quantity": 3,
        "unit": "each",
        "unit_price": 0.59,
        "line_price": 1.77,
    }
    assert agent.price_memory_event_price(event) == 0.59


def test_price_memory_uses_unit_price_for_weighted_goat_keema_lines():
    event = {
        "receipt_id": "goat-weighted",
        "line_index": 1,
        "store": "India Mart",
        "date": "5/23/26",
        "created_at": "2026-05-23",
        "code": None,
        "item_original": "GOAT KEEMA",
        "item_normalized": "goat keema",
        "quantity": 0.52,
        "unit": "lb",
        "unit_price": 14.99,
        "line_price": 7.79,
    }
    assert agent.price_memory_event_price(event) == 14.99


def test_weighted_price_memory_profile_uses_unit_price_not_line_total():
    old_event = {
        "receipt_id": "old-goat",
        "line_index": 1,
        "store": "India Mart",
        "date": "5/05/26",
        "created_at": "2026-05-05",
        "code": None,
        "item_original": "GOAT KEEMA",
        "item_normalized": "goat keema",
        "quantity": 0.77,
        "unit": "lb",
        "unit_price": 14.99,
        "line_price": 11.54,
    }
    current_event = {
        **old_event,
        "receipt_id": "current-goat",
        "date": "5/23/26",
        "created_at": "2026-05-23",
        "quantity": 0.52,
        "line_price": 7.79,
    }
    original_events = agent.fetch_owner_item_events
    try:
        agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: [
            old_event,
            current_event,
        ]
        match = agent.search_price_memory("GOAT KEEMA")["matches"][0]
        assert match["lowest_price"] == 14.99
        assert match["highest_price"] == 14.99
        assert all(event["compare_price"] == 14.99 for event in match["price_events"])
    finally:
        agent.fetch_owner_item_events = original_events


def test_weighted_price_memory_derives_unit_price_when_missing():
    event = {
        "receipt_id": "old-goat-no-unit-price",
        "line_index": 1,
        "store": "India Mart",
        "date": "5/05/26",
        "created_at": "2026-05-05",
        "code": None,
        "item_original": "GOAT KEEMA",
        "item_normalized": "goat keema",
        "quantity": 0.77,
        "unit": "lb",
        "unit_price": None,
        "line_price": 11.54,
    }
    assert agent.price_memory_event_price(event) == 14.99


def test_scan_normalization_merges_wrapped_ice_cream_item():
    receipt = {
        "store": "India Mart",
        "date": "5/23/26",
        "total": 10.47,
        "items": [
            {"name": "VL Badam Carnival", "quantity": 1, "unit": "each", "unit_price": 2.49, "price": 2.49},
            {"name": "IceCream 100", "quantity": 1, "unit": "each", "unit_price": 3.99, "price": 3.99},
            {"name": "PLUM CAKE", "quantity": 1, "unit": "each", "unit_price": 3.99, "price": 3.99},
        ],
    }
    normalized = claude.normalize_receipt_data(receipt)
    names = [item["name"] for item in normalized["items"]]
    assert names == ["VL Badam Carnival IceCream 100", "PLUM CAKE"]
    assert normalized["items"][0]["price"] == 2.49
    assert normalized["items"][0]["merged_from_split_lines"] is True


def test_scan_normalization_splits_ice_cream_tail_from_weighted_chili():
    receipt = {
        "store": "India Mart",
        "date": "5/23/26",
        "total": 12.74,
        "items": [
            {"name": "CHILLI THAI GREEN VL Badam Carnival", "quantity": 0.94, "unit": "lb", "unit_price": 3.89, "price": 3.66},
            {"name": "IceCream 100", "quantity": 1, "unit": "each", "unit_price": 3.99, "price": 3.99},
            {"name": "PLUM CAKE", "quantity": 1, "unit": "each", "unit_price": 3.99, "price": 3.99},
        ],
    }
    normalized = claude.normalize_receipt_data(receipt)
    names = [item["name"] for item in normalized["items"]]
    assert names == ["CHILLI THAI GREEN", "VL Badam Carnival IceCream 100", "PLUM CAKE"]
    assert normalized["items"][0]["unit"] == "lb"
    assert normalized["items"][0]["price"] == 3.66
    assert normalized["items"][1]["price"] == 3.99
    assert normalized["items"][1]["merged_from_split_lines"] is True


def test_price_memory_rejects_weak_long_product_match():
    royal_smokes_cream = {
        "receipt_id": "smoke-cream",
        "line_index": 1,
        "store": "Royal Smokes - Rogers",
        "date": "5/01/26",
        "created_at": "2026-05-01",
        "code": None,
        "item_original": "CARNIVAL CREAM",
        "item_normalized": "carnival cream",
        "quantity": 1,
        "unit": "each",
        "line_price": 10.67,
    }
    real_ice_cream = {
        **royal_smokes_cream,
        "receipt_id": "ice-cream",
        "store": "India Mart",
        "item_original": "VL BADAM CARNIVAL ICECREAM 100",
        "item_normalized": "vl badam carnival icecream 100",
        "line_price": 2.49,
    }

    original_events = agent.fetch_owner_item_events
    try:
        agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: [
            royal_smokes_cream,
            real_ice_cream,
        ]
        result = agent.search_price_memory("VL Badam Carnival IceCream 100")
        names = [match["item_name"] for match in result["matches"]]
        stores = [match["cheapest_store"] for match in result["matches"]]
        assert "VL BADAM CARNIVAL ICECREAM 100" in names
        assert "CARNIVAL CREAM" not in names
        assert "Royal Smokes - Rogers" not in stores
    finally:
        agent.fetch_owner_item_events = original_events


def test_semantic_duplicate_receipt_detects_retake_without_same_image_hash():
    scanned = {
        "store": "India Mart",
        "date": "5/23/26",
        "total": 51.51,
        "items": [
            {"name": "GOAT KEEMA", "price": 7.79},
            {"name": "CHICKEN LEG & THIGH", "price": 5.97},
            {"name": "CILANTRO", "price": 1.77},
        ],
    }
    existing = {
        "id": "already-saved",
        "store": "INDIA MART",
        "date": "2026-05-23",
        "total": 51.51,
        "items": [
            {"name": "GOAT KEEMA", "price": 7.79},
            {"name": "CHICKEN LEG THIGH", "price": 5.97},
            {"name": "CILANTRO", "price": 1.77},
        ],
    }

    assert agent.looks_like_same_receipt(scanned, existing)


def test_price_memory_rejects_restaurant_items_with_weak_grocery_matches():
    assert not agent.price_memory_match_is_comparable("Butter Chicken Curry", "CHICKEN LEG & THIGH", 0.7)
    assert not agent.price_memory_match_is_comparable("Butter Chicken Curry", "SEAFOOD", 0.7)
    assert not agent.price_memory_match_is_comparable("Garlic Naan", "GARLIC", 0.7)
    assert not agent.price_memory_match_is_comparable("Veg Samosa(Each)", "SAMOSA", 0.7)
    assert agent.price_memory_match_is_comparable("Veg Fried Rice", "VEG FRIED RICE", 1.0)
    assert agent.price_memory_match_is_comparable("Garlic Naan", "GARLIC NAAN", 1.0)


def test_scan_media_type_uses_actual_png_bytes_not_jpeg_default():
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    jpeg_header = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    assert claude.detect_image_media_type(png_header) == "image/png"
    assert claude.detect_image_media_type(jpeg_header) == "image/jpeg"
    assert claude.compress_image_for_claude(png_header)[1] == "image/png"


if __name__ == "__main__":
    setup_module()
    tests = [
        test_okra_and_bhindi_are_same_family_without_matching_random_vegetables,
        test_yogurt_and_dahi_aliases_do_not_pull_mango_or_cilantro,
        test_magie_typo_still_finds_maggi_not_mango,
        test_coriander_alias_locks_to_cilantro,
        test_egg_item_does_not_match_egg_noodles_for_simple_egg_price,
        test_noodles_query_can_return_maggi_and_egg_noodles_but_not_mango,
        test_prem_ocr_variant_finds_both_paint_rows,
        test_product_size_scan_error_is_not_treated_as_quantity_two,
        test_explicit_quantity_survives_when_receipt_says_qty,
        test_global_cheapest_does_not_steal_unknown_item_with_typo,
        test_price_check_with_amount_extracts_item_not_price_as_item,
        test_should_i_buy_now_routes_to_price_check_for_specific_item,
        test_current_market_without_product_asks_for_product_not_random_receipt_item,
        test_followup_pronoun_uses_last_item_topic,
        test_followup_after_spending_report_does_not_inherit_fake_item,
        test_general_storage_question_about_bought_item_stays_general,
        test_receipt_price_question_about_store_word_is_not_general_advice,
        test_category_words_do_not_trigger_spending_report_inside_item_query,
        test_monthly_correction_wins_after_weekly_history,
        test_store_breakdown_word_table_does_not_match_vegetable,
        test_receipt_action_classifier_handles_harder_phrasings,
        test_rice_size_does_not_make_rice_query_unknown,
        test_answer_guard_removes_semantically_wrong_low_price_candidate,
        test_hard_release_matrix,
        test_price_memory_keeps_full_history_for_instant_price_check,
        test_price_memory_uses_unit_price_for_multi_each_lines,
        test_price_memory_uses_unit_price_for_weighted_goat_keema_lines,
        test_weighted_price_memory_profile_uses_unit_price_not_line_total,
        test_weighted_price_memory_derives_unit_price_when_missing,
        test_scan_normalization_merges_wrapped_ice_cream_item,
        test_scan_normalization_splits_ice_cream_tail_from_weighted_chili,
        test_price_memory_rejects_weak_long_product_match,
        test_semantic_duplicate_receipt_detects_retake_without_same_image_hash,
        test_price_memory_rejects_restaurant_items_with_weak_grocery_matches,
        test_scan_media_type_uses_actual_png_bytes_not_jpeg_default,
    ]
    for test in tests:
        test()
    print("Hard agent regression tests passed.")
