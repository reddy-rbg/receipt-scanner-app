# ─────────────────────────────────────────
# services/claude.py
# All Claude AI logic lives here
# Handles receipt scanning, Q&A, shopping list optimization
#
# Functions:
# convert_pdf_to_image()     — convert PDF to PNG for scanning
# get_image_hash()           — unique fingerprint for duplicate detection
# check_duplicate()          — check if receipt already scanned
# scan_receipt_image()       — main receipt scanning function
# answer_question()          — natural language Q&A about receipts
# optimize_shopping_list()   — find best store for each item
# get_realtime_price()       — web search for current market prices
# ─────────────────────────────────────────

import base64
import json
import hashlib
from app.config import claude_client, CLAUDE_MODEL, MEDIA_TYPES, supabase


def convert_pdf_to_image(pdf_bytes: bytes) -> bytes:
    """
    Convert a PDF file to a PNG image for scanning.

    How it works:
    - pdf2image reads the PDF bytes
    - Converts the first page to a PIL image at 200 DPI
    - Returns the image as PNG bytes ready for Claude

    We only convert the first page because receipts
    are always single page documents.

    Raises ValueError if PDF cannot be converted.
    """
    try:
        from pdf2image import convert_from_bytes
        import io

        # Convert PDF bytes to list of PIL images
        # dpi=200 gives high enough quality for Claude to read text clearly
        # first_page=1 and last_page=1 means only convert page 1
        images = convert_from_bytes(
            pdf_bytes,
            dpi=200,
            first_page=1,
            last_page=1
        )

        if not images:
            raise ValueError("Could not extract any pages from the PDF")

        # Convert the PIL image to PNG bytes
        # BytesIO is an in-memory file buffer — no disk needed
        img_byte_arr = io.BytesIO()
        images[0].save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)  # rewind to start of buffer

        print(f"[pdf] Successfully converted PDF to PNG image")
        return img_byte_arr.read()

    except ImportError:
        # pdf2image or poppler not installed
        raise ValueError(
            "PDF support not installed. "
            "Run: pip install pdf2image pillow "
            "and install poppler from https://github.com/oschwartz10612/poppler-windows/releases"
        )
    except Exception as e:
        raise ValueError(f"Could not read PDF file: {str(e)}")


def get_image_hash(image_bytes: bytes) -> str:
    """
    Generate a unique fingerprint for an image using MD5 hashing.

    How it works:
    - MD5 reads the raw bytes of the image
    - Produces a unique 32 character string
    - Same image always = same hash
    - Different image = different hash

    Used for duplicate receipt detection — if you scan the same
    receipt twice, the hash will match and we skip saving it again.
    """
    return hashlib.md5(image_bytes).hexdigest()


def check_duplicate(image_hash: str) -> dict | None:
    """
    Check if this exact receipt image was already scanned before.

    How it works:
    - Look up the image hash in the database
    - If found return the existing receipt record
    - If not found return None so scanning proceeds

    This prevents the same receipt being saved twice by accident.
    """

    response = supabase.table("receipts")\
        .select("*")\
        .eq("image_hash", image_hash)\
        .execute()

    # If any rows returned this receipt was already scanned
    if response.data:
        return response.data[0]

    # No match found — receipt is new
    return None


