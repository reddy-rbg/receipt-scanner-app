"""Regressions for canonical receipt events, evidence counts, and fast paths."""

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
from app.services.agent_architecture import finalize_agent_result


def event(receipt_id, line_index, name, date, price, origin="receipt_items"):
    return {
        "event_origin": origin,
        "receipt_id": receipt_id,
        "line_index": line_index,
        "item_original": name,
        "item_normalized": agent.normalize_text(name),
        "store": "India Mart",
        "date": date,
        "created_at": date,
        "quantity": 1,
        "unit": "each",
        "line_price": price,
    }


def with_events(rows, callback):
    original_events = agent.fetch_owner_item_events
    original_feedback = agent.fetch_owner_feedback_examples
    original_blocklist = agent.fetch_owner_blocklist
    original_embeddings = agent.fetch_embedding_rank_boosts
    original_aliases = agent.fetch_owner_alias_families
    agent.fetch_owner_item_events = lambda user_id=None, guest_session_id=None, limit=1000: rows
    agent.fetch_owner_feedback_examples = lambda user_id=None, guest_session_id=None: []
    agent.fetch_owner_blocklist = lambda user_id=None, guest_session_id=None: set()
    agent.fetch_embedding_rank_boosts = lambda *args, **kwargs: {}
    agent.fetch_owner_alias_families = lambda user_id=None, guest_session_id=None: []
    try:
        return callback()
    finally:
        agent.fetch_owner_item_events = original_events
        agent.fetch_owner_feedback_examples = original_feedback
        agent.fetch_owner_blocklist = original_blocklist
        agent.fetch_embedding_rank_boosts = original_embeddings
        agent.fetch_owner_alias_families = original_aliases


def test_cross_source_line_index_differences_collapse_to_one_purchase():
    normalized = event("r1", 17, "CILANTRO", "2026-05-23", 0.59, "receipt_items")
    receipt_json = event("r1", 2, "CILANTRO", "2026-05-23", 0.59, "receipt_json")
    normalized["date"] = "May 23, 2026"
    normalized["quantity"] = 3
    receipt_json["source_page"] = 1
    receipt_json["source_bbox"] = [10, 20, 100, 40]
    unique = agent.dedupe_item_events([normalized, receipt_json])
    assert len(unique) == 1


def test_duplicate_candidates_do_not_push_other_dates_or_mutton_cuts_out():
    duplicate_keema = [
        event("r1", index, "GOAT KEEMA", "2026-05-23", 14.98, "receipt_json" if index % 2 else "receipt_items")
        for index in range(20)
    ]
    rows = duplicate_keema + [
        event("r2", 1, "GOAT LEG", "2026-05-05", 20.15),
        event("r3", 1, "GOAT KEEMA", "2026-04-14", 12.49),
    ]

    rag = with_events(rows, lambda: agent.retrieve_item_events("mutton", limit=250))
    assert len(rag["events"]) == 3
    assert {row["item_original"] for row in rag["events"]} == {"GOAT KEEMA", "GOAT LEG"}
    assert {row["date"] for row in rag["events"]} == {"2026-05-23", "2026-05-05", "2026-04-14"}


def test_ram_uses_the_mutton_goat_lamb_family():
    rows = [
        event("r1", 1, "GOAT KEEMA", "2026-05-23", 14.98),
        event("r2", 1, "GOAT LEG", "2026-05-05", 20.15),
    ]
    rag = with_events(rows, lambda: agent.retrieve_item_events("ram", limit=250))
    assert {row["item_original"] for row in rag["events"]} == {"GOAT KEEMA", "GOAT LEG"}


def test_when_question_uses_canonical_pipeline_and_lists_all_dates():
    rows = [
        event("r1", 1, "GOAT KEEMA", "2026-05-23", 14.98),
        event("r1", 99, "GOAT KEEMA", "2026-05-23", 14.98, "receipt_json"),
        event("r2", 1, "GOAT LEG", "2026-05-05", 20.15),
    ]
    result = with_events(rows, lambda: agent.run_agent("When did I buy mutton?", []))
    response = result["response"].lower()
    assert "found 2 mutton purchases" in response
    assert "2026-05-23" in response
    assert "2026-05-05" in response
    assert result["rag_trace"]["retrieval"] == "hybrid_item_rag"
    assert result["rag_trace"]["matched_event_count"] == 2


def test_numeric_purchase_claim_is_corrected_to_canonical_event_count():
    result = finalize_agent_result({
        "response": "I found 11 mutton purchases. Most recent: today.",
        "rag_trace": {
            "intent": "item_purchase_date",
            "retrieval": "hybrid_item_rag",
            "matched_event_count": 5,
            "evidence": [{"receipt_id": index} for index in range(1, 6)],
        },
    }, "when did I buy mutton")
    assert "found 5 mutton purchases" in result["response"].lower()
    assert result["rag_trace"]["numeric_claim_corrected"] is True


def test_clear_known_item_query_skips_semantic_model_call():
    original = agent.semantic_extract_items
    agent.semantic_extract_items = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("planner called"))
    try:
        understood = agent.understand_user_query("When did I buy mutton?", [])
    finally:
        agent.semantic_extract_items = original
    assert understood["item_query"] == "mutton"


def test_exact_match_skips_vector_network_call():
    rows = [event("r1", 1, "CILANTRO", "2026-05-23", 0.59)]
    def retrieve_without_vector():
        agent.fetch_embedding_rank_boosts = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("vector RPC called"))
        return agent.retrieve_item_events("cilantro", limit=50)

    rag = with_events(rows, retrieve_without_vector)
    assert len(rag["events"]) == 1
    assert rag["retrieval_pipeline"]["vector_search_skipped_for_exact_match"] is True


def test_empty_purchase_history_skips_vector_network_call():
    def retrieve_without_vector():
        agent.fetch_embedding_rank_boosts = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("vector RPC called"))
        return agent.retrieve_item_events("ram", limit=250)

    rag = with_events([], retrieve_without_vector)
    assert rag["events"] == []
    assert rag["retrieval_pipeline"]["vector_search_skipped_without_candidates"] is True


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Canonical event checks passed: {len(tests)}")
