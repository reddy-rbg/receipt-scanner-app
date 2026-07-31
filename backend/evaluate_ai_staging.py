"""Evaluate the enabled AI optimization profile before production promotion.

Offline mode verifies configuration without using provider tokens:
    python evaluate_ai_staging.py --offline

Live mode runs a synthetic, non-customer receipt through the staging profile:
    python evaluate_ai_staging.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from io import BytesIO


REQUIRED_ENABLED_FLAGS = (
    "CLAUDE_PROMPT_CACHING_ENABLED",
    "CLAUDE_STRUCTURED_OUTPUTS_ENABLED",
    "CLAUDE_STRICT_TOOLS_ENABLED",
    "CLAUDE_SCAN_CASCADE_ENABLED",
)


def enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def validate_profile() -> list[str]:
    failures: list[str] = []
    if os.getenv("APP_ENV", "").strip().lower() not in {"staging", "stage"}:
        failures.append("APP_ENV must be staging")
    for name in REQUIRED_ENABLED_FLAGS:
        if not enabled(name):
            failures.append(f"{name} must be true")
    if os.getenv("CLAUDE_SCAN_MODEL", "") == os.getenv("CLAUDE_SCAN_FAST_MODEL", ""):
        failures.append("CLAUDE_SCAN_MODEL and CLAUDE_SCAN_FAST_MODEL must differ")
    if not failures:
        from app.services import ai_optimization

        runtime_flags = (
            ai_optimization.PROMPT_CACHING_ENABLED,
            ai_optimization.STRUCTURED_OUTPUTS_ENABLED,
            ai_optimization.STRICT_TOOLS_ENABLED,
            ai_optimization.SCAN_CASCADE_ENABLED,
        )
        if not all(runtime_flags):
            failures.append("one or more optimization flags are disabled at runtime")
    return failures


def synthetic_receipt() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 1400), "white")
    draw = ImageDraw.Draw(image)
    lines = (
        "RECEIPTAI STAGING MARKET",
        "123 TEST AVENUE",
        "07/30/2026  10:15 AM",
        "",
        "APPLE                 1.25",
        "MILK 64 FL OZ         3.75",
        "2 @ 1.50 BANANA       3.00",
        "",
        "SUBTOTAL              8.00",
        "TAX                   0.66",
        "TOTAL                 8.66",
        "VISA",
    )
    y = 80
    for line in lines:
        draw.text((70, y), line, fill="black")
        y += 85
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def run_live() -> dict:
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY is required for live staging evaluation")

    from app.services import claude

    result = claude.scan_receipt_image(
        synthetic_receipt(),
        "synthetic-staging-receipt.png",
        guest_session_id="ai-staging-evaluation",
    )
    usage = result.get("_token_usage") or {}
    validation = result.get("validation") or {}
    cascade = (usage.get("metadata") or {}).get("model_cascade") or {}
    checks = {
        "store_extracted": bool(result.get("store")),
        "items_extracted": len(result.get("items") or []) >= 3,
        "total_correct": abs(float(result.get("total") or 0) - 8.66) < 0.01,
        "confidence_acceptable": float(validation.get("confidence") or 0) >= 0.72,
        "cascade_enabled": cascade.get("enabled") is True,
        "usage_recorded": int(usage.get("output_tokens") or 0) > 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "model": usage.get("model"),
        "usage": {
            key: int(usage.get(key) or 0)
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "cache_creation_input_tokens",
                "output_tokens",
            )
        },
        "cascade": cascade,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    failures = validate_profile()
    if failures:
        print(json.dumps({"passed": False, "profile_failures": failures}, indent=2))
        return 1
    if args.offline:
        print(json.dumps({"passed": True, "profile": "staging", "live": False}, indent=2))
        return 0

    try:
        result = run_live()
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
