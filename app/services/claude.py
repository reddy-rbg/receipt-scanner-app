# ─────────────────────────────────────────
# services/claude.py
# All Claude AI logic — upgraded with:
#
# 🤖 LLM Strategy (right model for each task):
#    - claude-opus-4-6         → complex Q&A and analysis (Ask AI)
#    - claude-sonnet-4-6       → receipt scanning, shopping optimizer, price search
#    - claude-haiku-4-5        → fast classification (RAG question routing)
#
# 🔍 RAG (Retrieval Augmented Generation):
#    - Classifies each question with Haiku (fast, cheap)
#    - Retrieves only RELEVANT receipts — not all of them
#    - Reduces tokens 60-80%, improves answer accuracy
#
# 🔗 MCP (Model Context Protocol) on ALL features:
#    - Ask AI       → Opus  + MCP → direct DB query
#    - Shopping     → Sonnet + MCP → live price lookup
#    - Price AI     → Sonnet + MCP → trend analysis
#    - MCP URL: https://mcp.supabase.com/mcp?project_ref=okzsqmoxdzrbhhdrsazy
#
# Functions:
# convert_pdf_to_image()   — PDF to PNG conversion
# get_image_hash()         — MD5 for duplicate detection
# check_duplicate()        — check if already scanned
# scan_receipt_image()     — scan with claude-sonnet-4-6 (vision)
# rag_retrieve()           — smart retrieval of relevant receipts
# answer_question()        — Q&A: MCP+Opus first, RAG+Opus fallback
# optimize_shopping_list() — best store: MCP+Sonnet first, fallback
# get_price_history_ai()   — price trend AI insight via MCP+Sonnet
# get_realtime_price()     — web search prices with Sonnet
# ─────────────────────────────────────────

import base64
import json
import hashlib
import os
from app.config import claude_client, CLAUDE_MODEL, MEDIA_TYPES, supabase

# ── LLM Model Strategy ──
MODEL_OPUS   = "claude-opus-4-6"             # Best reasoning — complex Q&A
MODEL_SONNET = "claude-sonnet-4-6"           # Balanced — scanning, optimizer
MODEL_HAIKU  = "claude-haiku-4-5-20251001"   # Fast — classification only

# ── Supabase MCP ──
SUPABASE_MCP_URL = "https://mcp.supabase.com/mcp?project_ref=okzsqmoxdzrbhhdrsazy"


# ─────────────────────────────────────────
# PDF + DUPLICATE HELPERS
# ─────────────────────────────────────────

def convert_pdf_to_image(pdf_bytes: bytes) -> bytes:
    """Convert PDF to PNG for Claude vision scanning."""
    try:
        from pdf2image import convert_from_bytes
        import io
        images = convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=1)
        if not images:
            raise ValueError("Could not extract pages from PDF")
        buf = io.BytesIO()
        images[0].save(buf, format='PNG')
        buf.seek(0)
        print("[pdf] Converted PDF to PNG")
        return buf.read()
    except ImportError:
        raise ValueError("PDF support not installed. Run: pip install pdf2image pillow")
    except Exception as e:
        raise ValueError(f"Could not read PDF: {str(e)}")


def get_image_hash(image_bytes: bytes) -> str:
    """MD5 fingerprint for duplicate detection."""
    return hashlib.md5(image_bytes).hexdigest()


def check_duplicate(image_hash: str) -> dict | None:
    """Check if this receipt was already scanned. Returns existing record or None."""
    response = supabase.table("receipts").select("*").eq("image_hash", image_hash).execute()
    if response.data:
        return response.data[0]
    return None


# ─────────────────────────────────────────
# RECEIPT SCANNING — claude-sonnet-4-6 (vision)
# ─────────────────────────────────────────

