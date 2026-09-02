"""Optional live Anthropic connectivity smoke test.

The test skips cleanly when no API key is configured so it never aborts
collection of the deterministic release suite.
"""

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
        pytest.skip("ANTHROPIC_API_KEY is not set; live smoke test skipped")
    client = anthropic.Anthropic(api_key=api_key)
    if client is None or not hasattr(client, "messages"):
        pytest.skip("Anthropic client is stubbed by the offline test suite")
    return client


def test_anthropic_live_connectivity():
    client = _live_client()
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with exactly: ReceiptAI live"}],
    )
    assert message.content
    assert "ReceiptAI live" in message.content[0].text


if __name__ == "__main__":
    try:
        test_anthropic_live_connectivity()
        print("Anthropic live connectivity passed.")
    except pytest.skip.Exception as error:
        print(f"SKIPPED: {error}")
