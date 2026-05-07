# ─────────────────────────────────────────
# main.py — Entry point
# Starts the app and connects all routes
# ─────────────────────────────────────────

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import receipts, queries

# Create the app
app = FastAPI(
    title="Receipt Scanner API",
    description="Scan receipts with Claude AI and track prices",
    version="1.0.0"
)

# ── Allow browser to talk to API ──
# This fixes the "Error connecting to API" issue
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],  # allow GET, POST, DELETE etc
    allow_headers=["*"],
)

# Connect all routes
app.include_router(receipts.router)
app.include_router(queries.router)

# Health check
@app.get("/")
def home():
    return {"message": "Receipt Scanner API is running!"}