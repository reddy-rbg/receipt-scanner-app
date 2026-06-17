import sys
import types


dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.modules["dotenv"] = dotenv

anthropic = types.ModuleType("anthropic")
anthropic.Anthropic = lambda api_key=None: None
sys.modules["anthropic"] = anthropic

supabase_module = types.ModuleType("supabase")
supabase_module.Client = object
supabase_module.create_client = lambda *args, **kwargs: None
sys.modules["supabase"] = supabase_module

from app.services import agent, agent_workflow


def test_workflow_attaches_orchestration_trace():
    original_run_agent = agent.run_agent
    try:
        agent.run_agent = lambda *args, **kwargs: {
            "response": "ok",
            "tools_used": [],
            "rag_trace": {"intent": "test"},
        }
        result = agent_workflow.run_agent_workflow(
            "what is the cost per type of cilantro, red chili, tomato, cucumber, is it cheaper?",
            [],
            user_id="u1",
        )
    finally:
        agent.run_agent = original_run_agent

    workflow = result["rag_trace"]["workflow"]
    assert result["response"] == "ok"
    assert workflow["engine"] in {"deterministic", "langgraph"}
    assert workflow["extracted_items"] == ["cilantro", "red chili", "tomato", "cucumber"]
    assert workflow["stages"] == ["prepare", "execute", "finalize"]


if __name__ == "__main__":
    test_workflow_attaches_orchestration_trace()
