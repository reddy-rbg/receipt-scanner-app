"""Wide conversational scenario checks for ReceiptAI Agent.

These tests cover the answer routing that users feel most: short questions,
typos, follow-ups, spending reports, shopping planning, before-buy checks, and
general food questions. The goal is to catch precise-answer regressions before
they reach the app.
"""

import test_agent_hard_scenarios as hard
from app.services import agent


def setup_module():
    hard.setup_module()


def answer(message, history=None):
    return agent.run_agent(message, history or [])


def assert_response(message, *, includes=(), excludes=(), card_type=None, history=None):
    result = answer(message, history)
    text = result["response"].lower()
    failures = []
    for expected in includes:
        if expected.lower() not in text:
            failures.append(f"missing {expected!r}")
    for forbidden in excludes:
        if forbidden.lower() in text:
            failures.append(f"included {forbidden!r}")
    if card_type is not None:
        actual = (result.get("answer_card") or {}).get("type")
        if actual != card_type:
            failures.append(f"card type {actual!r}, expected {card_type!r}")
    assert not failures, f"{message!r}: {', '.join(failures)}\n{text}"
    return result


def test_category_questions_return_category_answers_not_fake_items():
    assert_response(
        "What types of meat i bought",
        includes=["meat purchases found", "goat"],
        excludes=["no clear types meat", "price history", "prepared restaurant dishes"],
    )
    assert_response(
        "what meat",
        includes=["meat purchases found"],
        excludes=["best price found", "price history", "prepared restaurant dishes"],
    )
    assert_response(
        "waht meat",
        includes=["meat purchases found"],
        excludes=["no clear waht meat", "price history", "prepared restaurant dishes"],
    )
    assert_response(
        "cheap veggies",
        includes=["cilantro"],
        excludes=["spending snapshot", "receipt categories"],
    )
    assert_response(
        "waht vegitables",
        includes=["vegetable"],
        excludes=["no clear waht", "more detail", "general"],
    )
    assert_response(
        "waht mutton did i buy please",
        includes=["meat purchases found"],
        excludes=["no clear", "price memory"],
    )
    assert_response(
        "WAT TYPES OF GOAT MEAT now",
        includes=["meat purchases found"],
        excludes=["no clear", "price memory"],
    )


def test_best_price_questions_stay_short_and_evidence_based():
    assert_response(
        "cheap meat",
        includes=["cheapest meat found", "price", "store"],
        excludes=["prepared restaurant dishes", "price history", "pepper chicken"],
        card_type="category_best_price",
    )
    assert_response(
        "cilantro cheap",
        includes=["best price found", "cilantro", "$0.59"],
        excludes=["price history", "highest seen", "difference"],
        card_type="best_price",
    )
    assert_response(
        "mutton cheap",
        includes=["best price found"],
        excludes=["pepper chicken", "cinnamon", "mango"],
        card_type="best_price",
    )


def test_item_history_questions_show_history_only_when_asked():
    assert_response(
        "Keema",
        includes=["keema"],
        excludes=["cinnamon", "mango", "pepper chicken"],
    )
    assert_response(
        "goat keema price history",
        includes=["price history", "goat keema"],
        excludes=["cinnamon", "mango", "pepper chicken"],
    )
    assert_response(
        "show keema list",
        includes=["price history", "keema"],
        excludes=["cinnamon", "mango"],
    )


def test_followups_reuse_recent_item_but_not_report_topics():
    item_history = [
        {"role": "user", "content": "Keema"},
        {"role": "assistant", "content": "I found 12 keema purchases."},
    ]
    assert_response(
        "Show the list",
        history=item_history,
        includes=["price history", "keema"],
        excludes=["no clear list", "cilantro"],
    )

    report_history = [{"role": "user", "content": "show category-wise spending"}]
    resolved = agent.resolve_followup_message("where cheapest", report_history)
    assert resolved == "where cheapest"