def scan_receipt_image(image_bytes: bytes, filename: str) -> dict:
    """
    Main receipt scanning function.
    Handles both image files (jpg, png, webp, gif) and PDF files.

    Full flow:
    1. Generate MD5 hash of original bytes for duplicate detection
    2. Check if this exact file was already scanned before
    3. If duplicate — return existing data with duplicate flag
    4. If PDF — convert to PNG image first
    5. If image — detect type from file extension
    6. Convert image to base64 for API transmission
    7. Send to Claude with detailed extraction instructions
    8. Clean Claude's response (remove markdown if added)
    9. Parse JSON response
    10. Check if Claude returned an error (blurry, not a receipt)
    11. Attach image hash to data for saving in database

    Returns structured receipt data dictionary.
    Raises ValueError if file is unreadable or not a receipt.
    """

    # ── Step 1: Generate image fingerprint ──
    # Hash the ORIGINAL bytes before any conversion
    # This ensures PDF and its converted image have the same hash
    image_hash = get_image_hash(image_bytes)

    # ── Step 2: Check for duplicate ──
    # Look up hash in database — returns existing receipt or None
    existing = check_duplicate(image_hash)
    if existing:
        # Receipt already scanned — return with duplicate flag
        # The API endpoint will show a friendly warning message
        return {
            "duplicate": True,
            "message": "This receipt was already scanned!",
            "existing_receipt": existing
        }

    # ── Step 3: Get file extension ──
    # e.g. "receipt.pdf" → "pdf"
    # e.g. "receipt.jpg" → "jpg"
    extension = filename.split(".")[-1].lower()

    # ── Step 4: Handle PDF files ──
    # PDFs must be converted to images before sending to Claude
    # Claude Vision cannot read PDF format directly
    if extension == "pdf":
        print(f"[scan] PDF detected — converting to image: {filename}")
        # convert_pdf_to_image raises ValueError if conversion fails
        image_bytes = convert_pdf_to_image(image_bytes)
        # After conversion it's a PNG image
        media_type = "image/png"
    else:
        # ── Step 5: Detect image type for regular images ──
        # e.g. "jpg" → "image/jpeg"
        # e.g. "png" → "image/png"
        media_type = MEDIA_TYPES.get(extension, "image/jpeg")

    # ── Step 6: Convert image to base64 ──
    # Base64 converts binary image data into a text string
    # This is required for sending images through REST APIs
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    # ── Step 7: Send to Claude with detailed extraction instructions ──
    message = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,  # receipts can be long — give Claude enough room
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        # The receipt image sent as base64
                        "type": "image",
                        "source": {
                            "type":       "base64",
                            "media_type": media_type,
                            "data":       image_data,
                        },
                    },
                    {
                        # Detailed extraction instructions for Claude
                        "type": "text",
                        "text": """You are a receipt scanner. Carefully read this receipt image.

FIRST — check if this is a readable receipt:
- If NOT a receipt or too blurry/unclear to read accurately, respond ONLY with:
  {"error": "Cannot read receipt clearly. Please take a clearer photo."}
- If it IS a receipt, extract all data below

WHAT TO EXTRACT:

1. STORE INFO
   - store: exact store name as printed (e.g. "WAL*MART" or "LOWE'S HOME CENTERS, LLC")
   - address: full store address if visible (e.g. "PEA RIDGE, AR")
   - date: exact date printed on receipt (e.g. "04/12/26")
   - time: time of purchase if visible (e.g. "12:27:30")
   - payment_method: how they paid (e.g. "AMEX", "VISA", "CASH")

2. ITEMS — extract EVERY item carefully:

   For REGULAR items (sold by unit/each):
   - code: product barcode/SKU printed near item (e.g. "007874235334") or null
   - name: exact product name as printed (e.g. "GV SPAG 32O")
   - quantity: number of units bought (default 1)
   - unit: "each" for regular items
   - unit_price: price per single unit
   - price: total line price

   For WEIGHTED items (sold by weight — look for "lb", "kg", "oz"):
   - These appear as: "2.71 lb @ 1.0 lb /1.97" = 2.71 lbs at $1.97 per lb
   - code: barcode if visible or null
   - name: exact product name (e.g. "TOMATO 4X5")
   - quantity: the weight amount (e.g. 2.71)
   - unit: the weight unit — "lb", "kg", or "oz"
   - unit_price: price per unit weight (e.g. 1.97 per lb)
   - price: total line price (quantity x unit_price)

   For MULTI-PACK items (e.g. "3 AT 1 FOR 0.60"):
   - name: exact product name
   - quantity: total number bought (e.g. 3)
   - unit: "each"
   - unit_price: price per single item (e.g. 0.60)
   - price: total line price (e.g. 1.80)

3. DISCOUNTS — extract ALL savings as SEPARATE items:
   - Include any discount, coupon, or savings line
   - Use NEGATIVE prices for all discounts
   - name format: "DISCOUNT: [description]"
   - Example: {"code": null, "name": "DISCOUNT GIVEN", "quantity": 1, "unit": "each", "unit_price": -3.47, "price": -3.47}

4. TOTALS
   - subtotal: amount before discount and tax (0.00 if not shown)
   - discount: total discount amount as POSITIVE number (e.g. 3.47)
   - tax: tax amount charged (0.00 if not shown)
   - total: final total amount paid — must match receipt exactly
   - total_savings: total savings shown at bottom (0.00 if not shown)

STRICT RULES:
- Only extract what is CLEARLY visible — never guess or invent
- Item names must be EXACT as printed — do not paraphrase
- total must match exactly what is printed on the receipt
- For weighted items ALWAYS capture unit and unit_price
- Do NOT include: transaction numbers, receipt numbers, survey URLs,
  cashier names, store membership numbers, card numbers, change due

Return JSON only — no extra text, no markdown:
{
    "store": "store name",
    "address": "address or null",
    "date": "date or null",
    "time": "time or null",
    "payment_method": "payment method or null",
    "subtotal": 0.00,
    "discount": 0.00,
    "tax": 0.00,
    "total": 0.00,
    "total_savings": 0.00,
    "items": [
        {
            "code": "barcode or null",
            "name": "exact item name",
            "quantity": 1,
            "unit": "each",
            "unit_price": 0.00,
            "price": 0.00
        }
    ]
}"""
                    }
                ],
            }
        ],
    )

    # ── Step 8: Clean Claude's response ──
    raw = message.content[0].text.strip()

    # Claude sometimes wraps JSON in ```json ... ``` markdown
    # Remove those markers if present
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1])

    # ── Step 9: Parse JSON response ──
    data = json.loads(raw)

    # ── Step 10: Check if Claude returned an error ──
    # This happens when receipt is unreadable or not a receipt
    if "error" in data:
        raise ValueError(data["error"])

    # ── Step 11: Attach image hash for future duplicate detection ──
    # Stored in database so scanning the same file again is detected
    data["image_hash"] = image_hash

    return data


