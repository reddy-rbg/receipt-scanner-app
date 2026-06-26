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
    "lb",
    "lbs",
    "pound",
    "pounds",
    "week",
    "month",
    "today",
    "tomorrow",
    "p",
    "pr",
    "pri",
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


def test_adversarial_single_item_noise_does_not_create_fake_items():
    cases = {
        "how much cost keema p": ["keema"],
        "how much cost keema lb": ["keema"],
        "how much cost goat keema lbs": ["goat keema"],
        "waht price cilantro pr": ["cilantro"],
        "best price tomato tomorrow": ["tomato"],
        "should I buy cilantro this week": ["cilantro"],
        "pls price tomato pri": ["tomato"],
        "cost of cucumber today": ["cucumber"],
        "how much did i pay for goat keema yesterday": ["goat keema"],
    }
    for query, expected in cases.items():
        items = agent.extract_shopping_list_items(query)
        assert items == expected, f"{query!r} -> {items!r}"
        assert_items_are_clean(items)


def test_adversarial_multi_item_noise_does_not_leak_rows():
    cases = {
        "best price cilantro p tomato lb cucumber pr": ["cilantro", "tomato", "cucumber"],
        "compare goat keema lbs cilantro pr cinnamon stick today": ["goat keema", "cilantro", "cinnamon stick"],
        "price listing:\ncilantro p\ntomato lb\ncucumber pr": ["cilantro", "tomato", "cucumber"],
        "what cost cilnatro p red chilly lb tomatto pri cucumber today": ["cilantro", "red chili", "tomato", "cucumber"],
    }
    for query, expected in cases.items():
        items = agent.extract_shopping_list_items(query)
        assert items == expected, f"{query!r} -> {items!r}"
        assert_items_are_clean(items)


def test_high_confidence_semantic_understanding_overrides_local_single_item():
    original_semantic_extract = agent.semantic_extract_items
    try:
        agent.semantic_extract_items = lambda message, history=None: {
            "intent": "item_price",
            "canonical_message": "best price for cilantro",
            "item_query": "cilantro",
            "items": ["cilantro"],
            "category": "",
            "is_receipt_question": True,
            "semantic_extraction": True,
            "semantic_confidence": 0.94,
        }
        understood = agent.understand_user_query("waht is the damage for clantro plz", [])
        assert understood["item_query"] == "cilantro"
        assert understood["items"] == ["cilantro"]
        assert understood.get("semantic_extraction") is True
    finally:
        agent.semantic_extract_items = original_semantic_extract


def test_low_confidence_semantic_understanding_does_not_override_local_single_item():
    original_semantic_extract = agent.semantic_extract_items
    try:
        agent.semantic_extract_items = lambda message, history=None: {
            "intent": "item_price",
            "canonical_message": "best price for tomato",
            "item_query": "tomato",
            "items": ["tomato"],
            "category": "",
            "is_receipt_question": True,
            "semantic_extraction": True,
            "semantic_confidence": 0.4,
        }
        understood = agent.understand_user_query("best price for cilantro", [])
        assert understood["item_query"] == "cilantro"
        assert understood.get("semantic_extraction") is not True
    finally:
        agent.semantic_extract_items = original_semantic_extract


if __name__ == "__main__":
    setup_module()
    test_generated_clean_multi_item_queries_extract_expected_items()
    test_generated_answer_cards_keep_requested_items_clean()
    test_uncertain_generated_queries_route_to_claude_correction()
    test_adversarial_single_item_noise_does_not_create_fake_items()
    test_adversarial_multi_item_noise_does_not_leak_rows()
    test_high_confidence_semantic_understanding_overrides_local_single_item()
    test_low_confidence_semantic_understanding_does_not_override_local_single_item()
    print("Agent fuzz query tests passed.")
