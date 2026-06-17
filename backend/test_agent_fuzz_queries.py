"""Generated messy-query checks for ReceiptAI item understanding.

These are deterministic fuzz tests: many user-like variations, same output on
every run. They protect the app from the manual screenshot-by-screenshot loop.
"""

import itertools

import test_agent_rag_regression as rag


agent = rag.agent


FORBIDDEN_ITEM_WORDS = {
    "best",
    "cheap",
    "cheaper",
    "cheapest",
    "cost",
    "costs",
    "price",
    "prices",
    "rate",
    "rates",
    "type",
    "types",
    "where",
    "compare",
    "please",
    "tell",
    "find",
    "vs",
    "or",
}


ITEM_SETS = [
    [
        ("cilantro", ["cilantro", "cilnatro", "culantro", "clantro"]),
        ("red chili", ["red chili", "red chilly", "red chilies", "red chile"]),
        ("tomato", ["tomato", "tomatto", "tomatoes", "tomatoe"]),
        ("cucumber", ["cucumber", "cucmber", "cucumbers", "cumcumber"]),
    ],
    [
        ("tomato", ["tomato", "tomatoes", "tomatto"]),
        ("cucumber", ["cucumber", "cucumbers", "cucamber"]),
        ("onion", ["onion", "onions"]),
        ("carrot", ["carrot", "carrots"]),
    ],
    [
        ("cinnamon stick", ["cinnamon stick", "cinnamon sticks", "cinnamom stick"]),
        ("saffron", ["saffron", "safforn", "saffran"]),
        ("turmeric", ["turmeric", "tumeric", "turmric"]),
        ("cardamom", ["cardamom", "cardamon", "cardemon"]),
    ],
    [
        ("goat keema", ["goat keema", "goat kheema", "goat kherma"]),
        ("cilantro", ["cilantro", "cilntro", "culantro"]),
        ("cinnamon stick", ["cinnamon stick", "cinnamon sticks"]),
    ],
]


SEPARATORS = [
    " ",
    ", ",
    " and ",
    " / ",
    " + ",
    " vs ",
]


WRAPPERS = [
    "what is the cost per type of {items} is it cheaper",
    "best rates for {items}",
    "where is cheap {items}",
    "compare {items}",
    "please tell me cheapest price for {items} or not",
    "price listing:\n{items}",
]


def setup_module():
    rag.setup_module()


def _variant_round(item_set, round_index):
    typed = []
    expected = []
    for expected_name, variants in item_set:
        typed.append(variants[round_index % len(variants)])
        expected.append(expected_name)
    return typed, expected


def generated_clean_multi_item_cases(limit=None):
    count = 0
    max_rounds = max(len(variants) for item_set in ITEM_SETS for _, variants in item_set)
    for item_set, round_index, separator, wrapper in itertools.product(
        ITEM_SETS,
        range(max_rounds),
        SEPARATORS,
        WRAPPERS,
    ):
        typed, expected = _variant_round(item_set, round_index)
        query = wrapper.format(items=separator.join(typed))
        yield query, expected
        count += 1
        if limit is not None and count >= limit:
            return


def assert_items_are_clean(items):
    words = set(" ".join(items).split())
    leaked = words & FORBIDDEN_ITEM_WORDS
    assert not leaked, f"query words leaked into items: {sorted(leaked)} from {items}"


def test_generated_clean_multi_item_queries_extract_expected_items():
    checked = 0
    for query, expected in generated_clean_multi_item_cases():
        items = agent.extract_shopping_list_items(query)
        assert items == expected, f"{query!r} -> {items!r}, expected {expected!r}"
        assert_items_are_clean(items)

        understood = agent.deterministic_multi_item_understanding(query)
        assert understood.get("items") == expected, f"{query!r} -> {understood!r}"
        checked += 1

    assert checked >= 500


def test_generated_answer_cards_keep_requested_items_clean():
    for query, expected in list(generated_clean_multi_item_cases(limit=24)):
        result = agent.run_agent(query, [])
        rows = (result.get("answer_card") or {}).get("rows") or []
        requested = [row.get("requested_item") for row in rows]
        assert requested == expected, f"{query!r} -> {requested!r}, expected {expected!r}"
        assert_items_are_clean(requested)


def test_uncertain_generated_queries_route_to_claude_correction():
    uncertain_cases = [
        (
            "what is cost cilanxro red chili tomato cucumber cheaper",
            ["cilantro", "red chili", "tomato", "cucumber"],
        ),
        (
            "best rates for tomzzx cucumberx onion carrot",
            ["tomato", "cucumber", "onion", "carrot"],
        ),
        (
            "compare cinnzzmon stick saffron turmeric cardamom",
            ["cinnamon stick", "saffron", "turmeric", "cardamom"],
        ),
    ]

    original_semantic_extract = agent.semantic_extract_items
    try:
        for query, expected in uncertain_cases:
            extracted = agent.extract_shopping_list_items(query)
            assert agent.deterministic_items_need_semantic_review(query, extracted), (
                query,
                extracted,
            )
            assert agent.deterministic_multi_item_understanding(query) == {}

            agent.semantic_extract_items = lambda message, history=None, expected=expected: {
                "intent": "item_price",
                "canonical_message": f"best price for {', '.join(expected)}",
                "item_query": expected[0],
                "items": expected,
                "category": "",
                "is_receipt_question": True,
                "semantic_extraction": True,
                "semantic_confidence": 0.93,
            }
            result = agent.run_agent(query, [])
            rows = (result.get("answer_card") or {}).get("rows") or []
            assert [row.get("requested_item") for row in rows] == expected
    finally:
        agent.semantic_extract_items = original_semantic_extract


if __name__ == "__main__":
    setup_module()
    test_generated_clean_multi_item_queries_extract_expected_items()
    test_generated_answer_cards_keep_requested_items_clean()
    test_uncertain_generated_queries_route_to_claude_correction()
    print("Agent fuzz query tests passed.")