def answer_question(question: str, receipts: list) -> str:
    """
    Answer a natural language question about the user's receipts.

    How it works:
    1. Convert all receipts to JSON text (Claude's knowledge base)
    2. Send question + all receipt data to Claude
    3. Claude reads the data and answers in plain English
    4. Supports markdown — tables, bold, lists, headers

    The UI renders Claude's markdown response into proper HTML
    so tables, headers, and bold text display correctly.

    Returns Claude's answer as a markdown string.
    """

    # Convert receipts list to formatted JSON string
    # This becomes Claude's complete knowledge base for answering
    receipts_text = json.dumps(receipts, indent=2)

    message = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,  # allow longer answers for table responses
        messages=[
            {
                "role": "user",
                "content": f"""You are a helpful personal shopping assistant.
You have access to the user's complete purchase history below.

YOUR JOB:
- Answer the user's question clearly and specifically
- Use exact prices, store names, dates, and item names from the data
- For weighted items (lb, kg) compare by unit_price not total price
- If comparing prices show all options ranked cheapest to most expensive
- If the answer is not in the data say so honestly — never make up data
- Keep answers concise but complete
- Use dollar signs for prices (e.g. $3.49)
- For weighted items mention the unit (e.g. "$1.97 per lb")

FORMATTING:
- Use markdown tables when the user asks for table format
- Use ## headers to organize long answers
- Use **bold** for important numbers and store names
- Use bullet points for lists

PURCHASE HISTORY:
{receipts_text}

USER QUESTION: {question}

Answer directly and helpfully:"""
            }
        ],
    )

    # Return Claude's text response
    # The UI will render markdown into proper HTML
    return message.content[0].text


def optimize_shopping_list(items: list, item_prices: dict) -> dict:
    """
    Analyze price history for each item and recommend
    the best store to buy each one from.

    How it works:
    1. Build a readable price summary from receipt history
    2. Send to Claude with the shopping list
    3. Claude recommends best store per item based on real data
    4. Returns structured recommendations with savings estimates

    Returns:
    - recommendations: list of {item, best_store, price, all_options}
    - not_found: items with no purchase history
    - summary: {total_estimated_cost, stores_to_visit, total_savings, tip}
    """

    # Build a readable summary of price history for Claude
    # This shows Claude all the prices we found for each item
    price_summary = ""
    for item_name, prices in item_prices.items():
        if prices:
            # Item has purchase history — show all options sorted cheapest first
            price_summary += f"\n{item_name.upper()}:\n"
            for p in prices[:5]:  # show top 5 cheapest options
                unit_label = f"per {p['unit']}" if p['unit'] != "each" else "each"
                price_summary += (
                    f"  - {p['store']}: ${p['unit_price']:.2f} {unit_label}"
                    f" (bought {p['date']})\n"
                )
        else:
            # No purchase history for this item
            price_summary += f"\n{item_name.upper()}: No purchase history found\n"

    message = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""You are a smart shopping assistant helping optimize a shopping list.

Based on the user's REAL purchase history below, recommend the best store to buy each item.
Only use data from the purchase history — never make up prices.

PURCHASE HISTORY:
{price_summary}

SHOPPING LIST: {', '.join(items)}

Return ONLY raw JSON — no markdown, no backticks, no extra text:
{{
    "recommendations": [
        {{
            "item": "item name from shopping list",
            "found": true,
            "best_store": "store with cheapest price",
            "price": 0.00,
            "unit": "per lb or each",
            "last_bought": "date last purchased",
            "savings_vs_most_expensive": 0.00,
            "all_options": [
                {{"store": "store name", "price": 0.00, "unit": "per lb or each"}}
            ]
        }}
    ],
    "not_found": ["items with no purchase history"],
    "summary": {{
        "total_estimated_cost": 0.00,
        "stores_to_visit": ["unique list of recommended stores"],
        "total_savings": 0.00,
        "tip": "one helpful shopping tip based on the data"
    }}
}}