def test_receipt_evidence_followups_from_screenshot_routes():
    assert_response(
        "Goat keema 19 buys ?",
        includes=["goat keema"],
        excludes=["goat keema 19 buys", "no clear"],
    )

    history = [
        {"role": "user", "content": "Goat keema 19 buys ?"},
        {"role": "assistant", "content": "I found 12 goat keema purchases."},
    ]
    assert_response(
        "Show me",
        history=history,
        includes=["price history", "goat keema"],
        excludes=["goat keema 19 buys", "no clear"],
    )
    assert_response(
        "Give me an evidence",
        history=history,
        includes=["price history", "goat keema"],
        excludes=["clarify", "shopping, cooking", "no clear"],
    )
    assert_response(
        "Show me all receipts",
        includes=["recent receipts"],
        excludes=["no clear receipts", "purchase found"],
    )
    assert_response(
        "Receipts with keema",
        includes=["price history", "keema"],
        excludes=["receipts keema", "no clear"],
    )


def test_list_them_followup_uses_count_answer_topic():
    history = [
        {"role": "user", "content": "How many times the keema is bought"},
        {"role": "assistant", "content": "You bought keema 12 times."},
    ]
    assert_response(
        "List them",
        history=history,
        includes=["price history", "keema"],
        excludes=["no clear them", "them keema", "them purchases", "purchase found in your receipts"],
    )

    history = [
        {"role": "user", "content": "Keema"},
        {"role": "assistant", "content": "I found 12 keema purchases."},
    ]
    assert_response(
        "Give list",
        history=history,
        includes=["price history", "keema"],
        excludes=["no clear list", "purchase found in your receipts"],
    )


def test_frequent_items_phrases_route_to_repeat_summary():
    for question in [
        "Most frequently bought items",
        "Most bought items",
        "Frequently bought products",
        "Top purchased items",
        "Items I buy most often",
        "What item i am frequently purchasing",
        "what item i am frequently",
        "what item i am frequently purpasing",
        "waht item i bought most",
        "top products i purchased",
    ]:
        result = answer(question)
        text = (result.get("response") or "").lower()
        trace = result.get("rag_trace") or {}
        assert trace.get("intent") == "item_price_trends", f"{question}: {trace}"
        assert "no clear" not in text, f"{question}: {text}"
        assert "purchase found in your receipts" not in text, f"{question}: {text}"
        assert any(term in text for term in ["repeat", "price trend", "bought", "purchase"]), f"{question}: {text}"


def test_followup_pronouns_keep_recent_item_context():
    history = [
        {"role": "user", "content": "Keema"},
        {"role": "assistant", "content": "I found 12 keema purchases."},
    ]
    for followup in ["List them", "Show those", "Give me those receipts", "Show all of them"]:
        result = answer(followup, history=history)
        text = (result.get("response") or "").lower()
        assert "keema" in text, f"{followup}: {text}"
        assert "price history" in text or "receipt" in text, f"{followup}: {text}"
        assert "them keema" not in text, f"{followup}: {text}"
        assert "those keema" not in text, f"{followup}: {text}"
        assert "no clear" not in text, f"{followup}: {text}"


def test_receipt_word_typos_do_not_become_fake_items():
    assert_response(
        "show all recepits",
        includes=["recent receipts"],
        excludes=["no clear recepits", "purchase found"],
    )
    assert_response(
        "find recipt with keema",
        includes=["price history", "keema"],
        excludes=["recipt keema", "no clear recipt"],
    )
    history = [
        {"role": "user", "content": "Receipts with keema"},
        {"role": "assistant", "content": "Price history:\n1. GOAT KEEMA - $11.54/lb at India Mart (5/5/26, qty 0.77)"},
    ]
    assert_response(
        "Open receipt",
        history=history,
        includes=["keema"],
        excludes=["no clear open", "open keema", "clarify"],
    )


