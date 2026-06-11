# ─────────────────────────────────────────
# main.py — Entry point
# Starts the app and connects all routes
# ─────────────────────────────────────────

import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import receipts, queries, auth, agent_route
from app.services import agent as agent_service


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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Connect all routes ──
app.include_router(receipts.router)
app.include_router(queries.router)
app.include_router(auth.router)
app.include_router(agent_route.router)

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
    return {
        "success": True,
        "message": "AI Agent routes are loaded",
        "routes": ["POST /agent", "POST /agent/", "POST /agent/chat", "POST /agent/clear"],
        "structured_rag": True,
        "learned_aliases": True,
        "adaptive_query_recovery": True,
        "agent_build": agent_service.AGENT_BUILD,
        "agent_capabilities": agent_service.AGENT_CAPABILITIES,
        "google_meaning_enabled": google_meaning_enabled,
        "ai_provider": "claude",
        "supabase_key_mode": supabase_key_mode,
    }
