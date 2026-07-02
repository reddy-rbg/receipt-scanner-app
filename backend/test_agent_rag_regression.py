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

from app.services import agent


EVENTS = [
    {
        "receipt_id": "1",
        "line_index": 1,
        "store": "India Mart",
        "date": "May 9",
        "created_at": "2026-05-09",
        "code": None,
        "item_original": "Chicken Keema Dosa",
        "item_normalized": "chicken keema dosa",
        "quantity": 1,
        "unit": "each",
        "line_price": 15.99,
    },
    {
        "receipt_id": "2",
        "line_index": 2,
        "store": "India Mart",
        "date": "May 9",
        "created_at": "2026-05-09",
        "code": None,
        "item_original": "Pepper Chicken",
        "item_normalized": "pepper chicken",
        "quantity": 1,
        "unit": "each",
        "line_price": 34.98,
    },
    {
        "receipt_id": "3",
        "line_index": 3,
        "store": "India Mart",
        "date": "5/5/26",
        "created_at": "2026-05-05",
        "code": None,
        "item_original": "GOAT LEG",
        "item_normalized": "goat leg",
        "quantity": 1.26,
        "unit": "lb",
        "line_price": 20.15,
    },
    {
        "receipt_id": "4",
        "line_index": 4,
        "store": "India Mart",
        "date": "5/5/26",
        "created_at": "2026-05-05",
        "code": None,
        "item_original": "GOAT KEEMA",
        "item_normalized": "goat keema",
        "quantity": 0.77,
        "unit": "lb",
        "line_price": 11.54,
    },
    {
        "receipt_id": "5",
        "line_index": 5,
        "store": "India Mart",
        "date": "5/19/26",
        "created_at": "2026-05-19",
        "code": None,
        "item_original": "CILANTRO",
        "item_normalized": "cilantro",
        "quantity": 1,
        "unit": "each",
        "line_price": 0.59,
    },
    {
        "receipt_id": "6",
        "line_index": 6,
        "store": "Whole Foods",
        "date": "5/11/26",
        "created_at": "2026-05-11",
        "code": None,
        "item_original": "EGGS 12CT",
        "item_normalized": "eggs 12ct",
        "quantity": 1,
        "unit": "each",
        "line_price": 3.49,
    },
    {
        "receipt_id": "7",
        "line_index": 7,
        "store": "India Mart",
        "date": "5/19/26",
        "created_at": "2026-05-19",
        "code": None,
        "item_original": "BHAIYAJI GREEK MANGO 341G",
        "item_normalized": "bhaiyaji greek mango 341g",
        "quantity": 1,
        "unit": "each",
        "line_price": 3.99,
    },
    {
        "receipt_id": "8",
        "line_index": 8,
        "store": "India Mart",
        "date": "5/19/26",
        "created_at": "2026-05-19",
        "code": None,
        "item_original": "MAGGI MASALA NOODLES",
        "item_normalized": "maggi masala noodles",
        "quantity": 1,
        "unit": "each",
        "line_price": 1.49,
    },
    {
        "receipt_id": "9",
        "line_index": 9,
        "store": "NWA Bharath Bazaar",
        "date": "15-May-2026",
        "created_at": "2026-05-15",
        "code": None,
        "item_original": "LAXMI CINNAMON ROUND 200G",
        "item_normalized": "laxmi cinnamon round 200g",
        "quantity": 1,
        "unit": "each",
        "line_price": 6.99,
    },
]


def setup_module():
    agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: EVENTS
    agent.fetch_owner_receipts = lambda user_id=None, guest_session_id=None, limit=300: [
        {
            "id": "r1",
            "store": "India Mart",
            "date": "2026-05-19",
            "created_at": "2026-05-19",
            "total": 25.0,
            "items": [{"name": event["item_original"], "price": event["line_price"]} for event in EVENTS],
        }
    ]
    agent.fetch_owner_alias_families = lambda user_id=None, guest_session_id=None: []
    agent.fetch_owner_feedback_examples = lambda user_id=None, guest_session_id=None: []
    agent.save_owner_alias_families = lambda families, user_id=None, guest_session_id=None: None


def event_names(query):
    return [event["item_original"] for event in agent.retrieve_item_events(query)["events"]]


def test_specific_mutton_does_not_return_chicken():
    names = event_names("Where the cheap mutton")
    assert names == ["GOAT LEG", "GOAT KEEMA"]


def test_when_did_i_buy_mutton_answers_purchase_dates_not_price_table():
    understood = agent.local_understand_user_query("When did I buy mutton?")
    assert understood["item_query"] == "mutton"
    assert understood.get("items") in (None, [])
    assert agent.looks_like_shopping_list_price_request("When did I buy mutton?") is False

    result = agent.run_agent("When did I buy mutton?", [])
    response = result["response"].lower()
    assert "most recent" in response
    assert "5/5/26" in response
    assert "goat leg" in response
    assert "when" not in str(result.get("answer_card") or {}).lower()


def test_complete_price_history_of_buying_eggs_does_not_create_buying_item():
    query = "show me complete price history of buying eggs"
    plan = agent.build_intent_plan(query, query, [])
    assert plan.intent.value == "price_history"
    assert plan.item_query == "eggs"
    assert list(plan.items) == ["eggs"]
    assert agent.extract_shopping_list_items(query) == ["eggs"]

    result = agent.run_agent(query, [], intent_plan=plan, message_is_resolved=True)
    response = result["response"].lower()
    assert "eggs 12ct" in response
    assert "price history" in response
    assert "buying" not in response
    assert result.get("answer_card") is None


def test_generic_meat_can_return_all_meat_items():
    names = event_names("What is the cheap meat price")
    assert "GOAT KEEMA" in names
    assert "Pepper Chicken" in names


def test_category_meat_answer_excludes_prepared_dishes():
    result = agent.run_agent("Cheapest meat bought", [])
    response = result["response"].lower()
    assert "cheapest meat found" in response
    assert "goat keema" in response or "goat leg" in response
    assert "lowest meat prices" not in response
    assert "chicken keema dosa" not in response
    assert "pepper chicken" not in response
    assert "prepared restaurant dishes" not in response


def test_what_meat_uses_category_answer_not_item_history():
    result = agent.run_agent("what meat", [])
    response = result["response"].lower()
    assert "meat purchases found" in response
    assert "best price found" not in response
    assert "price history" not in response
    assert "chicken keema dosa" not in response
    assert "pepper chicken" not in response


def test_category_word_with_specific_item_keeps_specific_item():
    result = agent.run_agent("cheap vegetable cilantro", [])
    response = result["response"].lower()
    assert "cilantro" in response
    assert "meat purchases" not in response
    assert "receipt categories" not in response


def test_each_quantity_unit_price_is_used_for_best_price():
    event = {
        "item_original": "3 CILANTRO",
        "store": "India Mart",
        "date": "5/23/26",
        "quantity": 3,
        "unit": "each",
        "line_price": 1.77,
        "explicit_quantity": True,
    }
    assert agent.price_memory_event_price(event) == 0.59
    assert agent.event_price_text(event) == "$0.59"