def scan_receipt_image(image_bytes: bytes, filename: str) -> dict:
    """
    Scan a receipt image or PDF using claude-sonnet-4-6 vision.

    Flow:
    1. Hash image → check duplicate
    2. Convert PDF if needed
    3. Send to Claude Sonnet with detailed extraction prompt
    4. Parse and return structured receipt data
    """
    image_hash = get_image_hash(image_bytes)

    existing = check_duplicate(image_hash)
    if existing:
        return {"duplicate": True, "message": "This receipt was already scanned!", "existing_receipt": existing}

    extension = filename.split(".")[-1].lower()

    if extension == "pdf":
        print(f"[scan] Converting PDF: {filename}")
        image_bytes = convert_pdf_to_image(image_bytes)
        media_type = "image/png"
    else:
        media_type = MEDIA_TYPES.get(extension, "image/jpeg")

    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    print(f"[scan] Scanning with {MODEL_SONNET}...")
    message = claude_client.messages.create(
        model=MODEL_SONNET,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_data},
                },
                {
                    "type": "text",
                    "text": """You are a receipt scanner. Carefully read this receipt image.

FIRST — check if this is a readable receipt:
- If NOT a receipt or too blurry, respond ONLY with:
  {"error": "Cannot read receipt clearly. Please take a clearer photo."}
- If it IS a receipt, extract all data below.

WHAT TO EXTRACT:

1. STORE INFO
   - store: exact name as printed (e.g. "WAL*MART", "LOWE'S HOME CENTERS, LLC")
   - address: full store address if visible
   - date: exact date on receipt (e.g. "04/12/26")
   - time: time of purchase if visible
   - payment_method: AMEX, VISA, CASH, etc.

2. ITEMS — extract EVERY item:

   REGULAR items (sold by unit):
   - code: barcode/SKU or null
   - name: exact name as printed
   - quantity: units bought (default 1)
   - unit: "each"
   - unit_price: price per unit
   - price: total line price

   WEIGHTED items (sold by weight — lb, kg, oz, g on receipt):
   - Appear as: "2.71 lb @ $1.97/lb"
   - code: barcode or null
   - name: exact name
   - quantity: weight amount (e.g. 2.71)
   - unit: EXACTLY as printed — "lb", "kg", "oz", or "g"
   - unit_price: price per weight unit
   - price: total line price

   VOLUME items (fl oz, ml, l, gal, pt, qt):
   - name: exact name
   - quantity: volume amount
   - unit: EXACTLY as printed — "fl oz", "ml", "l", "gal", "pt", "qt"
   - unit_price: price per volume unit
   - price: total line price

   MULTI-PACK (e.g. "3 AT 1 FOR 0.60"):
   - name: exact name
   - quantity: total bought
   - unit: "each"
   - unit_price: price per item
   - price: total line price

   CRITICAL UNIT RULES:
   - NEVER default everything to "lb" — only use "lb" for weight-sold items
   - Use EXACTLY the unit shown on the receipt
   - Weight: lb, oz, kg, g
   - Volume: fl oz, ml, l, gal, pt, qt
   - Count: each, ct
   - Examples: chicken by weight→"lb", milk carton→"each", deli per oz→"oz"

3. DISCOUNTS — ALL savings as SEPARATE negative items:
   - {"code": null, "name": "DISCOUNT GIVEN", "quantity": 1, "unit": "each", "unit_price": -3.47, "price": -3.47}

4. TOTALS
   - subtotal, discount (positive), tax, total (must match receipt exactly), total_savings

STRICT: Only extract clearly visible data. Never guess. Never invent.

Return JSON only — no markdown:
{
    "store": "name",
    "address": "address or null",
    "date": "date or null",
    "time": "time or null",
    "payment_method": "method or null",
    "subtotal": 0.00,
    "discount": 0.00,
    "tax": 0.00,
    "total": 0.00,
    "total_savings": 0.00,
    "items": [
        {"code": null, "name": "name", "quantity": 1, "unit": "each", "unit_price": 0.00, "price": 0.00}
    ]
}"""
                }
            ],
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:-1])

    data = json.loads(raw)

    if "error" in data:
        raise ValueError(data["error"])

    data["image_hash"] = image_hash
    print(f"[scan] ✓ {len(data.get('items',[]))} items from {data.get('store','unknown')}")
    return data


# ─────────────────────────────────────────
# RAG — Retrieval Augmented Generation
# ─────────────────────────────────────────