Rules:
- found: true if we have price history, false if not
- best_store: the store with the cheapest unit_price from history
- price: the cheapest price found in history
- savings_vs_most_expensive: difference between cheapest and most expensive option
- If item has no history set found to false and omit best_store and price
- all_options: ALL stores where this item was found, sorted cheapest first
- total_estimated_cost: sum of best prices for all found items
- total_savings: total saved vs buying everything at most expensive options
- Return raw JSON only — no markdown"""
            }
        ]
    )

    raw = message.content[0].text.strip()

    # Clean markdown if present
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    # Extract JSON object
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1:
        raw = raw[start:end + 1]

    try:
        return json.loads(raw)
    except Exception as e:
        print(f"[optimize_shopping_list] Parse error: {e}")
        return {"error": "Could not optimize shopping list. Please try again."}


def get_realtime_price(item_name: str) -> dict:
    """
    Search the web for current retail prices of any item.
    Uses a two-step approach:
    1. Search web for raw price information
    2. Format results into clean structured JSON

    Returns:
    - current_prices: list of {store, price, unit, source}
    - price_range: {low, high}
    - notes: context about price variations

    Returns {"error": "..."} if prices cannot be found.
    """

    # ── Step 1: Search the web for prices ──
    # Run multiple targeted searches for better coverage
    search_queries = [
        f"{item_name} price per lb Walmart 2026",
        f"{item_name} price Kroger Target grocery store 2026",
        f"how much does {item_name} cost grocery store today"
    ]

    all_search_text = ""

    for query in search_queries:
        try:
            search_message = claude_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=512,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 1
                }],
                messages=[
                    {
                        "role": "user",
                        "content": f"Search for: {query}. Return only the prices you find."
                    }
                ]
            )

            # Collect all text blocks from the search response
            # Claude returns multiple small text blocks when using web search
            for block in search_message.content:
                if hasattr(block, "text") and block.text.strip():
                    all_search_text += block.text + " "

        except Exception as e:
            print(f"[realtime_price] Search failed for '{query}': {e}")
            continue

    all_search_text = all_search_text.strip()
    print(f"[realtime_price] Combined search text: {all_search_text[:300]}")

    if not all_search_text:
        return {"error": f"No price data found for '{item_name}'"}

    # ── Step 2: Format raw text into clean JSON ──
    # Ask Claude to structure the information it found into our format
    # We describe structure with placeholder words not example numbers
    # to avoid Claude copying placeholders instead of real prices
    json_structure = """{
    "item": "the item name",
    "current_prices": [
        {"store": "actual store name or General Market", "price": actual_number, "unit": "per lb or each", "source": "brief description"}
    ],
    "price_range": {"low": lowest_number, "high": highest_number},
    "notes": "brief note about price trends or variations"
}"""

    format_message = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""Based on this price information found from web searches:

{all_search_text}

Extract and organize all prices found for "{item_name}".
For each price mention identify the store if named,
or use "General Market" if no specific store is mentioned.

Return ONLY raw JSON — no markdown, no backticks, no extra text:
{json_structure}

Rules:
- Include EVERY price mentioned in the text
- If store name not mentioned use "General Market"
- price, low, high must be plain numbers like 1.97 not strings like "$1.97"
- If multiple price types exist (per lb, each) include all as separate entries
- Raw JSON only"""
            }
        ]
    )

    raw = format_message.content[0].text.strip()

    # Clean markdown if Claude added it
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    # Extract JSON object
    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1:
        raw = raw[start:end + 1]

    try:
        data = json.loads(raw)

        # Fix string prices to numbers if Claude returned "$1.97" instead of 1.97
        if "current_prices" in data:
            for p in data["current_prices"]:
                if isinstance(p.get("price"), str):
                    p["price"] = float(
                        p["price"].replace("$", "").replace(",", "").strip()
                    )

        if "price_range" in data:
            pr = data["price_range"]
            if isinstance(pr.get("low"), str):
                pr["low"] = float(pr["low"].replace("$", "").replace(",", "").strip())
            if isinstance(pr.get("high"), str):
                pr["high"] = float(pr["high"].replace("$", "").replace(",", "").strip())

        return data

    except Exception as e:
        print(f"[realtime_price] Parse error: {e}")
        return {"error": f"Could not parse price data for '{item_name}'"}