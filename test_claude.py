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

message = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": "Say hello and confirm you are working!"
        }
    ]
)

print(message.content[0].text)
