# ─────────────────────────────────────────
# main.py — Entry point
# Starts the app and connects all routes
# ─────────────────────────────────────────

import asyncio
import os
import time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.routes import receipts, auth, agent_route, rbac
from app.services import agent as agent_service
from app.services import agent_workflow
from app.services.app_logger import configure_logging, get_logger, record_error_event, request_id


configure_logging()
logger = get_logger(__name__)


# ── Auto-cleanup task ──
# Runs every hour and deletes expired guest receipts
async def cleanup_guest_receipts_task():
    """
    Background task that runs every hour.
    Deletes all guest receipts older than 24 hours.
    Keeps the database clean automatically.
    """
    while True:
        await asyncio.sleep(3600)  # wait 1 hour
        try:
            from datetime import datetime, timedelta, timezone
            from app.services import database

            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            result = database.supabase.table("receipts")\
                .delete()\
                .eq("is_guest", True)\
                .lt("expires_at", cutoff)\
                .execute()

            deleted_count = len(result.data) if result.data else 0
            if deleted_count > 0:
                print(f"[cleanup] ✓ Deleted {deleted_count} expired guest receipts")
            else:
                print(f"[cleanup] No expired guest receipts found")

        except Exception as e:
            print(f"[cleanup] Error: {e}")


# ── App lifespan ──
# Starts background tasks when app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start guest cleanup task in background
    print("[startup] Starting guest receipt cleanup task...")
    cleanup_task = asyncio.create_task(cleanup_guest_receipts_task())

    yield  # App runs here

    # Cleanup when app shuts down
    cleanup_task.cancel()
    print("[shutdown] Cleanup task stopped.")


# ── Create the app ──
app = FastAPI(
    title="Receipt Scanner API",
    description="Scan receipts with Claude AI and track prices",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Allow browser to talk to API ──
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def operations_security_headers(request, call_next):
    response = await call_next(request)
    if request.url.path == "/ops" or request.url.path.startswith("/ops/") or request.url.path.startswith("/reset-password"):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Log API traffic with request id, route, status, duration, file/line.

    Privacy rule: do not log request bodies here. Uploads, passwords, receipts,
    and auth headers can contain sensitive customer data.
    """
    rid = request.headers.get("X-Request-ID") or request_id()
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.exception(
            "Unhandled request error",
            extra={
                "request_id": rid,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
            },
        )
        record_error_event(
            source="request",
            message=f"{request.method} {request.url.path} failed",
            request_id_value=rid,
            metadata={"method": request.method, "path": request.url.path, "duration_ms": duration_ms},
            error=error,
        )
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = rid
    logger.info(
        "HTTP request completed",
        extra={
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response

# ── Connect all routes ──
app.include_router(receipts.router)
# Legacy global query routes were intentionally retired. They loaded receipts
# without an owner scope; all supported analytics now live in owner-filtered
# receipt and agent routes.
app.include_router(auth.router)
app.include_router(agent_route.router)
app.include_router(rbac.router)
app.mount(
    "/ops",
    StaticFiles(directory=str(Path(__file__).parent / "ops_dashboard"), html=True),
    name="operations-dashboard",
)
app.mount(
    "/reset-password",
    StaticFiles(directory=str(Path(__file__).parent / "reset_password"), html=True),
    name="password-reset",
)

# ── Health check ──
@app.get("/")
def home():
    return {
        "message": "Receipt Scanner API is running!",
        "version": "1.0.0",
        "features": ["receipt scanning", "AI Q&A", "price tracking", "guest trial mode"]
    }


@app.get("/agent-health")
def agent_health():
    google_meaning_enabled = bool(
        (os.getenv("GOOGLE_SEARCH_API_KEY") or os.getenv("GOOGLE_API_KEY"))
        and (os.getenv("GOOGLE_SEARCH_ENGINE_ID") or os.getenv("GOOGLE_CSE_ID"))
    )
    supabase_key_mode = "service" if (os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")) else "anon"
    parser_self_check_query = "what is the cost per type of cilantro red chilies tomato cucumber is it cheaper"
    parser_self_check_items = agent_service.extract_shopping_list_items(parser_self_check_query)
    return {
        "success": True,
        "message": "AI Agent routes are loaded",
        "routes": ["POST /agent", "POST /agent/", "POST /agent/chat", "GET /agent/history", "POST /agent/clear"],
        "structured_rag": True,
        "learned_aliases": True,
        "adaptive_query_recovery": True,
        "agent_build": agent_service.AGENT_BUILD,
        "agent_capabilities": agent_service.AGENT_CAPABILITIES,
        "rag_stack": {
            "contextual_item_embeddings": True,
            "embedding_model": agent_service.LOCAL_EMBEDDING_MODEL,
            "hybrid_retrieval": ["structured_sql", "exact_keyword", "fuzzy_alias", "local_vector", "feedback_ranker"],
            "reranker": "deterministic evidence reranker",
            "trace_dashboard": "rag_trace returned from POST /agent/chat",
        },
        "parser_self_check": {
            "query": parser_self_check_query,
            "items": parser_self_check_items,
            "passed": parser_self_check_items == ["cilantro", "red chili", "tomato", "cucumber"],
        },
        "workflow": agent_workflow.workflow_status(),
        "google_meaning_enabled": google_meaning_enabled,
        "ai_provider": "claude",
        "supabase_key_mode": supabase_key_mode,
    }