def test_typos_aliases_and_unknown_items_are_safe():
    assert_response(
        "clantro cheap",
        includes=["cilantro", "$0.59"],
        excludes=["cinnamon", "mango", "maggi"],
        card_type="best_price",
    )
    assert_response(
        "magie cheep prise",
        includes=["maggi masala noodles"],
        excludes=["mango", "cilantro"],
    )
    assert_response(
        "saffron cheap",
        includes=["no clear saffron"],
        excludes=["cinnamon", "cheapest found", "best price found"],
    )
    assert_response(
        "zaffron cheep?",
        includes=["no clear zaffron"],
        excludes=["cinnamon", "cheapest found"],
    )


def test_price_checks_extract_amount_and_product_correctly():
    assert_response(
        "is $5 good for eggs",
        includes=["current price", "eggs"],
        excludes=["cilantro", "maggi"],
    )
    assert_response(
        "is 14.99 good for goat keema",
        includes=["current price", "goat keema"],
        excludes=["cilantro", "cinnamon"],
    )
    assert_response(
        "current market price compare",
        includes=["market comparison needs a product"],
        excludes=["goat", "cilantro"],
    )


def test_reports_and_planning_route_to_the_right_summary():
    assert_response(
        "Give me this month items to purchase based on my receipts",
        includes=["shopping plan"],
        excludes=["monthly spending", "purchase found"],
        card_type="shopping_plan",
    )
    assert_response(
        "Want i should in next cmg month",
        includes=["shopping plan"],
        excludes=["clarify", "meal ideas", "something else"],
        card_type="shopping_plan",
    )
    assert_response(
        "Shopping",
        includes=["shopping plan"],
        excludes=["what do you need help", "product recommendations"],
        card_type="shopping_plan",
    )
    assert_response(
        "Products",
        includes=["price memory"],
        excludes=["no clear products", "purchase found"],
        card_type="price_memory",
    )
    assert_response(
        "items pls",
        includes=["price memory"],
        excludes=["no clear", "purchase found"],
        card_type="price_memory",
    )
    assert_response(
        "Items now",
        includes=["price memory"],
        excludes=["no clear", "purchase found"],
        card_type="price_memory",
    )
    assert_response(
        "avoid above prices",
        includes=["price memory"],
        excludes=["no clear", "purchase found"],
        card_type="price_memory",
    )
    assert_response(
        "show my price memory",
        includes=["price memory"],
        excludes=["spending snapshot"],
        card_type="price_memory",
    )
    assert_response(
        "Give table of stores by spend",
        includes=["store breakdown"],
        excludes=["purchase found", "price history"],
    )
    assert_response(
        "monthly spending report",
        includes=["monthly"],
        excludes=["purchase found", "best price found"],
    )
    assert_response(
        "Month Report?",
        includes=["monthly"],
        excludes=["purchase found", "best price found"],
    )
    assert_response(
        "weekly spending",
        includes=["weekly spending"],
        excludes=["monthly expense analysis", "purchase found"],
    )
    assert_response(
        "What items i am mostly purpased",
        includes=["price trends"],
        excludes=["no clear", "am mostly"],
    )
    assert_response(
        "What item i am frequently purchasing",
        includes=["price trends"],
        excludes=["no clear", "am frequently"],
    )
    assert_response(
        "Vegitables",
        includes=["cilantro"],
        excludes=["no clear vegitables", "spending snapshot", "maggi", "noodles", "goat keema", "pepper chicken"],
    )


def test_general_food_questions_do_not_search_receipt_prices():
    boiled = assert_response(
        "how long to boil eggs",
        includes=["egg"],
        excludes=["purchase found", "best price found", "price history"],
    )
    assert boiled["rag_trace"]["agent_architecture"] == "adaptive_agentic_hybrid_rag_multimodal_graph_memory"
    assert boiled["rag_trace"]["agent_mode"] == "general"
    assert boiled["rag_trace"]["retrieval"] == "general_context_rag"
    assert boiled["rag_trace"]["evidence_count"] >= 1
    assert boiled["rag_trace"]["openable_evidence"] is False
    assert boiled["rag_trace"]["strict_receipt_grounding"] is False

    cilantro = assert_response(
        "how to store cilantro fresh",
        includes=["cilantro"],
        excludes=["best price found", "price history", "purchase found"],
    )
    assert cilantro["rag_trace"]["agent_mode"] == "general"