def test_weighted_item_derives_unit_price_when_saved_unit_price_is_line_total():
    event = {
        "item_original": "GOAT KEEMA",
        "store": "India Mart",
        "date": "5/5/26",
        "quantity": 0.77,
        "unit": "lb",
        "unit_price": 11.54,
        "line_price": 11.54,
    }
    assert agent.price_memory_event_price(event) == 14.99
    assert agent.event_price_text(event) == "$14.99/lb"


def test_duplicate_history_rows_are_collapsed():
    event = {
        "receipt_id": "dup",
        "line_index": 1,
        "item_original": "CILANTRO",
        "store": "India Mart",
        "date": "5/23/26",
        "quantity": 3,
        "unit": "each",
        "line_price": 1.77,
        "explicit_quantity": True,
        "match_confidence": "high",
        "match_score": 1.0,
    }
    rag = {"query": "cilantro cheap", "normalized_query": "cilantro", "events": [event, dict(event)]}
    answer = agent.deterministic_item_answer("cilantro cheap", rag)
    assert answer.count("CILANTRO") == 1
    assert "$0.59" in answer
    assert "$1.77" not in answer


def test_best_price_answer_does_not_dump_history_unless_asked():
    cilantro_pack = {
        "receipt_id": "pack",
        "line_index": 1,
        "item_original": "3 CILANTRO",
        "store": "India Mart",
        "date": "5/23/26",
        "quantity": 3,
        "unit": "each",
        "line_price": 1.77,
        "explicit_quantity": True,
        "match_confidence": "high",
        "match_score": 1.0,
    }
    single = {
        "receipt_id": "single",
        "line_index": 1,
        "item_original": "CILANTRO",
        "store": "India Mart",
        "date": "5/19/26",
        "quantity": 1,
        "unit": "each",
        "line_price": 0.59,
        "match_confidence": "high",
        "match_score": 1.0,
    }
    rag = {"query": "cilantro cheap", "normalized_query": "cilantro", "events": [cilantro_pack, single]}
    answer = agent.deterministic_item_answer("clantro cheap", rag).lower()
    assert "best price found" in answer
    assert "$0.59" in answer
    assert "price history" not in answer
    assert "highest seen" not in answer
    assert "difference" not in answer


def test_best_price_returns_evidence_card():
    result = agent.run_agent("clantro cheap", [])
    card = result.get("answer_card")
    assert card
    assert card["type"] == "best_price"
    assert card["item"] == "CILANTRO"
    assert card["price"] == "$0.59"
    assert card["store"] == "India Mart"
    assert card["receipt_id"]


def test_category_best_price_returns_evidence_card():
    result = agent.run_agent("cheapest meat bought", [])
    card = result.get("answer_card")
    assert card
    assert card["type"] == "category_best_price"
    assert card["price"].endswith("/lb")
    assert not card.get("note")


def test_history_answer_includes_history_when_asked():
    rag = agent.retrieve_item_events("cilantro price history")
    answer = agent.deterministic_item_answer("cilantro price history", rag).lower()
    assert "price history" in answer or "i found" in answer


def test_multi_item_best_price_table_splits_requested_items():
    result = agent.run_agent(
        "Get me the best price listing in tabular form to buy\n"
        "Mutton\n"
        "Beef leg\n"
        "Cilantro\n"
        "Cinnamon stick",
        [],
    )
    response = result["response"].lower()
    assert "best receipt prices" in response
    assert "goat keema" in response
    assert "cilantro" in response
    assert "laxmi cinnamon" in response
    assert "tabular form mutton" not in response
    assert "no clear" not in response
    assert result["answer_card"]["type"] == "shopping_list_prices"
    assert result["rag_trace"]["intent"] in {"shopping_list_price", "multi_item_price_from_classifier"}


def test_messy_multi_item_request_with_commas_uses_table_path():
    result = agent.run_agent(
        "Get me the best price in tabular form to wher to but from for velow isted items "
        "chappals, cilntro, mutton kherma, vlcinnamonm sticks 100gms",
        [],
    )
    response = result["response"].lower()
    assert "best receipt prices" in response
    assert "cilantro" in response
    assert "goat keema" in response
    assert "laxmi cinnamon" in response
    assert "no clear tabular" not in response


def test_cost_per_type_words_do_not_become_requested_items():
    items = agent.extract_shopping_list_items(
        "what is the cost per type of cilantro, red chili, tomato, cucumber, is it cheaper?"
    )
    assert items == ["cilantro", "red chili", "tomato", "cucumber"]


def test_space_separated_cost_request_keeps_chili_and_cucumber_separate():
    items = agent.extract_shopping_list_items(
        "what is the cost per type of cilantro red chili tomato cucumber is it cheaper"
    )
    assert items == ["cilantro", "red chili", "tomato", "cucumber"]


def test_dangling_unit_tail_does_not_become_requested_item():
    items = agent.extract_shopping_list_items("how much cost keema p")
    assert items == ["keema"]

    result = agent.run_agent("how much cost keema p", [])
    assert "keema lb" not in result["response"].lower()
    assert result["rag_trace"]["normalized_query"] == "keema"


def test_screenshot_cost_request_with_typo_stays_fast_multi_item():
    original_semantic_extract = agent.semantic_extract_items
    try:
        agent.semantic_extract_items = lambda message, history=None: (_ for _ in ()).throw(
            AssertionError("semantic extraction should not run for deterministic multi-item requests")
        )
        result = agent.run_agent(
            "what is the cost per type of cilnatro red chili tomato cucumber is it cheaper",
            [],
        )
    finally:
        agent.semantic_extract_items = original_semantic_extract

    rows = result["answer_card"]["rows"]
    assert [row["requested_item"] for row in rows] == [
        "cilantro",
        "red chili",
        "tomato",
        "cucumber",
    ]
    assert result["rag_trace"]["intent"] == "multi_item_price_from_classifier"


def test_messy_cost_request_variants_extract_same_items():
    cases = [
        "cost per type cilnatro red chilly tomatto cucmber cheaper",
        "best rates for culantro, red chile, tomatoe and cumcumber",
        "where is cheap cilantro red chili tomato cucumber",
        "price listing:\ncilnatro\nred chilly\ntomatto\ncucamber",
    ]
    for query in cases:
        items = agent.extract_shopping_list_items(query)
        assert items == ["cilantro", "red chili", "tomato", "cucumber"], query


def test_plural_produce_words_are_singularized_before_splitting():
    cases = {
        "what is the cost per type of cilantro red chilies tomato cucumber is it cheaper": [
            "cilantro",
            "red chili",
            "tomato",
            "cucumber",
        ],
        "best prices tomatoes cucumbers chilies potatoes onions carrots": [
            "tomato",
            "cucumber",
            "chili",
            "potato",
            "onion",
            "carrot",
        ],
        "cilantro tomatoes cucumbers red chilies cheaper": [
            "cilantro",
            "tomato",
            "cucumber",
            "red chili",
        ],
        "best rates for red chiles tomatoes cucumbers": [
            "red chili",
            "tomato",
            "cucumber",
        ],
    }
    for query, expected in cases.items():
        assert agent.extract_shopping_list_items(query) == expected, query
        assert agent.deterministic_multi_item_understanding(query)["items"] == expected


