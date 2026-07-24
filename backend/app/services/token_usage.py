"""Best-effort AI token usage logging and summaries.

The scanner/agent must never fail just because analytics tables are missing,
so every write in this module is intentionally non-blocking.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from app.config import supabase
from app.services.app_logger import get_logger

logger = get_logger(__name__)

MODEL_INPUT_COST_PER_MILLION = float(os.getenv("AI_INPUT_COST_PER_MILLION_TOKENS", "0") or 0)
MODEL_OUTPUT_COST_PER_MILLION = float(os.getenv("AI_OUTPUT_COST_PER_MILLION_TOKENS", "0") or 0)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    """Return estimated USD only when env rates are configured."""
    if MODEL_INPUT_COST_PER_MILLION <= 0 and MODEL_OUTPUT_COST_PER_MILLION <= 0:
        return None
    return round(
        (input_tokens / 1_000_000) * MODEL_INPUT_COST_PER_MILLION
        + (output_tokens / 1_000_000) * MODEL_OUTPUT_COST_PER_MILLION,
        6,
    )


def usage_from_message(message: Any) -> dict[str, int]:
    usage = getattr(message, "usage", None)
    return {
        "input_tokens": _safe_int(getattr(usage, "input_tokens", 0)),
        "output_tokens": _safe_int(getattr(usage, "output_tokens", 0)),
    }


def record_token_usage(
    *,
    feature: str,
    operation: str,
    model: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    customer_id: str | None = None,
    receipt_id: int | None = None,
    filename: str | None = None,
    file_type: str | None = None,
    file_bytes: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    optimized: bool = False,
    optimization: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature": feature,
        "operation": operation,
        "model": model,
        "user_id": user_id,
        "guest_session_id": guest_session_id,
        "customer_id": customer_id,
        "receipt_id": receipt_id,
        "filename": filename,
        "file_type": file_type,
        "file_bytes": file_bytes,
        "input_tokens": _safe_int(input_tokens),
        "output_tokens": _safe_int(output_tokens),
        "cached_input_tokens": _safe_int(cached_input_tokens),
        "total_tokens": _safe_int(input_tokens) + _safe_int(output_tokens),
        "estimated_cost_usd": estimate_cost(_safe_int(input_tokens), _safe_int(output_tokens)),
        "optimized": optimized,
        "optimization": optimization,
        "metadata": metadata or {},
    }
    try:
        supabase.table("ai_token_usage").insert(payload).execute()
    except Exception as error:
        logger.warning("Token usage logging unavailable: %s", error)
