"""Regression checks for AI cost, cache, and context controls."""

import json
from types import SimpleNamespace

from app.services import token_usage
from app.services import claude as claude_service
from app.services import ai_optimization
from app.services.ai_optimization import (
    cacheable_system,
    compact_conversation_history,
    fit_image_to_vision_budget,
    model_supports_high_resolution_vision,
    optimized_tools,
    provider_image_token_count,
    structured_output_kwargs,
    visual_token_count,
)


def receipt_payload(confidence: float = 0.95) -> dict:
    return {
        "store": "Test Market",
        "address": None,
        "date": "07/30/26",
        "time": None,
        "payment_method": None,
        "transaction_number": None,
        "receipt_number": None,
        "invoice_number": None,
        "order_number": None,
        "subtotal": 10.0,
        "discount": 0.0,
        "tax": 0.0,
        "total": 10.0,
        "total_savings": 0.0,
        "items": [{
            "code": None,
            "name": "TEST ITEM",
            "normalized_name": "test item",
            "product_size": None,
            "quantity": 1,
            "unit": "each",
            "unit_price": 10.0,
            "price": 10.0,
            "quantity_type": "each",
            "unit_label": "each",
            "explicit_quantity": False,
            "source": "printed",
        }],
        "handwritten_items": [],
        "returned_items": [],
        "manual_adjustments": [],
        "validation": {"is_receipt": True, "confidence": confidence},
        "validation_notes": [],
    }


def test_visual_tokens_follow_documented_28_pixel_patch_grid():
    assert visual_token_count(200, 200) == 64
    assert visual_token_count(1000, 1000) == 1296
    assert visual_token_count(None, 1000) is None


def test_standard_model_resizing_stays_within_native_visual_budget():
    size = fit_image_to_vision_budget(
        3840,
        2160,
        model="claude-sonnet-4-5-20250929",
    )
    assert max(size) <= 1568
    assert visual_token_count(*size) <= 1568
    assert provider_image_token_count(
        3840,
        2160,
        model="claude-sonnet-4-5-20250929",
    ) <= 1568


def test_high_resolution_model_is_still_capped_by_product_budget():
    assert model_supports_high_resolution_vision("claude-opus-4-7")
    assert model_supports_high_resolution_vision("claude-sonnet-5")
    assert not model_supports_high_resolution_vision("claude-sonnet-4-5-20250929")
    size = fit_image_to_vision_budget(
        3840,
        2160,
        model="claude-sonnet-5",
        max_tokens=1568,
    )
    assert visual_token_count(*size) <= 1568


def test_prompt_cache_and_strict_tools_do_not_mutate_original_definitions():
    source = [{"name": "lookup", "input_schema": {"type": "object"}}]
    optimized = optimized_tools(
        source,
        cache_enabled=True,
        strict_enabled=True,
    )
    assert source == [{"name": "lookup", "input_schema": {"type": "object"}}]
    assert optimized[0]["strict"] is True
    assert optimized[0]["cache_control"] == {"type": "ephemeral"}
    assert isinstance(cacheable_system("stable rules", enabled=True), list)
    assert cacheable_system("stable rules", enabled=False) == "stable rules"


def test_structured_outputs_are_guarded():
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    assert structured_output_kwargs(schema, enabled=False) == {}
    enabled = structured_output_kwargs(schema, enabled=True)
    assert enabled["output_config"]["format"]["type"] == "json_schema"
    assert enabled["output_config"]["format"]["schema"] is schema


def test_conversation_history_keeps_newest_messages_within_budget():
    history = [
        {"role": "user", "content": "old " * 100},
        {"role": "assistant", "content": "middle " * 100},
        {"role": "user", "content": "newest"},
    ]
    compact = compact_conversation_history(
        history,
        max_messages=2,
        max_chars=80,
        message_max_chars=60,
    )
    assert compact[-1] == {"role": "user", "content": "newest"}
    assert len(compact) <= 2
    assert sum(len(row["content"]) for row in compact) <= 80