def rag_retrieve(question: str, receipts: list, top_k: int = 12) -> list:
    """
    Smart retrieval: fetch only receipts relevant to the question.

    Uses claude-haiku-4-5 (fast + cheap) to classify the question,
    then filters receipts based on category. Reduces tokens 60-80%.

    Categories: STORE, ITEM, DATE, SPENDING, SAVINGS, PRICE, ALL
    """
    if not receipts:
        return []

    # ── Classify with Haiku ──
    try:
        classify = claude_client.messages.create(
            model=MODEL_HAIKU,
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": f"""Classify into ONE word: STORE, ITEM, DATE, SPENDING, SAVINGS, PRICE, or ALL.

Question: {question}

Reply with ONLY the category word:"""
            }]
        )
        category = classify.content[0].text.strip().upper()
        # Validate it's one of our categories
        if category not in {"STORE","ITEM","DATE","SPENDING","SAVINGS","PRICE","ALL"}:
            category = "ALL"
        print(f"[rag] Category: {category} ({len(receipts)} total receipts)")
    except:
        category = "ALL"

    q = question.lower()
    stop = {"what","where","when","how","much","did","i","buy","cost","the","a","an",
            "is","was","my","have","been","do","does","for","me","at","in","on","to"}

    if category == "STORE":
        # Score receipts by store name match
        keywords = [w for w in q.split() if w not in stop and len(w) > 2]
        scored = []
        for r in receipts:
            store = (r.get("store") or "").lower()
            score = sum(2 for kw in keywords if kw in store)
            scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        top = [r for s, r in scored if s > 0]
        return (top or receipts)[:top_k]

    elif category == "ITEM":
        # Score receipts by item name match
        keywords = [w for w in q.split() if w not in stop and len(w) > 2]
        scored = []
        for r in receipts:
            score = 0
            for item in (r.get("items") or []):
                name = (item.get("name") or "").lower()
                score += sum(2 for kw in keywords if kw in name)
            scored.append((score, r))
        scored.sort(key=lambda x: -x[0])
        top = [r for s, r in scored if s > 0]
        return (top or receipts)[:top_k]

    elif category == "DATE":
        old_words = {"first","oldest","earliest","ever","history"}
        reverse = not any(w in q for w in old_words)
        sorted_r = sorted(receipts, key=lambda r: r.get("created_at") or "", reverse=reverse)
        return sorted_r[:top_k]

    elif category in ("SPENDING", "SAVINGS"):
        sorted_r = sorted(receipts, key=lambda r: r.get("total") or 0, reverse=True)
        return sorted_r[:top_k]

    elif category == "PRICE":
        # Price questions need wider history
        return receipts[:top_k * 2]

    # ALL — return most recent
    return receipts[:top_k]


# ─────────────────────────────────────────
# ASK AI — MCP + RAG + claude-opus-4-6
# ─────────────────────────────────────────

def answer_question(question: str, receipts: list) -> str:
    """
    Answer questions about receipts.

    Priority:
    1. Supabase MCP + claude-opus-4-6 (direct DB, most accurate)
    2. RAG + claude-opus-4-6 (smart retrieval fallback)
    """
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    # ── Mode 1: MCP + Opus ──
    if supabase_key:
        try:
            print(f"[ask] MCP + {MODEL_OPUS}...")
            message = claude_client.messages.create(
                model=MODEL_OPUS,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": f"""You are a personal shopping assistant with direct Supabase MCP access.

TABLE: receipts
COLUMNS: id, store, address, date, time, payment_method, total, subtotal, discount, tax, total_savings, items (JSONB), created_at
ITEMS JSONB: code, name, quantity, unit, unit_price, price

RULES:
- Query only what you need to answer efficiently
- Use unit_price for comparisons (not total)
- Always show unit for weighted items (lb, oz, kg)
- Use exact numbers — never invent data
- Markdown tables for comparisons, **bold** for key numbers

QUESTION: {question}

Query and answer:"""
                }],
                mcp_servers=[{
                    "type": "url",
                    "url": SUPABASE_MCP_URL,
                    "name": "supabase",
                    "authorization_token": supabase_key,
                }],
            )
            answer = "".join(b.text for b in message.content if hasattr(b, "text") and b.text)
            if answer.strip():
                print(f"[ask] ✓ MCP + {MODEL_OPUS}")
                return answer.strip()
        except Exception as e:
            print(f"[ask] MCP failed: {e}")

    # ── Mode 2: RAG + Opus ──
    print(f"[ask] RAG + {MODEL_OPUS}...")
    relevant = rag_retrieve(question, receipts)
    print(f"[rag] {len(relevant)}/{len(receipts)} receipts retrieved")

    message = claude_client.messages.create(
        model=MODEL_OPUS,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""You are a personal shopping assistant.
Total receipts: {len(receipts)} | Retrieved for this question: {len(relevant)}

RULES:
- Only use data below — never make up numbers
- unit_price for comparisons, show units for weighted items
- Markdown tables for comparisons, **bold** for key numbers
- If data isn't here, say so honestly

RECEIPTS:
{json.dumps(relevant, indent=2)}

QUESTION: {question}

Answer precisely:"""
        }],
    )
    print(f"[ask] ✓ RAG + {MODEL_OPUS}")
    return message.content[0].text


