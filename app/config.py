# ─────────────────────────────────────────
# config.py
# All settings, API keys, and connections
# ─────────────────────────────────────────

from dotenv import load_dotenv
load_dotenv()

import os
import anthropic
from supabase import create_client, Client

# ── Anthropic Claude client ──
claude_client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# ── Supabase client ──
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

# ── Supported image types ──
MEDIA_TYPES = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "gif":  "image/gif",
    "webp": "image/webp"
}

# ── Supported upload types (includes PDF) ──
SUPPORTED_EXTENSIONS = list(MEDIA_TYPES.keys()) + ["pdf"]

# ── Claude model to use ──
CLAUDE_MODEL = "claude-haiku-4-5-20251001"