def test_usage_accounting_includes_cache_reads_and_writes():
    message = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=25,
            cache_read_input_tokens=800,
            cache_creation_input_tokens=200,
        )
    )
    assert token_usage.usage_from_message(message) == {
        "input_tokens": 100,
        "output_tokens": 25,
        "cached_input_tokens": 800,
        "cache_creation_input_tokens": 200,
    }


def test_default_scan_keeps_existing_model_and_caches_only_stable_prompt(monkeypatch):
    captured: dict = {}
    receipt = receipt_payload()

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(receipt))],
                usage=SimpleNamespace(
                    input_tokens=120,
                    output_tokens=40,
                    cache_read_input_tokens=900,
                    cache_creation_input_tokens=0,
                ),
            )

    monkeypatch.setattr(claude_service, "SCAN_CASCADE_ENABLED", False)
    monkeypatch.setattr(claude_service, "check_duplicate", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        claude_service,
        "optimize_scan_image_for_claude",
        lambda content, page_index=1: (
            content,
            "image/jpeg",
            {"estimated_image_tokens_saved": 0},
        ),
    )
    monkeypatch.setattr(
        claude_service,
        "claude_client",
        SimpleNamespace(messages=FakeMessages()),
    )

    result = claude_service.scan_receipt_image(b"image", "receipt.jpg")

    assert captured["model"] == claude_service.SCAN_MODEL
    content = captured["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1]["type"] == "image"
    assert result["_token_usage"]["cached_input_tokens"] == 900


def test_scan_cascade_falls_back_without_changing_default_model_configuration(monkeypatch):
    models: list[str] = []
    responses = [receipt_payload(0.50), receipt_payload(0.96)]

    class FakeMessages:
        def create(self, **kwargs):
            models.append(kwargs["model"])
            payload = responses.pop(0)
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(payload))],
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=30,
                    cache_read_input_tokens=500,
                    cache_creation_input_tokens=0,
                ),
            )

    monkeypatch.setattr(claude_service, "SCAN_CASCADE_ENABLED", True)
    monkeypatch.setattr(claude_service, "SCAN_FAST_MODEL", "claude-haiku-4-5-test")
    monkeypatch.setattr(claude_service, "SCAN_CASCADE_MIN_CONFIDENCE", 0.82)
    monkeypatch.setattr(claude_service, "check_duplicate", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        claude_service,
        "optimize_scan_image_for_claude",
        lambda content, page_index=1: (
            content,
            "image/jpeg",
            {"estimated_image_tokens_saved": 0},
        ),
    )
    monkeypatch.setattr(
        claude_service,
        "claude_client",
        SimpleNamespace(messages=FakeMessages()),
    )

    result = claude_service.scan_receipt_image(b"image", "receipt.jpg")

    assert models == ["claude-haiku-4-5-test", claude_service.SCAN_MODEL]
    assert result["_token_usage"]["model"] == claude_service.SCAN_MODEL
    assert result["_token_usage"]["input_tokens"] == 200
    assert result["_token_usage"]["cached_input_tokens"] == 1000
    cascade = result["_token_usage"]["metadata"]["model_cascade"]
    assert cascade["fallback_used"] is True
    assert cascade["fast_confidence"] == 0.5


def test_scan_structured_output_is_opt_in(monkeypatch):
    captured: dict = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(receipt_payload()))],
                usage=SimpleNamespace(input_tokens=10, output_tokens=10),
            )

    monkeypatch.setattr(ai_optimization, "STRUCTURED_OUTPUTS_ENABLED", True)
    monkeypatch.setattr(claude_service, "SCAN_CASCADE_ENABLED", False)
    monkeypatch.setattr(claude_service, "check_duplicate", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        claude_service,
        "optimize_scan_image_for_claude",
        lambda content, page_index=1: (
            content,
            "image/jpeg",
            {"estimated_image_tokens_saved": 0},
        ),
    )
    monkeypatch.setattr(
        claude_service,
        "claude_client",
        SimpleNamespace(messages=FakeMessages()),
    )

    claude_service.scan_receipt_image(b"image", "receipt.jpg")

    assert captured["output_config"]["format"]["type"] == "json_schema"
