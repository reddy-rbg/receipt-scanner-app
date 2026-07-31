"""Shared, backward-compatible controls for Claude cost and context optimization."""

from __future__ import annotations

import math
import os
import re
from typing import Any, Iterable


_FALSE_VALUES = {"0", "false", "no", "off"}


def env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSE_VALUES


PROMPT_CACHING_ENABLED = env_enabled("CLAUDE_PROMPT_CACHING_ENABLED", True)
STRUCTURED_OUTPUTS_ENABLED = env_enabled("CLAUDE_STRUCTURED_OUTPUTS_ENABLED", False)
STRICT_TOOLS_ENABLED = env_enabled("CLAUDE_STRICT_TOOLS_ENABLED", False)
SCAN_CASCADE_ENABLED = env_enabled("CLAUDE_SCAN_CASCADE_ENABLED", False)

AGENT_HISTORY_MAX_MESSAGES = max(1, int(os.getenv("AGENT_HISTORY_MAX_MESSAGES", "10")))
AGENT_HISTORY_MAX_CHARS = max(1000, int(os.getenv("AGENT_HISTORY_MAX_CHARS", "16000")))
AGENT_HISTORY_MESSAGE_MAX_CHARS = max(
    500,
    int(os.getenv("AGENT_HISTORY_MESSAGE_MAX_CHARS", "4000")),
)

STANDARD_VISION_MAX_EDGE = 1568
STANDARD_VISION_MAX_TOKENS = 1568
HIGH_RES_VISION_MAX_EDGE = 2576
HIGH_RES_VISION_MAX_TOKENS = 4784


def model_supports_high_resolution_vision(model: str | None) -> bool:
    """Return whether Claude automatically uses the high-resolution vision tier."""
    normalized = (model or "").strip().lower()
    if any(name in normalized for name in ("fable-5", "mythos-5")):
        return True
    match = re.search(r"claude-(?:opus|sonnet)-(\d+)(?:-(\d+))?", normalized)
    if not match:
        return False
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    return major > 4 or (major == 4 and minor >= 7)


def vision_limits(model: str | None) -> tuple[int, int]:
    if model_supports_high_resolution_vision(model):
        return HIGH_RES_VISION_MAX_EDGE, HIGH_RES_VISION_MAX_TOKENS
    return STANDARD_VISION_MAX_EDGE, STANDARD_VISION_MAX_TOKENS


def visual_token_count(width: int | None, height: int | None) -> int | None:
    """Count Claude visual patches using the documented 28x28 token grid."""
    if not width or not height or width < 1 or height < 1:
        return None
    return math.ceil(width / 28) * math.ceil(height / 28)


def fit_image_to_vision_budget(
    width: int,
    height: int,
    *,
    model: str | None,
    max_edge: int | None = None,
    max_tokens: int | None = None,
) -> tuple[int, int]:
    """Find the largest aspect-preserving image size within edge/token limits."""
    if width < 1 or height < 1:
        return max(1, width), max(1, height)

    native_edge, native_tokens = vision_limits(model)
    edge_limit = min(native_edge, max_edge) if max_edge and max_edge > 0 else native_edge
    token_limit = (
        min(native_tokens, max_tokens)
        if max_tokens and max_tokens > 0
        else native_tokens
    )
    initial_scale = min(1.0, edge_limit / max(width, height))
    initial_width = max(1, math.floor(width * initial_scale))
    initial_height = max(1, math.floor(height * initial_scale))
    if (visual_token_count(initial_width, initial_height) or 0) <= token_limit:
        return initial_width, initial_height

    low = 0.0
    high = initial_scale
    best = (1, 1)
    for _ in range(48):
        scale = (low + high) / 2
        candidate = (
            max(1, math.floor(width * scale)),
            max(1, math.floor(height * scale)),
        )
        if (visual_token_count(*candidate) or 0) <= token_limit:
            best = candidate
            low = scale
        else:
            high = scale
    return best


def provider_image_dimensions(
    width: int,
    height: int,
    *,
    model: str | None,
) -> tuple[int, int]:
    """Return the dimensions Claude will approximately see after native resizing."""
    return fit_image_to_vision_budget(width, height, model=model)


def provider_image_token_count(
    width: int | None,
    height: int | None,
    *,
    model: str | None,
) -> int | None:
    if not width or not height:
        return None
    resized = provider_image_dimensions(width, height, model=model)
    return visual_token_count(*resized)


def cacheable_text_block(text: str, *, enabled: bool | None = None) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "text", "text": text}
    use_cache = PROMPT_CACHING_ENABLED if enabled is None else enabled
    if use_cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def cacheable_system(text: str, *, enabled: bool | None = None) -> str | list[dict[str, Any]]:
    use_cache = PROMPT_CACHING_ENABLED if enabled is None else enabled
    return [cacheable_text_block(text, enabled=True)] if use_cache else text


def optimized_tools(
    tools: Iterable[dict[str, Any]],
    *,
    cache_enabled: bool | None = None,
    strict_enabled: bool | None = None,
) -> list[dict[str, Any]]:
    """Copy tool definitions and apply optional strict/caching controls."""
    result = [dict(tool) for tool in tools]
    use_strict = STRICT_TOOLS_ENABLED if strict_enabled is None else strict_enabled
    if use_strict:
        for tool in result:
            tool["strict"] = True
    use_cache = PROMPT_CACHING_ENABLED if cache_enabled is None else cache_enabled
    if use_cache and result:
        result[-1]["cache_control"] = {"type": "ephemeral"}
    return result


def structured_output_kwargs(
    schema: dict[str, Any],
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    use_schema = STRUCTURED_OUTPUTS_ENABLED if enabled is None else enabled
    if not use_schema:
        return {}
    return {
        "output_config": {
            "format": {
                "type": "json_schema",
                "schema": schema,
            }
        }
    }


def compact_conversation_history(
    history: list[dict[str, Any]] | None,
    *,
    max_messages: int = AGENT_HISTORY_MAX_MESSAGES,
    max_chars: int = AGENT_HISTORY_MAX_CHARS,
    message_max_chars: int = AGENT_HISTORY_MESSAGE_MAX_CHARS,
) -> list[dict[str, str]]:
    """Keep the newest useful turns within a predictable context budget."""
    if not history:
        return []
    selected: list[dict[str, str]] = []
    used = 0
    for message in reversed(history[-max_messages:]):
        role = str(message.get("role") or "").strip()
        content = str(message.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if len(content) > message_max_chars:
            content = content[: message_max_chars - 1].rstrip() + "…"
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[-remaining:]
        selected.append({"role": role, "content": content})
        used += len(content)
    selected.reverse()
    return selected