def test_plural_chili_query_never_returns_combined_requested_rows():
    result = agent.run_agent(
        "what is the cost per type of cilantro red chilies tomato cucumber is it cheaper",
        [],
    )
    rows = result["answer_card"]["rows"]
    requested = [row["requested_item"] for row in rows]
    assert requested == ["cilantro", "red chili", "tomato", "cucumber"]
    assert "tomato cucumber" not in requested
    assert not any(item.startswith("cilantro red") for item in requested)
    assert result["answer_card"]["type"] == "shopping_list_prices"


def test_query_words_never_become_items_in_cost_request():
    query = (
        "please tell me what is the best cheapest cost per type rate for "
        "cilnatro red chilly tomatto cucumber and is it cheaper"
    )
    items = agent.extract_shopping_list_items(query)
    assert items == ["cilantro", "red chili", "tomato", "cucumber"]
    forbidden = {"please", "tell", "best", "cheapest", "cost", "type", "rate", "cheaper"}
    assert not (set(" ".join(items).split()) & forbidden)


def test_unknown_items_in_multi_item_lists_are_preserved_as_missing_rows():
    cases = {
        "price for cilantro fakeitem saffron": ["cilantro", "fakeitem", "saffron"],
        "compare tomato cucumber fakeitem": ["tomato", "cucumber", "fakeitem"],
        "where is cheap dragonfruit cilantro": ["dragonfruit", "cilantro"],
    }
    for query, expected in cases.items():
        assert agent.extract_shopping_list_items(query) == expected, query

    result = agent.run_agent("price for cilantro fakeitem saffron", [])
    rows = result["answer_card"]["rows"]
    assert [row["requested_item"] for row in rows] == ["cilantro", "fakeitem", "saffron"]
    assert any(row["requested_item"] == "fakeitem" and row["price"] == "Not found" for row in rows)


def test_fast_multi_item_understanding_shapes_screenshot_query():
    data = agent.deterministic_multi_item_understanding(
        "what is the cost per type of cilnatro red chili tomato cucumber is it cheaper"
    )
    assert data["items"] == ["cilantro", "red chili", "tomato", "cucumber"]
    assert data["intent"] == "item_price"
    assert data["item_query"] == "cilantro"


def test_uncertain_deterministic_items_require_semantic_review():
    query = "what is cost cilanxro red chili tomato cucumber cheaper"
    items = agent.extract_shopping_list_items(query)
    assert items == ["cilanxro red chili", "tomato", "cucumber"]
    assert agent.deterministic_items_need_semantic_review(query, items)
    assert agent.deterministic_multi_item_understanding(query) == {}


def test_uncertain_multi_item_query_uses_claude_semantic_correction():
    original_semantic_extract = agent.semantic_extract_items
    try:
        agent.semantic_extract_items = lambda message, history=None: {
            "intent": "item_price",
            "canonical_message": "best price for cilantro, red chili, tomato, cucumber",
            "item_query": "cilantro",
            "items": ["cilantro", "red chili", "tomato", "cucumber"],
            "category": "",
            "is_receipt_question": True,
            "semantic_extraction": True,
            "semantic_confidence": 0.94,
        }
        result = agent.run_agent(
            "what is cost cilanxro red chili tomato cucumber cheaper",
            [],
        )
    finally:
        agent.semantic_extract_items = original_semantic_extract

    rows = result["answer_card"]["rows"]
    assert [row["requested_item"] for row in rows] == [
        "cilantro",
        "red chili",
        "tomato",
        "cucumber",
    ]
    assert result["rag_trace"]["intent"] == "multi_item_price_from_classifier"


def test_comparison_separators_do_not_stick_to_items():
    cases = {
        "compare cilantro vs tomato vs cucumber vs red chili": ["cilantro", "tomato", "cucumber", "red chili"],
        "cilantro tomato cucumber red chili cheaper or not": ["cilantro", "tomato", "cucumber", "red chili"],
        "best price for cilantro / red chili / tomato / cucumber": ["cilantro", "red chili", "tomato", "cucumber"],
        "best price for cilantro + red chili + tomato + cucumber": ["cilantro", "red chili", "tomato", "cucumber"],
        "price for cilantro & red chili & tomato & cucumber": ["cilantro", "red chili", "tomato", "cucumber"],
    }
    for query, expected in cases.items():
        assert agent.extract_shopping_list_items(query) == expected, query


def test_leading_exclusion_clause_keeps_following_requested_items():
    items = agent.extract_shopping_list_items(
        "do not include potato, price cilantro red chili tomato cucumber"
    )
    assert items == ["cilantro", "red chili", "tomato", "cucumber"]


def test_culantro_typo_maps_to_cilantro_in_multi_item_request():
    items = agent.extract_shopping_list_items("The best price for culantro and tomato")
    assert items == ["cilantro", "tomato"]


def test_semantic_multi_item_understanding_overrides_rule_splitter():
    original_semantic_extract = agent.semantic_extract_items
    original_deterministic_multi = agent.deterministic_multi_item_understanding
    try:
        agent.deterministic_multi_item_understanding = lambda message: {}
        agent.semantic_extract_items = lambda message, history=None: {
            "intent": "item_price",
            "canonical_message": "best price for cilantro, red chili, tomato, cucumber",
            "item_query": "cilantro",
            "items": ["cilantro", "red chili", "tomato", "cucumber"],
            "category": "",
            "is_receipt_question": True,
            "semantic_extraction": True,
            "semantic_confidence": 0.95,
        }
        result = agent.run_agent(
            "Can you please tell best rates for culantro red chilly tomatto cucumber is it cheap",
            [],
        )
    finally:
        agent.semantic_extract_items = original_semantic_extract
        agent.deterministic_multi_item_understanding = original_deterministic_multi

    rows = result["answer_card"]["rows"]
    assert [row["requested_item"] for row in rows] == [
        "cilantro",
        "red chili",
        "tomato",
        "cucumber",
    ]
    assert result["rag_trace"]["intent"] == "multi_item_price_from_classifier"
    assert "best rates" not in " ".join(row["requested_item"] for row in rows)


def test_space_separated_multi_item_request_splits_on_product_anchors():
    items = agent.extract_shopping_list_items(
        "best prices mutton beef leg cilantro cinnamon stick"
    )
    assert items == ["mutton", "beef leg", "cilantro", "cinnamon stick"]

    result = agent.run_agent(
        "best prices mutton beef leg cilantro cinnamon stick",
        [],
    )
    response = result["response"].lower()
    assert "best receipt prices" in response
    assert "goat keema" in response
    assert "cilantro" in response
    assert "laxmi cinnamon" in response
    assert "no clear best prices mutton" not in response


def test_failed_combined_item_self_heals_into_sub_items():
    result = agent.run_agent(
        "What is clantro sweet potato, coconut price",
        [],
    )
    response = result["response"].lower()
    assert "best receipt prices" in response
    assert "cilantro" in response
    assert "$0.59" in response
    assert "sweetpotato" in response
    assert "coconut" in response
    assert "no clear cilantro sweetpotato coconut" not in response
    rows = result["answer_card"]["rows"]
    assert any(row["requested_item"] == "cilantro" and row["price"] == "$0.59" for row in rows)