def test_dual_mode_general_questions_do_not_use_receipt_rag():
    scenarios = [
        ("What is basmati rice?", ["basmati rice"], ["best price found", "purchase found", "price history"]),
        ("Is goat meat healthy?", ["goat meat", "healthy"], ["goat keema", "best price found", "purchase found"]),
        ("How to cook goat meat?", ["goat", "cook"], ["goat keema", "purchase found"]),
        ("How to make grocery shopping cheaper?", ["shopping", "cheaper"], ["shopping plan", "price memory", "purchase found"]),
        ("What vegetables go with chicken curry?", ["vegetables", "chicken curry"], ["meat purchases", "best price found", "purchase found"]),
        ("WHAT VEGETABLES GO WITH CHICKEN CURRY", ["vegetables"], ["meat purchases", "best price found", "purchase found"]),
    ]
    for message, includes, excludes in scenarios:
        result = assert_response(message, includes=includes, excludes=excludes)
        trace = result.get("rag_trace") or {}
        assert trace["agent_architecture"] == "adaptive_agentic_hybrid_rag_multimodal_graph_memory"
        assert trace["agent_mode"] == "general"
        assert trace["intent"] == "general_advice"
        assert trace["retrieval"] == "general_context_rag"
        assert trace["evidence_count"] >= 1
        assert trace["openable_evidence"] is False
        assert all(row.get("source") == "curated_general_knowledge" for row in trace["evidence"])


def test_dual_mode_receipt_questions_still_use_receipt_rag():
    receipt = assert_response(
        "Where did I buy eggs cheapest?",
        includes=["eggs"],
        excludes=["boil", "recipe"],
        card_type="best_price",
    )
    trace = receipt.get("rag_trace") or {}
    assert trace["agent_architecture"] == "adaptive_agentic_hybrid_rag_multimodal_graph_memory"
    assert trace["agent_mode"] == "receipt"
    assert trace["retrieval"] == "hybrid_item_rag"
    assert trace["openable_evidence"] is True


def test_shopping_and_receipt_evidence_cards_include_openable_receipts():
    shopping = assert_response(
        "Help me plan my next grocery shopping trip",
        includes=["shopping plan"],
        card_type="shopping_plan",
    )
    shopping_rows = shopping["answer_card"]["rows"]
    assert shopping_rows
    assert all(row.get("receipt_id") for row in shopping_rows[:5])

    price_memory = assert_response(
        "show my price memory and avoid-above prices",
        includes=["price memory"],
        card_type="price_memory",
    )
    memory_rows = price_memory["answer_card"]["rows"]
    assert memory_rows
    assert all(row.get("receipt_id") for row in memory_rows[:5])


def test_agent_uses_evidence_backed_hybrid_rag_contract():
    item = assert_response(
        "cilantro cheap",
        includes=["best price found", "cilantro"],
        card_type="best_price",
    )
    item_trace = item.get("rag_trace") or {}
    assert item_trace["architecture"] == "evidence_backed_hybrid_rag"
    assert item_trace["retrieval"] == "hybrid_item_rag"
    assert item_trace["normalized_query"] == "cilantro"
    assert item_trace["evidence_count"] >= 1
    assert item_trace["openable_evidence"] is True
    assert item_trace["strict_receipt_grounding"] is True

    category = assert_response(
        "cheap meat",
        includes=["cheapest meat found"],
        card_type="category_best_price",
    )
    category_trace = category.get("rag_trace") or {}
    assert category_trace["retrieval"] == "structured_category_rag"
    assert category_trace["normalized_query"] == "meat"
    assert category_trace["openable_evidence"] is True

    shopping = assert_response(
        "Shopping",
        includes=["shopping plan"],
        card_type="shopping_plan",
    )
    shopping_trace = shopping.get("rag_trace") or {}
    assert shopping_trace["retrieval"] == "structured_receipt_memory"
    assert shopping_trace["intent"] == "shopping_plan"
    assert shopping_trace["openable_evidence"] is True


