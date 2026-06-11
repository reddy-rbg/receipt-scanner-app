# ─────────────────────────────────────────
# RECEIPT SCANNER — scan_receipt.py
# Sends a receipt image to Claude AI
# and gets back structured JSON data
# ─────────────────────────────────────────

# Load API key from .env file
from dotenv import load_dotenv
load_dotenv()

import os
import base64
import anthropic

# ── STEP 1: Set your image file name here ──
# Change this to whatever receipt image you want to scan
# Supported: .jpg .jpeg .png .gif .webp
image_path = "receipt.png"

# ── STEP 2: Auto-detect image type from file extension ──
# Split filename by "." and take the last part (the extension)
extension = image_path.split(".")[-1].lower()

# Map each extension to its correct media type
# Claude needs this to understand what kind of image it's receiving
media_types = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "gif":  "image/gif",
    "webp": "image/webp"
}

# Look up the media type — default to jpeg if extension not found
media_type = media_types.get(extension, "image/jpeg")
print(f"Image type detected: {media_type}")

# ── STEP 3: Read and encode the image ──
# We convert the image to base64 — a way to turn any file
# into a long text string so it can be sent through an API
with open(image_path, "rb") as image_file:
    image_data = base64.standard_b64encode(image_file.read()).decode("utf-8")
print(f"Image loaded: {image_path}")

# ── STEP 4: Connect to Claude ──
# Uses your API key from the .env file
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── STEP 5: Send image to Claude with instructions ──
print("Sending to Claude... please wait")

message = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    messages=[
        {
            "role": "user",
            "content": [
                {
                    # The image — converted to base64
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_data,
                    },
                },
                {
                    # The instruction — tells Claude exactly what to extract
                    # and how to format the response
                    "type": "text",
                    "text": """Please extract the following information from this receipt and return it as JSON only, no extra text:
{
    "store": "store name",
    "date": "purchase date",
    "total": 0.00,
    "items": [
        {"name": "item name", "price": 0.00}
    ]
}"""
                }
            ],
        }
    ],
)

# ── STEP 6: Print Claude's response ──
print("\n── Receipt Data Extracted ──")
print(message.content[0].text)