# ─────────────────────────────────────────
# main.py — Entry point
# Starts the app and connects all routes
# ─────────────────────────────────────────

import asyncio
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routes import receipts, auth, agent_route, rbac
from app.services import agent as agent_service
from app.services import agent_workflow
from app.services.app_logger import configure_logging, get_logger, record_error_event, request_id
from app.production_config import require_production_config, validate_production_config


configure_logging()
logger = get_logger(__name__)
SLOW_REQUEST_MS = int(os.getenv("SLOW_REQUEST_MS", "3000") or "3000")
LOG_CLIENT_ERROR_EVENTS = os.getenv("LOG_CLIENT_ERROR_EVENTS", "true").lower() in {"1", "true", "yes", "on"}
WEB_APP_DIRECTORY = Path(__file__).parent / "web_app"
CLIENT_EVENT_LIMIT_PER_MINUTE = 30
_client_event_times: dict[str, deque[float]] = defaultdict(deque)


class SPAStaticFiles(StaticFiles):
    """Serve the shared Expo web build and fall back to its client router."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


class ClientErrorEvent(BaseModel):
    severity: str = Field(default="error", max_length=20)
    source: str = Field(default="client", max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    error_type: str | None = Field(default=None, max_length=200)
    stack: str | None = Field(default=None, max_length=4000)
    request_id: str | None = Field(default=None, max_length=100)
    metadata: dict = Field(default_factory=dict)


def _allow_client_event(client_key: str) -> bool:
    now = time.monotonic()
    recent = _client_event_times[client_key]
    while recent and now - recent[0] >= 60:
        recent.popleft()
    if len(recent) >= CLIENT_EVENT_LIMIT_PER_MINUTE:
        return False
    recent.append(now)
    return True


def _safe_client_metadata(metadata: dict) -> dict:
    safe: dict = {}
    for key, value in list(metadata.items())[:30]:
        name = str(key)[:80]
        if any(secret in name.lower() for secret in ("password", "token", "secret", "authorization", "cookie")):
            safe[name] = "[redacted]"
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[name] = value if not isinstance(value, str) else value[:500]
    return safe


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
                logger.info("Deleted %s expired guest receipts", deleted_count)
            else:
                logger.info("No expired guest receipts found")

        except Exception as e:
            logger.exception("Guest receipt cleanup failed")


# ── App lifespan ──
# Starts background tasks when app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    report = require_production_config()
    for warning in report.warnings:
        logger.warning("Production configuration warning: %s", warning)

    # Start guest cleanup task in background
    logger.info("Starting guest receipt cleanup task")
    cleanup_task = asyncio.create_task(cleanup_guest_receipts_task())

    try:
        yield
    finally:
        cleanup_task.cancel()
        logger.info("Guest receipt cleanup task stopped")


# ── Create the app ──
app = FastAPI(
    title="Receipt Scanner API",
    description="Scan receipts with Claude AI and track prices",
    version="1.0.3",
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
    if (
        request.url.path == "/ops"
        or request.url.path.startswith("/ops/")
        or request.url.path.startswith("/reset-password")
        or request.url.path.startswith("/privacy")
        or request.url.path.startswith("/support")
    ):
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
    request_context = {
        "request_id": rid,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
    }
    logger.info(
        "HTTP request completed",
        extra=request_context,
    )
    if response.status_code >= 500:
        record_error_event(
            source="server_response",
            message=f"{request.method} {request.url.path} returned {response.status_code}",
            request_id_value=rid,
            metadata=request_context,
        )
    elif LOG_CLIENT_ERROR_EVENTS and response.status_code >= 400:
        logger.warning("Client request warning", extra=request_context)
        record_error_event(
            source="client_response",
            message=f"{request.method} {request.url.path} returned {response.status_code}",
            severity="warning",
            request_id_value=rid,
            metadata=request_context,
        )
    elif SLOW_REQUEST_MS > 0 and duration_ms >= SLOW_REQUEST_MS:
        logger.warning("Slow request warning", extra=request_context)
        record_error_event(
            source="slow_request",
            message=f"{request.method} {request.url.path} took {duration_ms}ms",
            severity="warning",
            request_id_value=rid,
            metadata={**request_context, "threshold_ms": SLOW_REQUEST_MS},
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


@app.post("/client-errors", status_code=202, include_in_schema=False)
async def client_error_event(event: ClientErrorEvent, request: Request):
    """Accept sanitized browser/mobile failures for the operations Issues tab."""
    client_key = request.client.host if request.client else "unknown"
    if not _allow_client_event(client_key):
        return {"accepted": False, "reason": "rate_limited"}
    severity = event.severity.lower()
    if severity not in {"error", "warning", "info"}:
        severity = "error"
    metadata = _safe_client_metadata(event.metadata)
    if event.error_type:
        metadata["client_error_type"] = event.error_type
    if event.stack:
        metadata["client_stack"] = event.stack[:4000]
    record_error_event(
        source=f"client_{event.source}"[:100],
        message=event.message,
        severity=severity,
        request_id_value=event.request_id,
        metadata=metadata,
    )
    return {"accepted": True}
app.mount(
    "/privacy",
    StaticFiles(directory=str(Path(__file__).parent / "privacy"), html=True),
    name="privacy-policy",
)
app.mount(
    "/support",
    StaticFiles(directory=str(Path(__file__).parent / "support"), html=True),
    name="support",
)

# ── Health check ──
@app.get("/")
def web_app():
    return RedirectResponse(url="/app/", status_code=307)


@app.get("/api")
def api_info():
    return {
        "message": "Receipt Scanner API is running!",
        "version": app.version,
        "features": ["receipt scanning", "AI Q&A", "price tracking", "guest trial mode"]
    }


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "ok", "version": app.version}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    report = validate_production_config()
    payload = {
        "status": "ready" if report.ready else "not_ready",
        "version": app.version,
        "environment": report.environment,
        "production": report.production,
        "warnings": list(report.warnings),
    }
    return JSONResponse(content=payload, status_code=200 if report.ready else 503)


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


# Keep this catch-all mount last so API, health, operations, reset, privacy, and
# support routes retain priority. The browser now runs the same Expo Router app
# and shared screen code as iOS and Android.
app.mount(
    "/app",
    SPAStaticFiles(directory=str(WEB_APP_DIRECTORY), html=True),
    name="receiptai-web-app",
)