def test_mixed_known_unknown_items_do_not_become_one_purchase_claim():
    result = agent.run_agent(
        "what is cilantro coconut saffron price",
        [],
    )
    response = result["response"].lower()
    assert "best receipt prices" in response
    assert "cilantro" in response
    assert "$0.59" in response
    assert "not found in receipts" in response
    assert "i found" not in response
    assert "cilantro coconut saffron purchase" not in response
    rows = result["answer_card"]["rows"]
    assert any(row["requested_item"] == "cilantro" and row["price"] == "$0.59" for row in rows)
    assert any(row["requested_item"] == "coconut" and row["price"] == "Not found" for row in rows)
    assert any(row["requested_item"] == "saffron" and row["price"] == "Not found" for row in rows)


def test_partial_combined_match_recovers_instead_of_claiming_whole_phrase():
    assert agent.looks_like_partial_combined_item_match(
        "cilantro coconut saffron",
        [{"item_original": "CILANTRO"}],
    )
    result = agent.run_agent(
        "show price for cilantro coconut saffron",
        [],
    )
    response = result["response"].lower()
    assert "cilantro coconut saffron purchase" not in response
    assert "cilantro" in response
    assert "$0.59" in response
    assert result["answer_card"]["type"] in {"shopping_list_prices", "adaptive_recovered_prices"}


def test_category_instruction_words_do_not_become_list_items():
    items = agent.extract_shopping_list_items(
        "show vegetable prices but include cilantro tomato potato"
    )
    assert items == ["cilantro", "tomato", "potato"]

    result = agent.run_agent(
        "show vegetable prices but include cilantro tomato potato",
        [],
    )
    response = result["response"].lower()
    assert "vegetable but include" not in response
    assert "cilantro" in response
    assert "tomato" in response
    assert "potato" in response


def test_category_with_include_request_returns_category_plus_named_items():
    result = agent.run_agent(
        "show vegetable prices but include cilantro tomato potato",
        [],
    )
    response = result["response"].lower()
    assert "vegetable prices with requested items" in response
    assert "cilantro" in response
    assert "vegetable but include" not in response
    assert result["rag_trace"]["intent"] == "category_price_with_includes"
    rows = result["answer_card"]["rows"]
    assert any("CILANTRO" in row["item"] for row in rows)
    assert any(row["item"] == "tomato" for row in rows)
    assert any(row["item"] == "potato" for row in rows)


def test_adaptive_recovery_dedupes_same_receipt_line():
    result = agent.run_agent(
        "what did i pay for clantro sweet potato coconut saffron and mutton kherma",
        [],
    )
    rows = result["answer_card"]["rows"]
    goat_rows = [row for row in rows if row.get("item") == "GOAT KEEMA"]
    assert len(goat_rows) == 1
    assert any(row.get("item") == "CILANTRO" for row in rows)
    assert sum(1 for row in rows if row.get("item") == "saffron") == 1
    assert sum(1 for row in rows if row.get("item") == "coconut") == 1


def test_grocery_raw_meat_category_not_treated_as_item_include():
    result = agent.run_agent(
        "find cheapest grocery/raw meat and also include cilantro tomato potato in same table",
        [],
    )
    response = result["response"].lower()
    assert "grocery raw meat - not found" not in response
    assert "goat keema" in response
    assert "cilantro" in response
    assert result["rag_trace"]["intent"] == "category_price_with_includes"


def test_unknown_items_instruction_does_not_become_item():
    result = agent.run_agent(
        "compare price for cilantro tomato potato cinnamon stick but dont count unknown items as bought",
        [],
    )
    response = result["response"].lower()
    assert " as " not in response
    assert "cinnamon" in response
    assert "tomato" in response
    assert "potato" in response
    assert "as - not found" not in response


def test_pantry_request_keeps_round_and_does_not_match_ground_meat():
    items = agent.extract_shopping_list_items(
        "show best pantry prices for rice atta dal ghee cinnamon round"
    )
    assert items == ["rice", "atta", "dal", "ghee", "cinnamon round"]

    result = agent.run_agent(
        "show best pantry prices for rice atta dal ghee cinnamon round",
        [],
    )
    response = result["response"].lower()
    assert "laxmi cinnamon round" in response
    assert "goat keema" not in response


def test_spice_price_request_splits_adjacent_items():
    items = agent.extract_shopping_list_items(
        "what is the price for cinnamon stick saffron turmeric cardamom"
    )
    assert items == ["cinnamon stick", "saffron", "turmeric", "cardamom"]

    result = agent.run_agent(
        "what is the price for cinnamon stick saffron turmeric cardamom",
        [],
    )
    rows = result["answer_card"]["rows"]
    assert [row["requested_item"] for row in rows] == items
    assert any("LAXMI CINNAMON ROUND" in row["match"] for row in rows)


def test_coconut_oil_does_not_match_unrelated_oil_or_masala_noodles():
    extra_events = EVENTS + [
        {
            "receipt_id": "oil",
            "line_index": 1,
            "store": "Royal Smokes",
            "date": "05/27/2026",
            "created_at": "2026-05-27",
            "code": None,
            "item_original": "Oil Burner",
            "item_normalized": "oil burner",
            "quantity": 1,
            "unit": "each",
            "line_price": 4.49,
        }
    ]
    agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: extra_events
    try:
        result = agent.run_agent(
            "did i buy cinnamon saffron garam masala coconut oil, show price if found",
            [],
        )
    finally:
        setup_module()

    response = result["response"].lower()
    assert "oil burner" not in response
    assert "maggi masala noodles" not in response
    assert "coconut oil | not found" in response
    assert "garam masala | not found" in response


def test_vegetable_include_request_excludes_candy_mushroom_match():
    extra_events = EVENTS + [
        {
            "receipt_id": "mushroom-candy",
            "line_index": 1,
            "store": "Central Arkansas Wholesale",
            "date": "19 May 26",
            "created_at": "2026-05-19",
            "code": None,
            "item_original": "ORIGO X CHAPO MAGIC MUSHROOM BLEND 450M 2PK GUMMIES 2CT | TROLLI MEDLEY",
            "item_normalized": "origo x chapo magic mushroom blend 450m 2pk gummies 2ct trolli medley",
            "quantity": 1,
            "unit": "each",
            "line_price": 59.99,
        }
    ]
    agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: extra_events
    try:
        result = agent.run_agent(
            "show vegetable prices and include tomato potato okra eggplant mushroom",
            [],
        )
    finally:
        setup_module()

    response = result["response"].lower()
    assert "origo x chapo" not in response
    assert "trolli" not in response
    assert any(row["item"] == "mushroom" and row["price"] == "Not found" for row in result["answer_card"]["rows"])