# ─────────────────────────────────────────
# SHOPPING OPTIMIZER — MCP + claude-sonnet-4-6
# ─────────────────────────────────────────

def optimize_shopping_list(items: list, item_prices: dict) -> dict:
    """
    Find best store per item.
    Priority: Supabase MCP + Sonnet → fallback to item_prices dict + Sonnet
    """
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    # ── Mode 1: MCP + Sonnet ──
    if supabase_key:
        try:
            print(f"[optimize] MCP + {MODEL_SONNET}...")
            message = claude_client.messages.create(
                model=MODEL_SONNET,
                max_tokens=3000,
                messages=[{
                    "role": "user",
                    "content": f"""Use Supabase MCP to find the best prices for this shopping list.

Query the receipts table — look inside items JSONB for each item name.
Find all unit_prices per store, identify cheapest option.

SHOPPING LIST: {', '.join(items)}

Return ONLY raw JSON:
{{
    "recommendations": [
        {{
            "item": "name",
            "found": true,
            "best_store": "cheapest store",
            "price": 0.00,
            "unit": "lb or each",
            "last_bought": "date",
            "savings_vs_most_expensive": 0.00,
            "all_options": [{{"store": "name", "price": 0.00, "unit": "lb or each"}}]
        }}
    ],
    "not_found": ["items with no history"],
    "summary": {{
        "total_estimated_cost": 0.00,
        "stores_to_visit": ["store names"],
        "total_savings": 0.00,
        "tip": "helpful tip based on data"
    }}
}}"""
                }],
                mcp_servers=[{
                    "type": "url",
                    "url": SUPABASE_MCP_URL,
                    "name": "supabase",
                    "authorization_token": supabase_key,
                }],
            )
            raw = "".join(b.text for b in message.content if hasattr(b, "text") and b.text).strip()
            if "```json" in raw: raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:   raw = raw.split("```")[1].split("```")[0].strip()
            s, e = raw.find('{'), raw.rfind('}')
            if s != -1 and e != -1:
                result = json.loads(raw[s:e+1])
                print(f"[optimize] ✓ MCP + {MODEL_SONNET}")
                return result
        except Exception as e:
            print(f"[optimize] MCP failed: {e}")

    # ── Mode 2: Fallback + Sonnet ──
    print(f"[optimize] Fallback + {MODEL_SONNET}...")
    price_summary = ""
    for item_name, prices in item_prices.items():
        if prices:
            price_summary += f"\n{item_name.upper()}:\n"
            for p in prices[:5]:
                unit_label = f"per {p['unit']}" if p['unit'] != "each" else "each"
                price_summary += f"  - {p['store']}: ${p['unit_price']:.2f} {unit_label} (bought {p['date']})\n"
        else:
            price_summary += f"\n{item_name.upper()}: No history\n"

    message = claude_client.messages.create(
        model=MODEL_SONNET,
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": f"""Smart shopping assistant. Use REAL history only — never invent prices.

HISTORY:
{price_summary}

LIST: {', '.join(items)}

Return ONLY raw JSON:
{{
    "recommendations": [
        {{
            "item": "name",
            "found": true,
            "best_store": "cheapest",
            "price": 0.00,
            "unit": "per lb or each",
            "last_bought": "date",
            "savings_vs_most_expensive": 0.00,
            "all_options": [{{"store": "name", "price": 0.00, "unit": "per lb or each"}}]
        }}
    ],
    "not_found": ["no history items"],
    "summary": {{"total_estimated_cost": 0.00, "stores_to_visit": [], "total_savings": 0.00, "tip": "tip"}}
}}"""
        }]
    )

    raw = message.content[0].text.strip()
    if "```json" in raw: raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:   raw = raw.split("```")[1].split("```")[0].strip()
    s, e = raw.find('{'), raw.rfind('}')
    if s != -1 and e != -1:
        try:
            return json.loads(raw[s:e+1])
        except Exception as ex:
            print(f"[optimize] Parse error: {ex}")

    return {"error": "Could not optimize. Please try again."}


# ─────────────────────────────────────────
# PRICE HISTORY AI INSIGHT — MCP + claude-sonnet-4-6
# ─────────────────────────────────────────

def get_price_history_ai(item_name: str, data_points: list) -> dict:
    """
    AI insight on price trends for an item.
    Uses MCP + Sonnet to analyze price history and give actionable insight.
    """
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    # ── MCP mode ──
    if supabase_key:
        try:
            message = claude_client.messages.create(
                model=MODEL_SONNET,
                max_tokens=600,
                messages=[{
                    "role": "user",
                    "content": f"""Query receipts table for all purchases of "{item_name}".
Look in items JSONB for items whose name contains "{item_name}".
Analyze price trends across stores and dates.

Return ONLY raw JSON:
{{
    "insight": "one actionable sentence about price trend",
    "best_store": "store with lowest unit_price",
    "best_price": 0.00,
    "worst_store": "most expensive store",
    "trend_note": "rising/falling/stable — why"
}}"""
                }],
                mcp_servers=[{
                    "type": "url",
                    "url": SUPABASE_MCP_URL,
                    "name": "supabase",
                    "authorization_token": supabase_key,
                }],
            )
            raw = "".join(b.text for b in message.content if hasattr(b,"text") and b.text).strip()
            s, e = raw.find('{'), raw.rfind('}')
            if s != -1 and e != -1:
                return json.loads(raw[s:e+1])
        except Exception as ex:
            print(f"[price_ai] MCP failed: {ex}")

    # ── Fallback: analyze passed data_points ──
    if data_points:
        try:
            message = claude_client.messages.create(
                model=MODEL_SONNET,
                max_tokens=400,
                messages=[{
                    "role": "user",
                    "content": f"""Analyze these purchase records for "{item_name}":

{json.dumps(data_points[:20], indent=2)}

Return ONLY raw JSON:
{{"insight": "actionable sentence", "best_store": "cheapest store", "best_price": 0.00, "trend_note": "rising/falling/stable"}}"""
                }]
            )
            raw = message.content[0].text.strip()
            s, e = raw.find('{'), raw.rfind('}')
            if s != -1 and e != -1:
                return json.loads(raw[s:e+1])
        except Exception as ex:
            print(f"[price_ai] Analysis failed: {ex}")

    return {}


# ─────────────────────────────────────────
# REAL-TIME PRICE SEARCH — claude-sonnet-4-6 + web search
# ─────────────────────────────────────────

def get_realtime_price(item_name: str) -> dict:
    """
    Search web for current retail prices using claude-sonnet-4-6.
    Two-step: search → format into clean JSON.
    """
    queries = [
        f"{item_name} price per lb Walmart 2026",
        f"{item_name} price Kroger Target grocery 2026",
        f"how much does {item_name} cost grocery store today"
    ]

    all_text = ""
    for query in queries:
        try:
            res = claude_client.messages.create(
                model=MODEL_SONNET,
                max_tokens=512,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
                messages=[{"role": "user", "content": f"Search: {query}. Return only prices found."}]
            )
            for block in res.content:
                if hasattr(block, "text") and block.text.strip():
                    all_text += block.text + " "
        except Exception as ex:
            print(f"[price_search] Failed for '{query}': {ex}")

    all_text = all_text.strip()
    if not all_text:
        return {"error": f"No price data found for '{item_name}'"}

    fmt = claude_client.messages.create(
        model=MODEL_SONNET,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""From this search data, extract prices for "{item_name}":

{all_text}

Return ONLY raw JSON:
{{
    "item": "{item_name}",
    "current_prices": [{{"store": "name", "price": 0.00, "unit": "per lb or each", "source": "brief"}}],
    "price_range": {{"low": 0.00, "high": 0.00}},
    "notes": "brief price context"
}}

Rules: price/low/high must be plain numbers like 1.97. Raw JSON only."""
        }]
    )

    raw = fmt.content[0].text.strip()
    if "```json" in raw: raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:   raw = raw.split("```")[1].split("```")[0].strip()
    s, e = raw.find('{'), raw.rfind('}')
    if s != -1 and e != -1:
        try:
            data = json.loads(raw[s:e+1])
            for p in data.get("current_prices", []):
                if isinstance(p.get("price"), str):
                    p["price"] = float(p["price"].replace("$","").replace(",","").strip())
            pr = data.get("price_range", {})
            for k in ("low","high"):
                if isinstance(pr.get(k), str):
                    pr[k] = float(pr[k].replace("$","").replace(",","").strip())
            return data
        except Exception as ex:
            print(f"[price_search] Parse error: {ex}")

    return {"error": f"Could not parse price data for '{item_name}'"}
