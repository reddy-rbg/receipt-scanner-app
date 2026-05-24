import os

try:
    from dotenv import load_dotenv
    import anthropic
except ModuleNotFoundError as exc:
    print(f"SKIPPED: optional dependency missing ({exc.name}). Run `pip install -r requirements.txt` to enable this live smoke test.")
    raise SystemExit(0)

load_dotenv()

if not os.getenv("ANTHROPIC_API_KEY"):
    print("SKIPPED: ANTHROPIC_API_KEY is not set.")
    raise SystemExit(0)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

print("Testing web search...")

try:
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
        messages=[{"role": "user", "content": "What is the current price of tomatoes at Walmart in 2026?"}]
    )
    print("SUCCESS!")
    for block in message.content:
        print("Block type:", type(block).__name__)
        if hasattr(block, "text"):
            print("Text:", block.text[:300])
except Exception as e:
    print("ERROR:", str(e))