def test_hard_exclusion_prompt_does_not_request_excluded_items_or_mushroom_tablets():
    extra_events = EVENTS + [
        {
            "receipt_id": "mushroom-tablets",
            "line_index": 1,
            "store": "Central Arkansas Wholesale",
            "date": "19 May 26",
            "created_at": "2026-05-19",
            "code": None,
            "item_original": "Lil MF's Mushroom Tablets - 25COUNT | FRUIT",
            "item_normalized": "lil mfs mushroom tablets 25count fruit",
            "quantity": 1,
            "unit": "each",
            "line_price": 79.99,
        }
    ]
    agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: extra_events
    query = (
        "show best prices for cinnamon round, ground meat, goat keema, garam masala, "
        "coriander powder, dhania, coconut oil, and mushroom, but do not count oil burner, "
        "mushroom gummies, fried rice, or cooked meals"
    )
    try:
        items = agent.extract_shopping_list_items(query)
        result = agent.run_agent(query, [])
    finally:
        setup_module()

    assert "not oil burner" not in items
    assert "mushroom gummies" not in items
    assert "fried rice" not in items
    assert "or cooked meals" not in items
    assert "mushroom" in items

    response = result["response"].lower()
    assert "mushroom tablets" not in response
    assert "oil burner" not in response
    assert any(row["item"] == "mushroom" and row["price"] == "Not found" for row in result["answer_card"]["rows"])


def test_compare_multi_item_request_keeps_unknown_as_missing_row():
    items = agent.extract_shopping_list_items(
        "compare tomato roma potato onion carrot and unknown veggie"
    )
    assert items == ["tomato roma", "potato", "onion", "carrot", "unknown veggie"]

    result = agent.run_agent(
        "compare tomato roma potato onion carrot and unknown veggie",
        [],
    )
    assert result["answer_card"]["type"] == "shopping_list_prices"
    assert any(row["requested_item"] == "unknown veggie" and row["price"] == "Not found" for row in result["answer_card"]["rows"])


def test_avoid_above_usual_price_routes_to_price_memory():
    assert agent.classify_receipt_action("which items should i avoid buying above my usual price") == "price_memory"
    result = agent.run_agent(
        "which items should i avoid buying above my usual price",
        [],
    )
    assert result["answer_card"]["type"] == "price_memory"
    assert "no clear buying" not in result["response"].lower()


def test_feedback_examples_boost_corrected_receipt_item_rank():
    extra_events = EVENTS + [
        {
            "receipt_id": "tomato-sauce",
            "line_index": 1,
            "store": "Market A",
            "date": "2026-05-28",
            "created_at": "2026-05-28",
            "code": None,
            "item_original": "TOMATO SAUCE",
            "item_normalized": "tomato sauce",
            "quantity": 1,
            "unit": "each",
            "line_price": 2.49,
        },
        {
            "receipt_id": "tomato-roma",
            "line_index": 1,
            "store": "Market B",
            "date": "2026-05-20",
            "created_at": "2026-05-20",
            "code": None,
            "item_original": "TOMATO ROMA",
            "item_normalized": "tomato roma",
            "quantity": 3.07,
            "unit": "lb",
            "line_price": 2.82,
        },
    ]
    agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: extra_events
    agent.fetch_owner_feedback_examples = lambda user_id=None, guest_session_id=None: [
        {
            "message": "what is tomato price",
            "response": "Best price found: TOMATO SAUCE",
            "expected_response": "Use TOMATO ROMA for tomato produce price.",
            "rating": "wrong",
            "correction_note": "Tomato means TOMATO ROMA here, not tomato sauce.",
            "alias_term": None,
            "alias_value": None,
        }
    ]
    try:
        rag = agent.retrieve_item_events("best price for tomato", user_id="u1", limit=5)
    finally:
        setup_module()

    assert rag["events"][0]["item_original"] == "TOMATO ROMA"
    assert rag["events"][0]["learned_rank_adjustment"] > 0


def test_failed_single_item_rag_uses_adaptive_recovery_before_giving_up():
    result = agent.run_agent(
        "Can you find what I paid for clantro sweet potato coconut",
        [],
    )
    response = result["response"].lower()
    assert "best receipt prices" in response
    assert "cilantro" in response
    assert "$0.59" in response
    assert "no clear cilantro sweetpotato coconut" not in response
    assert result["answer_card"]["type"] == "adaptive_recovered_prices"
    assert result["rag_trace"]["intent"] == "adaptive_item_recovery"


def test_keema_query_does_not_return_unrelated_meat():
    names = event_names("what is the cheap price bought keema")
    assert "GOAT KEEMA" in names
    assert "Chicken Keema Dosa" in names
    assert "Pepper Chicken" not in names
    assert "BN CHICKEN LOLLIPOP" not in names
    assert "LAXMI CINNAMON ROUND 200G" not in names


def test_mutton_keema_requires_both_meanings():
    names = event_names("mutton keema best price")
    assert names == ["GOAT KEEMA"]


def test_maggi_does_not_match_mango():
    names = event_names("best price for maggi")
    assert names == ["MAGGI MASALA NOODLES"]
    assert "BHAIYAJI GREEK MANGO 341G" not in names


def test_unknown_specific_item_does_not_fall_back_to_global_cheapest():
    names = event_names("best price for saffron")
    assert names == []


def test_answer_guard_drops_bad_retrieval_rows():
    rag = {
        "query": "What cheap keema",
        "normalized_query": "keema",
        "events": [
            EVENTS[3],
            EVENTS[8],
        ],
    }
    answer = agent.deterministic_item_answer("What cheap keema", rag)
    assert "GOAT KEEMA" in answer
    assert "CINNAMON" not in answer
    assert "Best price found: GOAT KEEMA" in answer


def test_round_is_not_corrected_to_ground_meat():
    cinnamon = {"item_original": "LAXMI CINNAMON ROUND 200G", "match_score": 1.0}
    assert not agent.event_satisfies_required_families(cinnamon, "keema")
    assert not agent.event_has_anchor_evidence(cinnamon, "keema")
    assert agent.verified_match_level(cinnamon, "keema", 1.0) == "none"


def test_verified_match_confidence_is_attached():
    rag = agent.retrieve_item_events("keema cheap in ?")
    assert rag["events"]
    assert all(event.get("match_confidence") in {"high", "medium"} for event in rag["events"])
    assert all("CINNAMON" not in event["item_original"] for event in rag["events"])


def test_contextual_retrieval_pipeline_trace_is_attached():
    original_boosts = agent.fetch_embedding_rank_boosts
    try:
        agent.fetch_embedding_rank_boosts = lambda query, user_id=None, guest_session_id=None: {
            ("4", "4", "goat keema"): 0.12
        }
        rag = agent.retrieve_item_events("goat keema")
    finally:
        agent.fetch_embedding_rank_boosts = original_boosts

    pipeline = rag["retrieval_pipeline"]
    assert pipeline["contextual_embeddings"] is True
    assert pipeline["embedding_model"] == "receiptai-contextual-local-hash-v2"
    assert "structured_sql" in pipeline["hybrid_signals"]
    assert "local_vector" in pipeline["hybrid_signals"]
    assert pipeline["reranker"] == "deterministic evidence reranker"
    assert pipeline["vector_boost_matches"] == 0
    assert pipeline["vector_search_skipped_for_exact_match"] is True


