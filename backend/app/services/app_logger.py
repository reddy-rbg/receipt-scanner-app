"""Centralized application logging for ReceiptAI.

Why this exists:
- `print()` is easy during development, but production needs consistent fields.
- Every log line should show where it came from: file, function, line, request id.
- Supabase error rows are best-effort only; logging must never break scanning.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_JSON = os.getenv("LOG_JSON", "false").lower() in {"1", "true", "yes", "on"}


class RequestContextFilter(logging.Filter):
    """Ensure every record has fields referenced by our formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in ("request_id", "method", "path", "status_code", "duration_ms", "user_id", "customer_id"):
            if not hasattr(record, key):
                setattr(record, key, "-")
        return True


class JsonFormatter(logging.Formatter):
    """Render logs as JSON for Railway/log aggregation when LOG_JSON=true."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
        }
        for key in ("request_id", "method", "path", "status_code", "duration_ms", "user_id", "customer_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure root logging once at backend startup."""
    root = logging.getLogger()
    if getattr(root, "_receiptai_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContextFilter())
    if LOG_JSON:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] "
            "%(filename)s:%(lineno)d %(funcName)s "
            "request_id=%(request_id)s %(message)s"
        ))
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    root._receiptai_configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger."""
    configure_logging()
    return logging.getLogger(name)


def request_id() -> str:
    return uuid.uuid4().hex[:12]


def log_exception(
    logger: logging.LoggerAdapter,
    message: str,
    error: BaseException,
    *,
    request_id_value: str | None = None,
    **extra: Any,
) -> None:
    """Log an exception with consistent context."""
    merged = {"request_id": request_id_value or "-", **extra}
    logger.error("%s: %s", message, error, exc_info=error, extra=merged)


def record_error_event(
    *,
    source: str,
    message: str,
    severity: str = "error",
    request_id_value: str | None = None,
    user_id: str | None = None,
    customer_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> None:
    """Best-effort Supabase event for a future error dashboard.

    This deliberately imports Supabase lazily to avoid circular imports.
    """
    try:
        from app.config import supabase

        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "severity": severity,
            "source": source,
            "message": message[:1000],
            "request_id": request_id_value,
            "user_id": user_id,
            "customer_id": customer_id,
            "metadata": metadata or {},
        }
        if error:
            payload["error_type"] = type(error).__name__
            payload["stack"] = "".join(traceback.format_exception(type(error), error, error.__traceback__))[:8000]
        supabase.table("app_error_events").insert(payload).execute()
    except Exception as logging_error:
        # Last-resort stderr keeps the original feature path safe even if the
        # analytics table has not been installed yet.
        print(f"[app_error_events] logging unavailable: {logging_error}", file=sys.stderr)
