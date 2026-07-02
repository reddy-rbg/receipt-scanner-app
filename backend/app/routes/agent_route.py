# ─────────────────────────────────────────
# routes/agent_route.py
# AI Agent endpoint
# ─────────────────────────────────────────

import asyncio
import hashlib
import re
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.services import agent as agent_service
from app.services import agent_workflow

router = APIRouter(prefix="/agent", tags=["agent"])
conversation_store: dict[str, list[dict[str, str]]] = {}
_PERSISTENT_HISTORY_AVAILABLE: bool | None = None
_TOKEN_USER_CACHE: dict[str, tuple[float, str]] = {}
TOKEN_USER_CACHE_SECONDS = 300
_RATE_BUCKETS: dict[tuple[str, str], list[float]] = {}


def validate_guest_session_id(value: str | None) -> str:
    session_id = (value or "").strip()
    if (
        len(session_id) < 12
        or len(session_id) > 160
        or session_id in {"guest", "default"}
        or re.fullmatch(r"[A-Za-z0-9_-]+", session_id) is None
    ):
        raise HTTPException(status_code=401, detail="A valid guest session is required.")
    return session_id


def enforce_rate_limit(scope: str, owner: str, maximum: int, window_seconds: int) -> None:
    now = time.monotonic()
    key = (scope, owner)
    recent = [stamp for stamp in _RATE_BUCKETS.get(key, []) if now - stamp < window_seconds]
    if len(recent) >= maximum:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment and try again.")
    recent.append(now)
    _RATE_BUCKETS[key] = recent
    if len(_RATE_BUCKETS) > 5000:
        _RATE_BUCKETS.clear()


def load_persistent_history(
    session_id: str,
    user_id: str | None,
    guest_session_id: str | None,
) -> list[dict[str, str]]:
    global _PERSISTENT_HISTORY_AVAILABLE
    if _PERSISTENT_HISTORY_AVAILABLE is False:
        return []
    try:
        from app.config import supabase
        query = supabase.table("agent_conversation_messages")\
            .select("role,content,created_at")\
            .eq("session_id", session_id)
        if user_id:
            query = query.eq("user_id", user_id)
        else:
            query = query.eq("guest_session_id", guest_session_id)
        rows = query.order("created_at", desc=True).limit(20).execute().data or []
        _PERSISTENT_HISTORY_AVAILABLE = True
        return [
            {"role": str(row.get("role") or ""), "content": str(row.get("content") or "")}
            for row in reversed(rows)
            if row.get("role") in {"user", "assistant"} and row.get("content")
        ]
    except Exception as e:
        if _PERSISTENT_HISTORY_AVAILABLE is not False:
            print(f"[agent_history] Persistent history unavailable: {e}")
        _PERSISTENT_HISTORY_AVAILABLE = False
        return []


def save_persistent_turn(
    session_id: str,
    user_id: str | None,
    guest_session_id: str | None,
    message: str,
    response: str,
) -> None:
    global _PERSISTENT_HISTORY_AVAILABLE
    if _PERSISTENT_HISTORY_AVAILABLE is False:
        return
    try:
        from app.config import supabase
        owner = {
            "user_id": user_id,
            "guest_session_id": None if user_id else guest_session_id,
            "session_id": session_id,
        }
        supabase.table("agent_conversation_messages").insert([
            {**owner, "role": "user", "content": message},
            {**owner, "role": "assistant", "content": response},
        ]).execute()
        _PERSISTENT_HISTORY_AVAILABLE = True
    except Exception as e:
        if _PERSISTENT_HISTORY_AVAILABLE is not False:
            print(f"[agent_history] Could not persist turn: {e}")
        _PERSISTENT_HISTORY_AVAILABLE = False


def clear_persistent_history(session_id: str, user_id: str | None, guest_session_id: str | None) -> None:
    if _PERSISTENT_HISTORY_AVAILABLE is False:
        return
    try:
        from app.config import supabase
        query = supabase.table("agent_conversation_messages").delete().eq("session_id", session_id)
        query = query.eq("user_id", user_id) if user_id else query.eq("guest_session_id", guest_session_id)
        query.execute()
    except Exception as e:
        print(f"[agent_history] Could not clear persistent history: {e}")


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
    guest_session_id = None if user_id else validate_guest_session_id(body.guest_session_id)

    owner_key = user_id or guest_session_id
    enforce_rate_limit("agent", str(owner_key), maximum=30, window_seconds=60)
    session_key = f"{owner_key}:{body.session_id}"
    history = conversation_store.get(session_key)
    if history is None:
        history = await asyncio.to_thread(
            load_persistent_history,
            body.session_id,
            user_id,
            guest_session_id,
        )

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
        if len(conversation_store) > 1000:
            conversation_store.pop(next(iter(conversation_store)), None)
        await asyncio.to_thread(
            save_persistent_turn,
            body.session_id,
            user_id,
            guest_session_id,
            message,
            response_text,
        )

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
        request_id = uuid.uuid4().hex[:12]
        print(f"[agent] request_id={request_id} error={e}")
        raise HTTPException(status_code=500, detail=f"Agent request failed. Reference: {request_id}")


@router.post("")
async def run_agent_no_slash(request: Request, body: AgentMessage):
    return await handle_agent_request(request, body)


@router.post("/")
async def run_agent_with_slash(request: Request, body: AgentMessage):
    return await handle_agent_request(request, body)


@router.post("/chat")
async def run_agent_chat(request: Request, body: AgentMessage):
    return await handle_agent_request(request, body)


@router.get("/history")
async def get_conversation_history(
    request: Request,
    session_id: str,
    guest_session_id: str | None = None,
):
    user_id = await asyncio.to_thread(get_user_id, request)
    guest_id = None if user_id else validate_guest_session_id(guest_session_id)
    owner_key = user_id or guest_id
    session_key = f"{owner_key}:{session_id}"
    history = conversation_store.get(session_key)
    if history is None:
        history = await asyncio.to_thread(load_persistent_history, session_id, user_id, guest_id)
        conversation_store[session_key] = history[-20:]
    return {"success": True, "messages": history[-20:]}


@router.post("/clear")
async def clear_conversation(request: Request, body: ClearMessage):
    user_id = await asyncio.to_thread(get_user_id, request)
    guest_session_id = None if user_id else validate_guest_session_id(body.guest_session_id)
    owner_key = user_id or guest_session_id
    session_key = f"{owner_key}:{body.session_id}"
    conversation_store.pop(session_key, None)
    await asyncio.to_thread(clear_persistent_history, body.session_id, user_id, guest_session_id)
    return {"success": True, "message": "Conversation cleared."}


@router.post("/feedback")
async def agent_feedback(request: Request, body: AgentFeedback):
    user_id = get_user_id(request)
    guest_session_id = None if user_id else validate_guest_session_id(body.guest_session_id)

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