def test_multi_item_retrieval_pipeline_trace_is_attached():
    original_boosts = agent.fetch_embedding_rank_boosts
    try:
        agent.fetch_embedding_rank_boosts = lambda query, user_id=None, guest_session_id=None: {
            ("19", "19", "cilantro"): 0.11
        } if query == "cilantro" else {}
        pipeline = agent.multi_item_retrieval_pipeline_trace(["cilantro", "tomato"])
    finally:
        agent.fetch_embedding_rank_boosts = original_boosts

    assert pipeline["contextual_embeddings"] is True
    assert pipeline["embedding_model"] == "receiptai-contextual-local-hash-v2"
    assert pipeline["vector_boost_matches"] == 1
    assert pipeline["multi_item_queries"] == ["cilantro", "tomato"]


def test_specific_unknown_answer_does_not_show_unrelated_candidates():
    rag = {
        "query": "best price for saffron",
        "normalized_query": "saffron",
        "events": [],
        "closest_candidates": [
            {
                "item": "LAXMI CINNAMON ROUND 200G",
                "store": "NWA Bharath Bazaar",
                "date": "15-May-2026",
                "price": 6.99,
                "match_score": 0.5,
            }
        ],
    }
    answer = agent.deterministic_item_answer("best price for saffron", rag)
    assert answer == "No clear saffron purchase found in your receipts."
    assert "CINNAMON" not in answer


def test_category_question_without_price_word_uses_rag():
    assert agent.should_use_item_rag("What is the meat")
    names = event_names("What is the meat")
    assert "GOAT KEEMA" in names
    assert "Pepper Chicken" in names


def test_incomplete_cheapest_question_is_global_price_question():
    assert agent.looks_like_global_price_question("What is the cheap")


def test_short_followup_uses_recent_item_topic():
    history = [{"role": "user", "content": "mutton"}]
    resolved = agent.resolve_followup_message("where cheapest", history)
    assert resolved == "where cheapest mutton"


def test_misspelled_item_price_query_does_not_become_global_cheapest():
    assert not agent.looks_like_global_price_question("What is clantro cheap pice")
    names = event_names("What is clantro cheap pice")
    assert names == ["CILANTRO"]


def test_new_item_after_previous_topic_does_not_reuse_old_topic():
    history = [{"role": "user", "content": "What clantro cheap"}]
    resolved = agent.resolve_followup_message("Egg best price", history)
    assert resolved == "Egg best price"
    names = [
        event["item_original"]
        for event in agent.retrieve_item_events(resolved)["events"]
    ]
    assert names == ["EGGS 12CT"]


def test_understanding_can_canonicalize_messy_language():
    message = agent.canonicalize_message_with_understanding(
        "huevo barato",
        {"intent": "item_price", "item_query": "eggs", "category": ""},
    )
    assert message == "best price for eggs"


def test_run_agent_uses_understood_item_without_old_topic_leakage():
    original_understand = agent.understand_user_query
    try:
        agent.understand_user_query = lambda message, history=None: (
            {"intent": "item_price", "item_query": "eggs", "category": ""}
            if message == "huevo barato"
            else {}
        )
        result = agent.run_agent(
            "huevo barato",
            [{"role": "user", "content": "What clantro cheap"}],
        )
        assert "EGGS 12CT" in result["response"]
        assert "CILANTRO" not in result["response"]
    finally:
        agent.understand_user_query = original_understand


def test_general_advice_uses_general_knowledge():
    original_understand = agent.understand_user_query
    original_general_answer = agent.general_advice_answer
    try:
        agent.understand_user_query = lambda message, history=None: {
            "intent": "general_advice",
            "canonical_message": message,
            "is_receipt_question": False,
        }
        agent.general_advice_answer = lambda message: "Heat milk to 161°F / 72°C for 15 seconds."
        result = agent.run_agent(
            "How much temperature the milk should heat to kill bacteria",
            [],
        )
        assert "Heat milk" in result["response"]
        assert "purchase found" not in result["response"]
        assert result["rag_trace"]["intent"] == "general_advice"
        assert result["rag_trace"]["retrieval"] == "general_knowledge"
        assert result["rag_trace"]["agent_mode"] == "general"
    finally:
        agent.understand_user_query = original_understand
        agent.general_advice_answer = original_general_answer


def test_should_buy_item_uses_receipt_history_without_current_price():
    result = agent.run_agent("should I buy cilantro this week", [])
    response = result["response"].lower()
    assert "based on your receipts" in response
    assert "cilantro" in response
    assert "tell me the item and current price" not in response
    assert "usual price" in response


def test_product_relationship_routing_is_generic_not_item_specific():
    scenarios = [
        "Are cilantro and coriander the same?",
        "Is yogurt another name for curd?",
        "Are moonfruit and sunberry regional names for the same product?",
        "What is the difference between alpha-root and beta-root?",
    ]
    for message in scenarios:
        understanding = agent.local_understand_user_query(message, [])
        assert understanding["intent"] == "product_knowledge", (message, understanding)
        assert understanding["is_receipt_question"] is False
        assert understanding.get("item_query") == ""


def test_product_relationship_question_never_becomes_alias_training_data():
    original_save = agent.save_owner_alias_families
    original_general_answer = agent.general_advice_answer
    try:
        agent.save_owner_alias_families = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a question must not persist an alias")
        )
        agent.general_advice_answer = lambda message, context=None: "These may be regional product names."
        result = agent.run_agent("Are foo-root and bar-root the same?", [])
        assert result["rag_trace"]["intent"] == "product_knowledge"
        assert result["rag_trace"]["retrieval"] == "general_product_knowledge"
    finally:
        agent.save_owner_alias_families = original_save
        agent.general_advice_answer = original_general_answer


def test_unknown_product_aliases_use_semantic_resolver_not_hardcoded_examples():
    original_client = agent.claude_client
    original_google = agent.google_meaning_snippets

    class FakeMessages:
        @staticmethod
        def create(**kwargs):
            return types.SimpleNamespace(content=[types.SimpleNamespace(
                text='{"canonical_name":"sunroot","aliases":["moonroot","vegetable"]}'
            )])

    try:
        agent._PUBLIC_MEANING_CACHE.clear()
        agent.claude_client = types.SimpleNamespace(messages=FakeMessages())
        agent.google_meaning_snippets = lambda query: ""
        families = agent.public_meaning_alias_families("moonroot local name")
        assert families
        assert "sunroot" in families[0]
        assert "moonroot" in families[0]
        assert "vegetable" not in families[0]
    finally:
        agent.claude_client = original_client
        agent.google_meaning_snippets = original_google
        agent._PUBLIC_MEANING_CACHE.clear()


def test_general_advice_heuristic_without_understanding():
    assert agent.looks_like_general_advice_question(
        "How much temperature the milk should heat to kill bacteria"
    )


def test_local_router_handles_general_question_without_claude():
    understanding = agent.understand_user_query(
        "How much temperature the milk should heat to kill bacteria",
        [],
    )
    assert understanding["intent"] == "general_advice"
    assert understanding["is_receipt_question"] is False


def test_local_router_handles_broad_category_question():
    understanding = agent.understand_user_query("What meat did I buy", [])
    assert understanding["intent"] == "category_price"
    assert understanding["category"] == "meat"
    result = agent.run_agent("What meat did I buy", [])
    assert "GOAT KEEMA" in result["response"]
    assert "CILANTRO" not in result["response"]


