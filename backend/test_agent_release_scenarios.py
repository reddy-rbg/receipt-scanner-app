"""Release safety checks for ReceiptAI Agent.

Run this before publishing backend changes. These tests prefer a safe
"no clear match" answer over a confident wrong price.
"""

import test_agent_rag_regression as base
from app.services import agent


SCENARIOS = [
    {
        "query": "keema cheap in ?",
        "must_include": ["GOAT KEEMA"],
        "must_not_include": ["CINNAMON", "MANGO", "PEPPER CHICKEN"],
    },
    {
        "query": "What cheap keema",
        "must_include": ["GOAT KEEMA"],
        "must_not_include": ["CINNAMON", "MANGO"],
    },
    {
        "query": "mutton keema best price",
        "must_include": ["GOAT KEEMA"],
        "must_not_include": ["GOAT LEG", "CHICKEN KEEMA DOSA", "CINNAMON"],
    },
    {
        "query": "best price for maggi",
        "must_include": ["MAGGI MASALA NOODLES"],
        "must_not_include": ["MANGO"],
    },
    {
        "query": "What clantro cheap pice",
        "must_include": ["CILANTRO"],
        "must_not_include": ["OYSTER", "MANGO", "MAGGI"],
    },
    {
        "query": "Egg best price",
        "must_include": ["EGGS 12CT"],
        "must_not_include": ["CILANTRO", "MAGGI"],
    },
    {
        "query": "best price for saffron",
        "must_include": ["No clear saffron purchase found"],
        "must_not_include": ["CINNAMON", "Best price found"],
    },
]


def answer_for(query: str) -> str:
    rag = agent.retrieve_item_events(query)
    return agent.deterministic_item_answer(query, rag)


def test_release_scenarios_are_safe():
    base.setup_module()
    failures = []
    for scenario in SCENARIOS:
        answer = answer_for(scenario["query"])
        answer_upper = answer.upper()
        for expected in scenario["must_include"]:
            if expected.upper() not in answer_upper:
                failures.append(f"{scenario['query']}: missing {expected!r}\n{answer}")
        for forbidden in scenario["must_not_include"]:
            if forbidden.upper() in answer_upper:
                failures.append(f"{scenario['query']}: included forbidden {forbidden!r}\n{answer}")
    assert not failures, "\n\n".join(failures)


if __name__ == "__main__":
    test_release_scenarios_are_safe()
    print("Agent release safety scenarios passed.")
