"""Regression checks for the single-pass ReceiptAI agent architecture."""

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

from app.services import agent, agent_workflow
from app.services.agent_contracts import AgentIntent, IntentPlan, intent_plan_from_understanding


def test_intent_plan_preserves_raw_question_and_operation():
    plan = intent_plan_from_understanding(
        "When did I buy mutton?",
        "When did I buy mutton?",
        {
            "intent": "item_price",
            "item_query": "mutton",
            "items": [],
            "is_receipt_question": True,
        },
    )
    assert plan.raw_message == "When did I buy mutton?"
    assert plan.intent == AgentIntent.PURCHASE_DATE
    assert plan.item_query == "mutton"


def test_prepared_plan_skips_second_interpretation():
    plan = IntentPlan(
        raw_message="hello",
        resolved_message="hello",
        intent=AgentIntent.HELP,
        is_receipt_question=False,
        legacy_intent="help",
    )
    original = agent.understand_user_query
    agent.understand_user_query = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("execution interpreted an already planned turn")
    )
    try:
        result = agent.run_agent(
            "hello",
            [],
            intent_plan=plan,
            message_is_resolved=True,
        )
    finally:
        agent.understand_user_query = original
    assert "ask" in result["response"].lower()


def test_workflow_passes_one_plan_into_execution():
    plan = IntentPlan(
        raw_message="hello",
        resolved_message="hello",
        intent=AgentIntent.HELP,
        is_receipt_question=False,
        legacy_intent="help",
    )
    calls = {"plan": 0, "execute": 0}
    original_build = agent.build_intent_plan
    original_run = agent.run_agent

    def fake_build(*_args, **_kwargs):
        calls["plan"] += 1
        return plan

    def fake_run(*_args, **kwargs):
        calls["execute"] += 1
        assert kwargs.get("intent_plan") is plan
        assert kwargs.get("message_is_resolved") is True
        return {"response": "ok", "tools_used": [], "rag_trace": {}}

    agent.build_intent_plan = fake_build
    agent.run_agent = fake_run
    try:
        final = agent_workflow._run_deterministic_workflow({
            "message": "hello",
            "conversation_history": [],
            "workflow_trace": {},
        })
    finally:
        agent.build_intent_plan = original_build
        agent.run_agent = original_run

    assert final["result"]["response"] == "ok"
    assert calls == {"plan": 1, "execute": 1}


def test_ttl_cache_reuses_data_without_request_wide_clear():
    cache = {}
    key = ("user", "abc", 100)
    agent._ttl_cache_set(cache, key, [1, 2, 3])
    assert agent._ttl_cache_get(cache, key) == [1, 2, 3]


def test_aggregate_receipt_total_honors_analytics_plan_before_item_rag():
    receipts = [
        {"id": 138, "store": "Test Grocery Mart", "date": "2026-09-02", "total": 12.94, "items": []},
        {"id": 139, "store": "Test Wholesale Market", "date": "2026-09-01", "total": 64.80, "items": []},
    ]
    original_receipts = agent.fetch_owner_receipts
    original_events = agent.fetch_owner_item_events
    agent.fetch_owner_receipts = lambda *_args, **_kwargs: receipts
    agent.fetch_owner_item_events = lambda *_args, **_kwargs: []
    try:
        question = "Across both test receipts, how much did I pay in total?"
        plan = agent.build_intent_plan(question, question, [])
        assert plan.intent == AgentIntent.RECEIPT_ANALYTICS
        assert not plan.item_query
        result = agent.run_agent(question, [], intent_plan=plan, message_is_resolved=True)
    finally:
        agent.fetch_owner_receipts = original_receipts
        agent.fetch_owner_item_events = original_events

    assert "$77.74" in result["response"]
    assert "purchase found" not in result["response"].lower()
    assert result["rag_trace"]["retrieval"] == "structured_receipt_aggregation"


def test_item_specific_total_remains_an_item_question():
    question = "How much did I pay for eggs in total?"
    plan = agent.build_intent_plan(question, question, [])
    assert plan.intent != AgentIntent.RECEIPT_ANALYTICS
    assert plan.item_query == "eggs"


if __name__ == "__main__":
    tests = [
        test_intent_plan_preserves_raw_question_and_operation,
        test_prepared_plan_skips_second_interpretation,
        test_workflow_passes_one_plan_into_execution,
        test_ttl_cache_reuses_data_without_request_wide_clear,
        test_aggregate_receipt_total_honors_analytics_plan_before_item_rag,
        test_item_specific_total_remains_an_item_question,
    ]
    for test in tests:
        test()
    print(f"Single-pass architecture checks passed: {len(tests)}")