def test_local_router_handles_multilingual_simple_item_query():
    understanding = agent.understand_user_query("huevo barato", [])
    assert understanding["intent"] == "item_price"
    assert understanding["item_query"] in {"egg", "eggs"}
    result = agent.run_agent("huevo barato", [])
    assert "EGGS 12CT" in result["response"]
    assert "CILANTRO" not in result["response"]


def test_global_cheapest_stays_global_not_help():
    understanding = agent.understand_user_query("what is the cheap", [])
    assert understanding["intent"] == "global_cheapest"
    result = agent.run_agent("what is the cheap", [])
    assert "cheapest" in result["response"].lower()


def test_global_cheapest_does_not_inherit_general_advice_topic():
    history = [
        {
            "role": "user",
            "content": "how much temperature should milk be heated to kill bacteria",
        }
    ]
    resolved = agent.resolve_followup_message("what is cheap", history)
    assert resolved == "what is cheap"
    result = agent.run_agent("what is cheap", history)
    assert "temperature" not in result["response"].lower()
    assert "purchase found" not in result["response"].lower()
    assert "cheapest" in result["response"].lower()


def test_monthly_report_routes_to_overview_not_item_rag():
    result = agent.run_agent("Show my monthly expenses spent analysis as a chart", [])
    assert "monthly expense analysis" in result["response"].lower()
    assert "purchase found" not in result["response"].lower()


def test_weekly_spending_routes_to_weekly_graph():
    original_receipts = agent.fetch_owner_receipts
    try:
        agent.fetch_owner_receipts = lambda user_id=None, guest_session_id=None, limit=300: [
            {"id": "w1", "store": "India Mart", "date": "2026-05-05", "created_at": "2026-05-05", "total": 25.0, "items": []},
            {"id": "w2", "store": "Walmart", "date": "2026-05-12", "created_at": "2026-05-12", "total": 40.0, "items": []},
        ]
        result = agent.run_agent("give a graph spending in week wise", [])
        response = result["response"].lower()
        assert "weekly spending" in response
        assert "2026-05-04 to 2026-05-10" in response
        assert "2026-05-11 to 2026-05-17" in response
        assert "#" not in response
        assert "monthly expense analysis" not in response
        assert "purchase found" not in response
    finally:
        agent.fetch_owner_receipts = original_receipts


def test_weekly_correction_does_not_become_general_advice():
    original_receipts = agent.fetch_owner_receipts
    try:
        agent.fetch_owner_receipts = lambda user_id=None, guest_session_id=None, limit=300: [
            {"id": "w1", "store": "India Mart", "date": "2026-05-05", "created_at": "2026-05-05", "total": 25.0, "items": []},
            {"id": "w2", "store": "Walmart", "date": "2026-05-12", "created_at": "2026-05-12", "total": 40.0, "items": []},
        ]
        history = [{"role": "user", "content": "show my monthly expenses as chart"}]
        result = agent.run_agent("I said week wise not month", history)
        response = result["response"].lower()
        assert "weekly spending" in response
        assert "#" not in response
        assert "meal planning" not in response
        assert "purchase found" not in response
    finally:
        agent.fetch_owner_receipts = original_receipts


def test_price_trends_route_to_repeat_item_analysis():
    result = agent.run_agent("Show me price trends for items I buy regularly", [])
    response = result["response"].lower()
    assert "price trends" in response or "repeat purchases" in response
    assert "weekly spending" not in response
    assert "monthly spending" not in response
    assert "purchase history" not in response


def test_shopping_plan_routes_to_next_purchase_plan():
    result = agent.run_agent("Give me this month items to purchase based on my receipts", [])
    assert "shopping" in result["response"].lower() or "need" in result["response"].lower() or "due" in result["response"].lower()
    assert "purchase found" not in result["response"].lower()


def test_market_comparison_without_item_does_not_pick_random_item():
    result = agent.run_agent("Compare my prices to current market prices and find where I overpaid", [])
    response = result["response"].lower()
    assert "market comparison needs a product" in response
    assert "10.00-oz wick" not in response


def test_price_memory_question_routes_to_price_memory():
    result = agent.run_agent("Show my price memory and avoid-above prices", [])
    assert "price memory" in result["response"].lower()
    assert "spending snapshot" not in result["response"].lower()


def test_analyze_spending_routes_to_overview():
    result = agent.run_agent("Analyze spending", [])
    response = result["response"].lower()
    assert "spending snapshot" in response
    assert "purchase found" not in response


def test_store_most_spend_routes_to_store_totals():
    result = agent.run_agent("Which store did I spend the most at?", [])
    response = result["response"].lower()
    assert "spent the most" in response or "top stores" in response
    assert "india mart" in response
    assert "purchase found" not in response


def test_category_wise_spending_stays_category_only():
    result = agent.run_agent("Show category-wise spending", [])
    response = result["response"].lower()
    assert "receipt categories" in response
    assert "food & grocery" in response
    assert "weekly spending" not in response
    assert "monthly spending" not in response


def test_this_month_expense_chart_stays_current_month():
    result = agent.run_agent("show this month expense chart", [])
    response = result["response"].lower()
    assert "monthly expense analysis" in response
    assert "store breakdown" in response
    assert "month trend" not in response


def test_receipt_action_classifier_locks_common_reports():
    assert agent.classify_receipt_action("Show category-wise spending") == "category_spending"
    assert agent.classify_receipt_action("give graph spending week wise") == "weekly_spending"
    assert agent.classify_receipt_action("Which store did I spend the most at?") == "store_spend"
    assert agent.classify_receipt_action("Show me price trends for items I buy regularly") == "item_price_trends"
    assert agent.classify_receipt_action("What are the top 3 ways I can save money?") == "save_money"
    assert agent.classify_receipt_action("Analyze my spending") == "open_analysis"
    assert agent.classify_receipt_action("Help me plan my next grocery shopping trip") == "shopping_plan"
    assert agent.classify_receipt_action("Which items should I compare before buying?") == "best_deals"
    assert agent.classify_receipt_action("Give table of stores by spend") == "store_breakdown"


def test_vegetable_question_does_not_match_table_substring():
    assert not agent.looks_like_overview_question("What cheap vegetable?")
    result = agent.run_agent("What cheap vegetable?", [])
    response = result["response"].lower()
    assert "cilantro" in response
    assert "spending snapshot" not in response


def test_natural_planning_and_store_table_questions_are_locked():
    result = agent.run_agent("Help me plan my next grocery shopping trip", [])
    assert "purchase found" not in result["response"].lower()

    result = agent.run_agent("Give table of stores by spend", [])
    response = result["response"].lower()
    assert "store breakdown" in response
    assert "purchase found" not in response


def test_unknown_item_cheap_does_not_become_global_cheapest():
    result = agent.run_agent("saffron cheap", [])
    response = result["response"].lower()
    assert "no clear saffron" in response
    assert "cheapest found" not in response
    assert "cinnamon" not in response


def test_general_food_questions_do_not_search_receipts():
    result = agent.run_agent("how long to boil eggs", [])
    response = result["response"].lower()
    assert "egg" in response
    assert "purchase found" not in response

    result = agent.run_agent("how to store cilantro fresh", [])
    response = result["response"].lower()
    assert "cilantro" in response
    assert "best price found" not in response


