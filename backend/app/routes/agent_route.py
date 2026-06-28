# ─────────────────────────────────────────
# routes/agent_route.py
# AI Agent endpoint
# ─────────────────────────────────────────

import asyncio
import hashlib
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.services import agent as agent_service
from app.services import agent_workflow

router = APIRouter(prefix="/agent", tags=["agent"])
conversation_store: dict[str, list[dict[str, str]]] = {}
_TOKEN_USER_CACHE: dict[str, tuple[float, str]] = {}
TOKEN_USER_CACHE_SECONDS = 300


class AgentMessage(BaseModel):
    message: str
    session_id: str = "default"
    guest_session_id: str | None = None


class ClearMessage(BaseModel):
    session_id: str = "default"
    guest_session_id: str | None = None


class AgentFeedback(BaseModel):
    session_id: str = "default"
    guest_session_id: str | None = None
    message: str
    response: str | None = None
    expected_response: str | None = None
    rating: str | None = None
    correction_note: str | None = None
    alias_term: str | None = None
    alias_value: str | None = None


def get_user_id(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.replace("Bearer ", "").strip()
    if not token or token == "guest":
        return None
    cache_key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cached = _TOKEN_USER_CACHE.get(cache_key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        from app.config import supabase
        response = supabase.auth.get_user(token)
        if response and response.user:
            user_id = str(response.user.id)
            _TOKEN_USER_CACHE[cache_key] = (time.monotonic() + TOKEN_USER_CACHE_SECONDS, user_id)
            return user_id
    except Exception as e:
        print(f"[agent] Token error: {e}")
    return None


async def handle_agent_request(request: Request, body: AgentMessage):
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    user_id = await asyncio.to_thread(get_user_id, request)
    guest_session_id = None if user_id else (body.guest_session_id or body.session_id)

    if not user_id and (not guest_session_id or guest_session_id in {"guest", "default"}):
        raise HTTPException(status_code=400, detail="Valid guest_session_id is required for guest agent requests.")

    owner_key = user_id or guest_session_id
    session_key = f"{owner_key}:{body.session_id}"
    history = conversation_store.get(session_key, [])

    try:
        result = await asyncio.to_thread(
            agent_workflow.run_agent_workflow,
            message,
            history,
            user_id,
            guest_session_id,
        )
        if not isinstance(result, dict):
            result = {"response": str(result), "tools_used": []}

        response_text = result.get("response") or "I could not generate a response. Please try again."
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response_text})
        conversation_store[session_key] = history[-20:]

        return {
            "success": True,
            "response": response_text,
            "answer_card": result.get("answer_card"),
            "tools_used": result.get("tools_used", []),
            "thinking": result.get("thinking", ""),
            "rag_trace": result.get("rag_trace"),
            "turn": len(conversation_store[session_key]) // 2,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[agent] Agent error: {e}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@router.post("")
async def run_agent_no_slash(request: Request, body: AgentMessage):
    return await handle_agent_request(request, body)


@router.post("/")
async def run_agent_with_slash(request: Request, body: AgentMessage):
    return await handle_agent_request(request, body)


@router.post("/chat")
async def run_agent_chat(request: Request, body: AgentMessage):
    return await handle_agent_request(request, body)


@router.post("/clear")
async def clear_conversation(request: Request, body: ClearMessage):
    user_id = get_user_id(request)
    guest_session_id = None if user_id else (body.guest_session_id or body.session_id)
    owner_key = user_id or guest_session_id
    session_key = f"{owner_key}:{body.session_id}"
    conversation_store.pop(session_key, None)
    return {"success": True, "message": "Conversation cleared."}


@router.post("/feedback")
async def agent_feedback(request: Request, body: AgentFeedback):
    user_id = get_user_id(request)
    guest_session_id = None if user_id else (body.guest_session_id or body.session_id)

    if not user_id and (not guest_session_id or guest_session_id in {"guest", "default"}):
        raise HTTPException(status_code=400, detail="Valid guest_session_id is required for guest feedback.")

    learned_alias = False
    if body.alias_term and body.alias_value:
        agent_service.save_owner_alias_families(
            [{body.alias_term, body.alias_value}],
            user_id=user_id,
            guest_session_id=guest_session_id,
        )
        learned_alias = True

    try:
        from app.config import supabase
        supabase.table("agent_feedback").insert({
            "user_id": user_id,
            "guest_session_id": guest_session_id,
            "session_id": body.session_id,
            "message": body.message,
            "response": body.response,
            "expected_response": body.expected_response,
            "rating": body.rating,
            "correction_note": body.correction_note,
            "alias_term": body.alias_term,
            "alias_value": body.alias_value,
            "status": "new",
        }).execute()
    except Exception as e:
        print(f"[agent_feedback] Feedback table not available: {e}")

    agent_service.clear_owner_learning_caches(user_id=user_id, guest_session_id=guest_session_id)

    return {
        "success": True,
        "learned_alias": learned_alias,
        "message": "Feedback saved. Future answers can use this correction for adaptive ranking, and aliases apply immediately when provided.",
    }