def test_multimodal_evidence_metadata_flows_to_answer_card():
    event = {
        "receipt_id": "vision-r1",
        "line_index": 2,
        "store": "India Mart",
        "date": "5/23/26",
        "item_original": "CILANTRO",
        "item_normalized": "cilantro",
        "quantity": 1,
        "unit": "each",
        "unit_price": 0.59,
        "line_price": 0.59,
        "source_page": 0,
        "source_bbox": {"x": 20, "y": 120, "w": 240, "h": 28},
        "source_text": "CILANTRO 0.59",
        "source_image_hash": "image-hash",
        "match_confidence": "high",
    }
    original_events = agent.fetch_owner_item_events
    try:
        agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: [event]
        result = agent.run_agent("cilantro cheap", [])
        card = result["answer_card"]
        trace = result["rag_trace"]
        assert card["multimodal_evidence"]["available"] is True
        assert card["multimodal_evidence"]["can_highlight_line"] is True
        assert card["multimodal_evidence"]["bbox"]["x"] == 20
        assert trace["multimodal_evidence"] is True
        assert trace["highlightable_evidence"] is True
    finally:
        agent.fetch_owner_item_events = original_events


def test_graph_rag_memory_answers_relationship_questions():
    together = assert_response(
        "What items do I usually buy together?",
        includes=["items commonly bought together"],
        excludes=["purchase found", "best price found"],
    )
    together_trace = together.get("rag_trace") or {}
    assert together_trace["retrieval"] == "graph_rag_memory"
    assert together_trace["intent"] == "graph_memory"

    categories = assert_response(
        "What categories do I buy from India Mart?",
        includes=["categories from india mart"],
        excludes=["purchase found", "best price found"],
    )
    assert categories["rag_trace"]["retrieval"] == "graph_rag_memory"


def test_conversation_matrix_smoke():
    scenarios = [
        ("egg best price", ["eggs 12ct"], ["egg noodles", "cilantro"]),
        ("bhindi best price", ["okra"], ["cilantro", "mango"]),
        ("best dahi price", ["dahi"], ["cilantro", "mango"]),
        ("cheap noodles", ["noodles"], ["mango"]),
        ("rose pink prem price", ["rose pink"], ["cilantro", "goat"]),
        ("basmati rice cheap", ["basmati rice"], ["cilantro"]),
        ("Analyze spending", ["spending snapshot"], ["purchase found"]),
        ("Show category-wise spending", ["receipt categories"], ["weekly spending"]),
        ("Which store did I spend the most at?", ["india mart"], ["purchase found"]),
    ]
    for message, includes, excludes in scenarios:
        assert_response(message, includes=includes, excludes=excludes)


if __name__ == "__main__":
    setup_module()
    tests = [
        test_category_questions_return_category_answers_not_fake_items,
        test_best_price_questions_stay_short_and_evidence_based,
        test_item_history_questions_show_history_only_when_asked,
        test_followups_reuse_recent_item_but_not_report_topics,
        test_receipt_evidence_followups_from_screenshot_routes,
        test_list_them_followup_uses_count_answer_topic,
        test_frequent_items_phrases_route_to_repeat_summary,
        test_followup_pronouns_keep_recent_item_context,
        test_receipt_word_typos_do_not_become_fake_items,
        test_typos_aliases_and_unknown_items_are_safe,
        test_price_checks_extract_amount_and_product_correctly,
        test_reports_and_planning_route_to_the_right_summary,
        test_general_food_questions_do_not_search_receipt_prices,
        test_dual_mode_general_questions_do_not_use_receipt_rag,
        test_dual_mode_receipt_questions_still_use_receipt_rag,
        test_shopping_and_receipt_evidence_cards_include_openable_receipts,
        test_agent_uses_evidence_backed_hybrid_rag_contract,
        test_multimodal_evidence_metadata_flows_to_answer_card,
        test_graph_rag_memory_answers_relationship_questions,
        test_conversation_matrix_smoke,
    ]
    for test in tests:
        test()
    print("Wide agent scenario tests passed.")