def test_veggie_alias_matches_vegetable_family():
    result = agent.run_agent("cheap veggies", [])
    response = result["response"].lower()
    assert "cilantro" in response
    assert "spending snapshot" not in response


def test_good_price_with_amount_routes_to_price_check():
    result = agent.run_agent("is $5 good for eggs", [])
    response = result["response"].lower()
    assert "current price" in response
    assert "eggs" in response
    assert "cilantro" not in response


def test_this_month_purchase_question_returns_shopping_plan_card():
    result = agent.run_agent("Give me this month items to purchase based on my receipts", [])
    response = result["response"].lower()
    assert "shopping plan" in response
    assert "monthly spending" not in response
    card = result.get("answer_card")
    assert card and card["type"] == "shopping_plan"
    assert card.get("rows")
    assert card["rows"][0].get("receipt_id")


def test_price_memory_answer_returns_receipt_evidence_card():
    result = agent.run_agent("show my price memory", [])
    card = result.get("answer_card")
    assert card and card["type"] == "price_memory"
    assert card.get("rows")
    assert card["rows"][0].get("receipt_id")


def test_meat_type_question_returns_meat_list_not_missing_item():
    result = agent.run_agent("What types of meat i bought", [])
    response = result["response"].lower()
    assert "meat purchases found" in response
    assert "no clear types meat" not in response
    assert "goat keema" in response or "chicken leg" in response


def test_show_the_list_followup_uses_previous_item_topic():
    history = [
        {"role": "user", "content": "Keema"},
        {"role": "assistant", "content": "I found 12 keema purchases."},
    ]
    result = agent.run_agent("Show the list", history)
    response = result["response"].lower()
    assert "price history" in response
    assert "keema" in response
    assert "no clear list" not in response


if __name__ == "__main__":
    setup_module()
    test_specific_mutton_does_not_return_chicken()
    test_generic_meat_can_return_all_meat_items()
    test_category_meat_answer_excludes_prepared_dishes()
    test_what_meat_uses_category_answer_not_item_history()
    test_category_word_with_specific_item_keeps_specific_item()
    test_each_quantity_unit_price_is_used_for_best_price()
    test_weighted_item_derives_unit_price_when_saved_unit_price_is_line_total()
    test_duplicate_history_rows_are_collapsed()
    test_best_price_answer_does_not_dump_history_unless_asked()
    test_best_price_returns_evidence_card()
    test_category_best_price_returns_evidence_card()
    test_history_answer_includes_history_when_asked()
    test_multi_item_best_price_table_splits_requested_items()
    test_messy_multi_item_request_with_commas_uses_table_path()
    test_cost_per_type_words_do_not_become_requested_items()
    test_space_separated_cost_request_keeps_chili_and_cucumber_separate()
    test_screenshot_cost_request_with_typo_stays_fast_multi_item()
    test_messy_cost_request_variants_extract_same_items()
    test_plural_produce_words_are_singularized_before_splitting()
    test_plural_chili_query_never_returns_combined_requested_rows()
    test_query_words_never_become_items_in_cost_request()
    test_unknown_items_in_multi_item_lists_are_preserved_as_missing_rows()
    test_fast_multi_item_understanding_shapes_screenshot_query()
    test_uncertain_deterministic_items_require_semantic_review()
    test_uncertain_multi_item_query_uses_claude_semantic_correction()
    test_comparison_separators_do_not_stick_to_items()
    test_leading_exclusion_clause_keeps_following_requested_items()
    test_culantro_typo_maps_to_cilantro_in_multi_item_request()
    test_semantic_multi_item_understanding_overrides_rule_splitter()
    test_space_separated_multi_item_request_splits_on_product_anchors()
    test_failed_combined_item_self_heals_into_sub_items()
    test_mixed_known_unknown_items_do_not_become_one_purchase_claim()
    test_partial_combined_match_recovers_instead_of_claiming_whole_phrase()
    test_category_instruction_words_do_not_become_list_items()
    test_category_with_include_request_returns_category_plus_named_items()
    test_adaptive_recovery_dedupes_same_receipt_line()
    test_grocery_raw_meat_category_not_treated_as_item_include()
    test_unknown_items_instruction_does_not_become_item()
    test_pantry_request_keeps_round_and_does_not_match_ground_meat()
    test_spice_price_request_splits_adjacent_items()
    test_coconut_oil_does_not_match_unrelated_oil_or_masala_noodles()
    test_vegetable_include_request_excludes_candy_mushroom_match()
    test_hard_exclusion_prompt_does_not_request_excluded_items_or_mushroom_tablets()
    test_compare_multi_item_request_keeps_unknown_as_missing_row()
    test_avoid_above_usual_price_routes_to_price_memory()
    test_feedback_examples_boost_corrected_receipt_item_rank()
    test_failed_single_item_rag_uses_adaptive_recovery_before_giving_up()
    test_category_question_without_price_word_uses_rag()
    test_incomplete_cheapest_question_is_global_price_question()
    test_short_followup_uses_recent_item_topic()
    test_misspelled_item_price_query_does_not_become_global_cheapest()
    test_new_item_after_previous_topic_does_not_reuse_old_topic()
    test_understanding_can_canonicalize_messy_language()
    test_run_agent_uses_understood_item_without_old_topic_leakage()
    test_general_advice_uses_general_knowledge()
    test_product_relationship_routing_is_generic_not_item_specific()
    test_product_relationship_question_never_becomes_alias_training_data()
    test_unknown_product_aliases_use_semantic_resolver_not_hardcoded_examples()
    test_should_buy_item_uses_receipt_history_without_current_price()
    test_general_advice_heuristic_without_understanding()
    test_local_router_handles_general_question_without_claude()
    test_local_router_handles_broad_category_question()
    test_local_router_handles_multilingual_simple_item_query()
    test_global_cheapest_stays_global_not_help()
    test_global_cheapest_does_not_inherit_general_advice_topic()
    test_monthly_report_routes_to_overview_not_item_rag()
    test_weekly_spending_routes_to_weekly_graph()
    test_weekly_correction_does_not_become_general_advice()
    test_price_trends_route_to_repeat_item_analysis()
    test_shopping_plan_routes_to_next_purchase_plan()
    test_market_comparison_without_item_does_not_pick_random_item()
    test_price_memory_question_routes_to_price_memory()
    test_analyze_spending_routes_to_overview()
    test_store_most_spend_routes_to_store_totals()
    test_category_wise_spending_stays_category_only()
    test_this_month_expense_chart_stays_current_month()
    test_receipt_action_classifier_locks_common_reports()
    test_vegetable_question_does_not_match_table_substring()
    test_natural_planning_and_store_table_questions_are_locked()
    test_unknown_item_cheap_does_not_become_global_cheapest()
    test_general_food_questions_do_not_search_receipts()
    test_veggie_alias_matches_vegetable_family()
    test_good_price_with_amount_routes_to_price_check()
    test_this_month_purchase_question_returns_shopping_plan_card()
    test_price_memory_answer_returns_receipt_evidence_card()
    test_meat_type_question_returns_meat_list_not_missing_item()
    test_show_the_list_followup_uses_previous_item_topic()
    print("Agent RAG regression tests passed.")
