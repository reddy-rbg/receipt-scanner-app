import os
from dotenv import load_dotenv
load_dotenv()
import anthropic

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