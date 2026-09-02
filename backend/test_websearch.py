"""Optional live Claude web-search smoke test with clean pytest skipping."""

import os

import pytest


def _live_client():
    if os.getenv("RUN_LIVE_PROVIDER_TESTS", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("Set RUN_LIVE_PROVIDER_TESTS=true to run live provider smoke tests")
    pytest.importorskip("dotenv")
    anthropic = pytest.importorskip("anthropic")
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY is not set; live web-search test skipped")
    client = anthropic.Anthropic(api_key=api_key)
    if client is None or not hasattr(client, "messages"):
        pytest.skip("Anthropic client is stubbed by the offline test suite")
    return client


def test_claude_live_web_search():
    client = _live_client()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
        messages=[{"role": "user", "content": "Find the official OpenAI home page and name its domain."}],
    )
    assert message.content
    assert any(getattr(block, "text", "").strip() for block in message.content)


if __name__ == "__main__":
    try:
        test_claude_live_web_search()
        print("Claude live web-search passed.")
    except pytest.skip.Exception as error:
        print(f"SKIPPED: {error}")
