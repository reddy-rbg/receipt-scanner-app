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
import os
import re
from app.config import claude_client, CLAUDE_MODEL, MEDIA_TYPES, supabase

MODEL_SONNET = "claude-sonnet-4-5-20250929"
MODEL_HAIKU = "claude-haiku-4-5-20251001"
SCAN_MODEL = os.getenv("CLAUDE_SCAN_MODEL", MODEL_SONNET)
MAX_CLAUDE_IMAGE_BYTES = 3_600_000
MAX_PDF_SCAN_PAGES = int(os.getenv("MAX_PDF_SCAN_PAGES", "16"))
MAX_SCAN_IMAGE_PAGES = int(os.getenv("MAX_SCAN_IMAGE_PAGES", "8"))
MAX_SCAN_OUTPUT_TOKENS = int(os.getenv("MAX_SCAN_OUTPUT_TOKENS", "16000"))


def convert_pdf_to_images(pdf_bytes: bytes, max_pages: int = MAX_PDF_SCAN_PAGES) -> list[bytes]:
    """
    Convert a PDF file to PNG page images for scanning.

    How it works:
    - pdf2image reads the PDF bytes
    - Converts up to max_pages pages to PIL images at 200 DPI
    - Returns PNG bytes for each page ready for Claude

    Raises ValueError if PDF cannot be converted.
    """
    try:
        from pdf2image import convert_from_bytes
        import io

        # Convert PDF bytes to list of PIL images
        # dpi=200 gives high enough quality for Claude to read text clearly
        images = convert_from_bytes(
            pdf_bytes,
            dpi=200,
            first_page=1,
            last_page=max(1, max_pages)
        )

        if not images:
            raise ValueError("Could not extract any pages from the PDF")

        # Convert the PIL image to PNG bytes
        # BytesIO is an in-memory file buffer — no disk needed
        pages = []
        for image in images:
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            pages.append(img_byte_arr.read())

        print(f"[pdf] Successfully converted {len(pages)} PDF page(s) to PNG images")
        return pages

    except ImportError:
        # pdf2image or poppler not installed
        raise ValueError(
            "PDF support not installed. "
            "Run: pip install pdf2image pillow "
            "and install poppler from https://github.com/oschwartz10612/poppler-windows/releases"
        )
    except Exception as e:
        raise ValueError(f"Could not read PDF file: {str(e)}")


def convert_pdf_to_image(pdf_bytes: bytes) -> bytes:
    """Backward-compatible first-page PDF conversion helper."""
    return convert_pdf_to_images(pdf_bytes, max_pages=1)[0]


PRICE_LIST_CATEGORY_PREFIXES = (
    "INDIAN / ASIAN PRODUCE",
    "AMERICAN PRODUCE",
    "FRESH PRODUCTS - READY TO COOK/EAT",
    "DRY FRUITS & NUTS",
    "FROZEN PRODUCTS",
    "DAIRY PRODUCTS",
    "HOUSEHOLD PRODUCTS",
    "PAPER PRODUCTS",
    "RELIGIOUS PRODUCTS",
    "NEW ARRIVAL",
    "SPECIALTY",
    "CLASSICS",
    "ESSENTIALS",
    "PEPPERS",
    "GINGER",
    "GREENS & HERBS",
    "FRUITS",
    "MANGOES",
)


def _clean_price_list_description(description: str) -> str:
    text = re.sub(r"\s+", " ", str(description or "")).strip(" -")
    upper = text.upper()
    for prefix in sorted(PRICE_LIST_CATEGORY_PREFIXES, key=len, reverse=True):
        if upper.startswith(prefix + " "):
            return text[len(prefix):].strip(" -")
    return text


def _extract_price_list_product_size(description: str) -> str | None:
    text = str(description or "")
    patterns = [
        r"\b\d+(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?\s*(?:LB|LBS|CT|OZ|GM|KG|GAL|L)\b",
        r"\b\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*(?:LB|LBS|CT|OZ|GM|KG|GAL|L)\b",
        r"\b\d+(?:\.\d+)?\s*(?:LB|LBS|CT|OZ|GM|KG|GAL|ML|L|LTR|PCS|ROLLS|CM)\b",
        r"\b\d+\s*X\s*\d+(?:\.\d+)?\s*(?:LB|LBS|CT|OZ|GM|KG|GAL|ML|L|PCS)\b",
    ]
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, text, flags=re.I))
    if not matches:
        return None
    return re.sub(r"\s+", " ", matches[-1]).upper()


def _infer_price_list_vendor(text: str, filename: str) -> str:
    lowered = text.lower()
    if "omproduce.com" in lowered or "om produce" in lowered:
        return "OM Produce"
    email_match = re.search(r"[\w.+-]+@([\w.-]+)", lowered)
    if email_match:
        domain = email_match.group(1).split(".")[0]
        cleaned = re.sub(r"[^a-z0-9]+", " ", domain).strip()
        if cleaned:
            return cleaned.title()
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem or "Vendor Price List"


def try_parse_digital_price_list_pdf(pdf_bytes: bytes, filename: str) -> dict | None:
    """Parse digital wholesale/vendor price-list PDFs without Claude token limits.

    Vision extraction is excellent for photographed receipts, but a 14-page
    supplier catalog can contain hundreds of rows. Asking Claude to return all
    rows in one JSON response truncates the result.  For text PDFs with
    DESCRIPTION/PRICE/QTY style rows, parse deterministically and save through
    the same normal receipt pipeline.
    """
    try:
        import io
        import pdfplumber
    except Exception as error:
        print(f"[pdf_price_list] pdfplumber unavailable; falling back to Claude scan: {error}")
        return None

    price_line = re.compile(r"^\s*(?P<description>.+?)\s+(?P<price>\d+\.\d{2})\s*$")
    page_counts: list[int] = []
    items: list[dict] = []
    all_text: list[str] = []

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                all_text.append(text)
                page_count = 0
                for line in text.splitlines():
                    match = price_line.match(line)
                    if not match:
                        continue
                    description = _clean_price_list_description(match.group("description"))
                    if not description or description.upper() in {"DESCRIPTION", "PRICE", "QTY"}:
                        continue
                    try:
                        price = float(match.group("price"))
                    except Exception:
                        continue
                    if price <= 0:
                        continue
                    product_size = _extract_price_list_product_size(description)
                    items.append({
                        "code": None,
                        "name": description,
                        "normalized_name": description.lower().strip(),
                        "product_size": product_size,
                        "quantity": 1,
                        "unit": "each",
                        "unit_price": price,
                        "price": price,
                        "quantity_type": "package_size" if product_size else "each",
                        "unit_label": product_size or "each",
                        "explicit_quantity": False,
                        "source": "price_list",
                        "metadata": {
                            "source_document": "digital_price_list_pdf",
                            "page": page_number,
                        },
                    })
                    page_count += 1
                page_counts.append(page_count)
    except Exception as error:
        print(f"[pdf_price_list] Could not parse digital PDF text; falling back to Claude scan: {error}")
        return None

    joined_text = "\n".join(all_text)
    lowered = joined_text.lower()
    price_list_markers = [
        "description price qty",
        "effective from",
        "order by email",
        "pricing and availability",
    ]
    marker_count = sum(1 for marker in price_list_markers if marker in lowered)
    if len(items) < 20 or marker_count < 2:
        return None

    effective_match = re.search(
        r"Effective\s+From:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})",
        joined_text,
        re.I,
    )
    start_date = effective_match.group(1) if effective_match else None
    end_date = effective_match.group(2) if effective_match else None
    address_match = re.search(r"\b\d{3,6}\s+[A-Za-z0-9 .'-]+,\s*[A-Za-z .'-]+\s+[A-Z]{2}-?\d{5}\b", joined_text)
    address = address_match.group(0).replace("TX-", "TX ") if address_match else None
    store = _infer_price_list_vendor(joined_text, filename)

    notes = [
        "Parsed as a digital wholesale/vendor price-list PDF and saved through the normal receipt flow.",
        f"Extracted {len(items)} priced item rows across {len(page_counts)} page(s).",
        f"Page item counts: {page_counts}",
        "Quantity columns were blank; each listed price was saved as one receipt-like line with quantity 1.",
        "Final paid total was not printed; total is null.",
    ]
    if effective_match:
        notes.append(f"Effective From: {start_date} - {end_date}")

    return {
        "store": store,
        "address": address,
        "date": start_date,
        "time": None,
        "payment_method": None,
        "transaction_number": None,
        "receipt_number": None,
        "invoice_number": None,
        "order_number": None,
        "subtotal": 0.0,
        "discount": 0.0,
        "tax": 0.0,
        "total": None,
        "total_savings": 0.0,
        "items": items,
        "handwritten_items": [],
        "returned_items": [],
        "manual_adjustments": [],
        "validation": {
            "is_receipt": True,
            "confidence": 0.98,
            "document_type": "wholesale_price_list",
            "deterministic_pdf_parse": True,
        },
        "validation_notes": notes,
    }


def detect_image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def compress_image_for_claude(image_bytes: bytes) -> tuple[bytes, str]:
    """Keep raw image bytes below Claude's base64 image limit."""
    if len(image_bytes) <= MAX_CLAUDE_IMAGE_BYTES:
        return image_bytes, detect_image_media_type(image_bytes)

    try:
        from PIL import Image
        import io

        image = Image.open(io.BytesIO(image_bytes))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")

        attempts = [
            (1800, 72),
            (1500, 62),
            (1200, 52),
            (1000, 45),
            (800, 38),
            (650, 32),
        ]

        best = image_bytes
        for max_width, quality in attempts:
            working = image.copy()
            if working.width > max_width:
                ratio = max_width / working.width
                working = working.resize((max_width, max(1, int(working.height * ratio))))

            output = io.BytesIO()
            working.save(output, format="JPEG", quality=quality, optimize=True)
            candidate = output.getvalue()
            best = candidate
            if len(candidate) <= MAX_CLAUDE_IMAGE_BYTES:
                print(f"[scan] Compressed image for Claude: {len(image_bytes)} -> {len(candidate)} bytes")
                return candidate, "image/jpeg"

        if len(best) > MAX_CLAUDE_IMAGE_BYTES:
            raise ValueError(
                "Receipt image is too large for AI scanning. Please crop closer to the receipt or retake the photo."
            )

        return best, "image/jpeg"
    except ValueError:
        raise
    except Exception as e:
        print(f"[scan] Image compression skipped: {e}")
        return image_bytes, detect_image_media_type(image_bytes)


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


def get_combined_image_hash(files: list[tuple[bytes, str]]) -> str:
    """Stable duplicate fingerprint for a multi-page image/PDF scan."""
    hasher = hashlib.md5()
    for file_bytes, filename in files:
        hasher.update(filename.encode("utf-8", errors="ignore"))
        hasher.update(b"\0")
        hasher.update(file_bytes)
        hasher.update(b"\0PAGE\0")
    return hasher.hexdigest()


def check_duplicate(image_hash: str, user_id: str | None = None, guest_session_id: str | None = None) -> dict | None:
    """
    Check if this exact receipt image was already scanned before.

    How it works:
    - Look up the image hash in the database
    - If found return the existing receipt record
    - If not found return None so scanning proceeds

    This prevents the same receipt being saved twice by accident.
    """

    query = supabase.table("receipts").select("*").eq("image_hash", image_hash)

    # Duplicate detection must be scoped to the current owner.
    if user_id:
        query = query.eq("user_id", user_id)
    elif guest_session_id:
        query = query.eq("is_guest", True).eq("guest_session_id", guest_session_id)
    else:
        return None

    response = query.execute()

    # If any rows returned this receipt was already scanned
    if response.data:
        return response.data[0]

    # No match found — receipt is new
    return None


def parse_receipt_json(raw: str) -> dict:
    def clean_json_text(value: str) -> str:
        value = (value or "").strip()
        if value.startswith("```"):
            value = "\n".join(value.split("\n")[1:-1]).strip()
        start = value.find("{")
        end = value.rfind("}")
        if start != -1 and end != -1:
            value = value[start:end + 1]
        value = value.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
        value = re.sub(r",\s*([}\]])", r"\1", value)
        return value

    def repair_with_claude(bad_json: str, error_message: str) -> str:
        if claude_client is None:
            return ""
        try:
            response = claude_client.messages.create(
                model=MODEL_HAIKU,
                max_tokens=2200,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": f"""Repair this malformed receipt/invoice JSON.
Return ONLY valid JSON. No markdown. No explanation.
Do not add new fields or invent data; only fix syntax such as missing commas, quotes, braces, or trailing commas.

Parser error:
{error_message}

Malformed JSON:
{bad_json}
""",
                }],
            )
            return "".join(block.text for block in response.content if hasattr(block, "text")).strip()
        except Exception as e:
            print(f"[scan] JSON repair failed: {e}")
            return ""

    raw = raw.strip()
    cleaned = clean_json_text(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as first_error:
        repaired = clean_json_text(repair_with_claude(cleaned, str(first_error)))
        if repaired:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as second_error:
                print(f"[scan] JSON parse failed after repair: {second_error}")
        print(f"[scan] JSON parse failed: {first_error}")
        raise ValueError(
            "I could not read this receipt or invoice cleanly. Please retake it closer, make sure the full document is visible, and avoid shadows or blur."
        )


def normalize_receipt_data(data: dict) -> dict:
    import re as _re

    size_re = _re.compile(
        r"\b(\d+(?:\.\d+)?)\s*-?\s*(GAL|GALLON|GALLONS|OZ|FL\s*OZ|LB|LBS|QT|QTS|PT|PTS|CT|EA|ML|L|LTR|LITER|LITERS)\b",
        _re.I,
    )
    qty_re = _re.compile(r"\b(QTY\s*\d+|\d+\s*@|\d+\s+EA\b|\d+\s+FOR\b|\d+\s+AT\b)", _re.I)
    weight_units = {"lb", "lbs", "oz", "kg", "g", "mg"}
    volume_units = {"fl oz", "floz", "ml", "l", "liter", "liters", "gal", "gallon", "gallons", "pt", "pint", "qt", "quart"}
    count_units = {"each", "ea", "ct", "count", "pack"}

    def _safe_float(value, default=0.0) -> float:
        try:
            if value is None or value == "":
                return default
            return float(str(value).replace("$", "").replace(",", "").strip())
        except Exception:
            return default

    def quantity_type(unit: str | None, product_size: str | None) -> str:
        normalized = _re.sub(r"\s+", " ", str(unit or "each").strip().lower())
        compact = normalized.replace(" ", "")
        if normalized in weight_units or compact in weight_units:
            return "weight"
        if normalized in volume_units or compact in volume_units:
            return "volume"
        if normalized in count_units or compact in count_units:
            return "package_size" if product_size else "count"
        return "package_size" if product_size else "each"

    def clean_item(item: dict, source: str = "printed") -> dict:
        name = str(item.get("name") or item.get("item") or "").strip()
        item["name"] = name
        item.setdefault("source", source)
        match = size_re.search(name)
        if match and not item.get("product_size"):
            unit = _re.sub(r"\s+", "", match.group(2).upper())
            item["product_size"] = f"{match.group(1)}-{unit}"
        if not item.get("normalized_name"):
            item["normalized_name"] = (
                name.lower()
                .replace("pren", "prem")
                .replace("prern", "prem")
                .replace("prcm", "prem")
                .strip()
            )
        if item.get("product_size") and not qty_re.search(name):
            item["quantity"] = 1
            item["unit"] = item.get("unit") or "each"
            item["unit_price"] = item.get("price") or item.get("unit_price")
            item["explicit_quantity"] = False
        else:
            item["explicit_quantity"] = bool(item.get("explicit_quantity")) or bool(qty_re.search(name))
        item["quantity_type"] = quantity_type(item.get("unit"), item.get("product_size"))
        if item.get("product_size") and item.get("unit", "each") == "each":
            item["unit_label"] = f"{item.get('product_size')} package"
        elif item.get("unit") and item.get("unit") != "each":
            item["unit_label"] = f"per {item.get('unit')}"
        else:
            item["unit_label"] = "each"
        return item

    def item_tokens(name: str) -> list[str]:
        return [token for token in _re.sub(r"[^a-z0-9]+", " ", str(name).lower()).split() if token]

    def looks_like_continuation(previous: dict, current: dict, following: dict | None = None) -> bool:
        previous_unit = str(previous.get("unit") or "each").strip().lower()
        if previous_unit and previous_unit != "each":
            return False
        prev_name = str(previous.get("name") or "").strip()
        curr_name = str(current.get("name") or "").strip()
        prev_tokens = item_tokens(prev_name)
        curr_tokens = item_tokens(curr_name)
        if len(prev_tokens) < 2 or not curr_tokens or len(curr_tokens) > 3:
            return False
        continuation_terms = {
            "icecream", "ice", "cream", "badam", "kulfi", "bar", "cake", "candy",
            "biscuit", "biscuits", "cookies", "cookie", "100", "200", "250", "500",
        }
        has_descriptor = bool(set(curr_tokens) & continuation_terms) or any(token.isdigit() for token in curr_tokens)
        if not has_descriptor:
            return False
        current_price = _safe_float(current.get("price"), 0)
        following_price = _safe_float((following or {}).get("price"), None)
        # OCR often gives a wrapped description line the next item's price. If that
        # happens, merge the text into the previous item and keep the previous price.
        return current_price == 0 or current_price == following_price or len(curr_tokens) <= 2

    def merge_split_item_lines(items: list[dict]) -> list[dict]:
        merged: list[dict] = []
        index = 0
        while index < len(items):
            current = dict(items[index])
            current_name = str(current.get("name") or "")
            current_unit = str(current.get("unit") or "each").strip().lower()
            badam_tail = _re.match(r"^(.*?)(\bVL\s+Badam\s+Carnival.*)$", current_name, _re.I)
            if (
                badam_tail
                and current_unit
                and current_unit != "each"
                and index + 1 < len(items)
                and _re.search(r"ice\s*cream|icecream", str(items[index + 1].get("name") or ""), _re.I)
            ):
                current["name"] = badam_tail.group(1).strip()
                current["normalized_name"] = current["name"].lower().strip()
                merged.append(current)
                continuation = dict(items[index + 1])
                continuation["name"] = f"{badam_tail.group(2).strip()} {str(continuation.get('name') or '').strip()}".strip()
                continuation["normalized_name"] = continuation["name"].lower().strip()
                continuation["merged_from_split_lines"] = True
                merged.append(continuation)
                index += 2
                continue
            if index + 1 < len(items) and looks_like_continuation(current, items[index + 1], items[index + 2] if index + 2 < len(items) else None):
                continuation = items[index + 1]
                current["name"] = f"{current.get('name', '').strip()} {str(continuation.get('name') or '').strip()}".strip()
                current["normalized_name"] = current["name"].lower().strip()
                current["merged_from_split_lines"] = True
                index += 2
            else:
                index += 1
            merged.append(current)
        return merged

    data["items"] = merge_split_item_lines([clean_item(item, "printed") for item in (data.get("items") or []) if isinstance(item, dict)])
    data["handwritten_items"] = [
        clean_item(item, "handwritten") for item in (data.get("handwritten_items") or []) if isinstance(item, dict)
    ]

    existing_names = {(item.get("name"), item.get("price")) for item in data["items"]}
    for item in data["handwritten_items"]:
        key = (item.get("name"), item.get("price"))
        if key not in existing_names:
            data["items"].append(item)
            existing_names.add(key)

    for field in ("returned_items", "manual_adjustments", "validation_notes"):
        if field not in data or data.get(field) is None:
            data[field] = []
    if data.get("total") in ("", "null"):
        data["total"] = None
    invoice_text = " ".join([
        str(data.get("store") or ""),
        str(data.get("address") or ""),
        " ".join(str(note) for note in data.get("validation_notes") or []),
        " ".join(str(item.get("name") or "") for item in data.get("items") or [] if isinstance(item, dict)),
    ]).lower()
    invoice_like = any(term in invoice_text for term in [
        "invoice",
        "wholesale",
        "sold to",
        "ship to",
        "tobacco license",
        "price list",
        "pricing and availability",
        "effective from",
        "order by email",
    ])
    has_line_amounts = any(_safe_float(item.get("price"), 0) > 0 for item in data.get("items") or [] if isinstance(item, dict))
    if invoice_like and _safe_float(data.get("total"), 0) == 0 and has_line_amounts:
        data["total"] = None
        data["validation_notes"].append("Final invoice/price-list total was not visible on the scanned page.")
    if not isinstance(data.get("validation"), dict):
        data["validation"] = {"is_receipt": True, "confidence": None}
    return data


def validate_scan_quality(data: dict) -> None:
    """Reject low-quality receipt reads before saving incorrect item data."""
    validation = data.get("validation") if isinstance(data.get("validation"), dict) else {}
    confidence = validation.get("confidence")
    try:
        confidence_value = float(confidence) if confidence is not None else None
    except Exception:
        confidence_value = None

    notes = " ".join(str(note).lower() for note in (data.get("validation_notes") or []))
    items = data.get("items") or []
    total = data.get("total")
    store = str(data.get("store") or "").strip().lower()

    low_quality_terms = [
        "blurry", "blur", "unclear", "too small", "far away", "distant", "low resolution",
        "hard to read", "cannot read", "not legible",
    ]

    if validation.get("is_receipt") is False:
        raise ValueError("This does not look like a receipt. Please scan a clear receipt photo.")

    if confidence_value is not None and confidence_value < 0.72:
        raise ValueError("Cannot read receipt clearly. Please retake the photo closer, sharper, and with the full receipt visible.")

    if any(term in notes for term in low_quality_terms):
        raise ValueError("Cannot read receipt clearly. Please retake the photo closer, sharper, and with the full receipt visible.")

    if not items or len(items) < 1:
        raise ValueError("No readable receipt items found. Please retake the photo closer to the receipt.")

    if not store or store in {"unknown", "unknown store"}:
        raise ValueError("The store name is not readable. Please retake the photo closer and keep the top of the receipt visible.")

    if total in (None, "", 0, 0.0) and len(items) <= 2:
        raise ValueError("The receipt total and items are not readable enough. Please retake a clearer photo.")


def scan_receipt_image(
    image_bytes: bytes,
    filename: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    image_hash_override: str | None = None,
    page_images_override: list[bytes] | None = None,
) -> dict:
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
    image_hash = image_hash_override or get_image_hash(image_bytes)

    # ── Step 2: Check for duplicate ──
    # Look up hash in database — returns existing receipt or None
    existing = check_duplicate(image_hash, user_id=user_id, guest_session_id=guest_session_id)
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

    if extension == "pdf" and page_images_override is None:
        parsed_price_list = try_parse_digital_price_list_pdf(image_bytes, filename)
        if parsed_price_list:
            print(
                "[scan] Digital price-list PDF parsed deterministically: "
                f"{len(parsed_price_list.get('items') or [])} item row(s)"
            )
            data = normalize_receipt_data(parsed_price_list)
            validate_scan_quality(data)
            data["image_hash"] = image_hash
            if user_id:
                data["owner_user_id"] = user_id
            if guest_session_id:
                data["guest_session_id"] = guest_session_id
            return data

    # ── Step 4: Handle PDF files ──
    # PDFs must be converted to images before sending to Claude
    # Claude Vision cannot read PDF format directly
    if page_images_override is not None:
        page_images = page_images_override
    elif extension == "pdf":
        print(f"[scan] PDF detected — converting to image: {filename}")
        # convert_pdf_to_image raises ValueError if conversion fails
        page_images = convert_pdf_to_images(image_bytes)
    else:
        # ── Step 5: Detect image type for regular images ──
        # e.g. "jpg" → "image/jpeg"
        # e.g. "png" → "image/png"
        page_images = [image_bytes]

    image_blocks = []
    for page_index, page_bytes in enumerate(page_images, 1):
        page_bytes, page_media_type = compress_image_for_claude(page_bytes)
        image_data = base64.standard_b64encode(page_bytes).decode("utf-8")
        image_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": page_media_type,
                "data": image_data,
            },
        })
        if len(page_images) > 1:
            image_blocks.append({"type": "text", "text": f"Page {page_index} of {len(page_images)}"})

    # ── Step 6: Send to Claude with detailed extraction instructions ──
    message = claude_client.messages.create(
        model=SCAN_MODEL,
        max_tokens=MAX_SCAN_OUTPUT_TOKENS,
        messages=[
            {
                "role": "user",
                "content": image_blocks + [
                    {
                        # Detailed extraction instructions for Claude
                        "type": "text",
                        "text": """You are a receipt, invoice, and wholesale vendor price-list scanner. Carefully read this document image.

FIRST — check if this is a readable receipt, invoice, or wholesale vendor price list:
- Receipts and invoices are allowed when they show a merchant/vendor, item/service lines, and totals.
- Wholesale/vendor price lists, order guides, and catalog price sheets are also allowed when they show a vendor/store name plus item descriptions and prices, even if QTY columns are blank and no final paid total is printed.
- For wholesale/vendor price lists, treat the document as a receipt-like business purchase record because the user may upload supplier purchase documents for resale inventory.
- Messy receipts/invoices are allowed. If the document is wrinkled, folded, crushed, stained, faded, curved, or partially shadowed but the vendor, totals, and item lines are still readable, scan it.
- Do not reject only because the receipt is damaged, folded, or not neat.
- Reject the scan only if the receipt/document is too far away, too small in the image, blurry, low resolution, or if item names and prices are not clearly legible.
- Do NOT reject a wholesale/vendor price list only because it has no subtotal, tax, payment method, transaction number, or final total.
- Reject the scan if you can only guess item names or prices.
- If NOT a receipt/invoice/wholesale price list or too unclear to read accurately, respond ONLY with:
  {"error": "Cannot read this receipt or invoice clearly. Please retake the photo closer, sharper, and with the full document visible."}
- If it IS readable, extract all data below.
- If multiple pages are provided, extract rows from every page in order and combine them into one invoice/receipt JSON.
- For damaged/folded receipts or invoices, extract all readable lines and add unclear or hidden parts to validation_notes instead of inventing them.
- In validation.confidence, use 0.90+ only when store/vendor, date or effective date, and most item lines/prices are clearly readable. Use below 0.72 for far, tiny, blurry, or uncertain scans.


CRITICAL PRODUCT SIZE VS QUANTITY RULES:
- Do NOT treat product size/packaging as purchased quantity.
- Text inside item names like "2.00-GAL", "10.00-OZ", "32OZ", "1 QT", "5 LB", "12 CT", "16 FL OZ" is product_size/packaging, not quantity.
- Lowe's example: "5331976 2.00-GAL ROSE PINK PREM 12.49" means name="2.00-GAL ROSE PINK PREM", product_size="2.00-GAL", quantity=1, unit="each", unit_price=12.49, price=12.49.
- Lowe's example: "5331976 2.00-GAL ROSE PINK PREM 24.98" means name="2.00-GAL ROSE PINK PREM", product_size="2.00-GAL", quantity=1, unit="each", unit_price=24.98, price=24.98.
- Only set quantity greater than 1 when the receipt explicitly shows purchased quantity separate from the item size, such as "QTY 2", "2 @ 12.49", "2 EA", or a clear quantity column.
- If OCR reads PREM as PREN/PRCM/PRERN, keep the visible text but add normalized_name as the likely corrected product name.
- If the same product appears on different receipts with different prices, they are separate purchase events; do not combine into one quantity.

WHAT TO EXTRACT:

1. STORE INFO
   - store: exact store name as printed (e.g. "WAL*MART" or "LOWE'S HOME CENTERS, LLC")
   - address: full store address if visible (e.g. "PEA RIDGE, AR")
   - date: exact purchase date printed on receipt/invoice (e.g. "04/12/26"). For price lists with an "Effective From" date range, use the start date as date and add the full effective range to validation_notes.
   - time: time of purchase if visible (e.g. "12:27:30")
   - payment_method: how they paid (e.g. "AMEX", "VISA", "CASH")
   - transaction_number: transaction/reference number if clearly labeled; otherwise null
   - receipt_number: receipt number if clearly labeled; otherwise null
   - invoice_number: invoice number if clearly labeled; otherwise null
   - order_number: order number if clearly labeled; otherwise null

2. ITEMS — extract EVERY item carefully:
- For invoices with table columns like UPC, Product Name / Description, SO Qty, Qty, Price, Sold Price, Amount:
  - Extract EVERY visible product row from the invoice page, top to bottom. Do not stop after the first 8-10 rows.
  - code: UPC.
  - name: Product Name / Description.
  - quantity: use the shipped/sold Qty column, not SO Qty.
  - unit: "each" unless the row clearly shows another sales unit.
  - unit_price: use Sold Price when visible; otherwise use Price.
  - price: use Amount. This is the line total.
  - source: "invoice".
  - If the invoice says Page 1 of 2, only extract visible rows from this image and add a validation note that more pages may be needed for full invoice totals.

- For wholesale/vendor price lists with columns like DESCRIPTION, PRICE, QTY:
  - Extract EVERY visible product row from every scanned page, top to bottom and left column before right column when the page is two-column.
  - store: vendor/company name printed on the document, such as "OM Produce".
  - code: null unless a SKU/UPC/item code is visible.
  - name: exact DESCRIPTION text.
  - normalized_name: lowercase searchable item name.
  - product_size: package/pack size from the description, such as "25-30 LB", "5 LB", "12 CT", "16X1 LB", or "8/800 GM".
  - quantity: use the QTY column only if a quantity is filled in. If the QTY column is blank, set quantity to 1.
  - explicit_quantity: true only when the QTY column is filled or an explicit order quantity is printed; otherwise false.
  - unit: "each" unless the row clearly represents a weight/volume purchase quantity separate from product size.
  - unit_price: use the PRICE column.
  - price: if QTY is filled, use quantity * unit_price; if QTY is blank, use the PRICE column value.
  - quantity_type: "package_size" when the size is part of the description and QTY is blank.
  - unit_label: use the product_size when available, otherwise "each".
  - source: "price_list".
  - Do NOT treat pack sizes like "25-30 LB", "5 LB", or "12 CT" as purchased quantity.
  - Do NOT invent a final receipt total for price lists.

   For REGULAR items (sold by unit/each):
   - code: product barcode/SKU printed near item (e.g. "007874235334") or null
   - name: exact product name as printed (e.g. "GV SPAG 32O")
   - normalized_name: lowercase searchable item name with obvious OCR variants corrected, e.g. PREN -> PREM
   - product_size: package size if part of the item name, e.g. "2.00-GAL", "32-OZ", "12-CT"; otherwise null
   - quantity: number of units bought (default 1)
   - unit: "each" for regular items
   - unit_price: price per single unit
   - price: total line price
   - quantity_type: "each", "count", "weight", "volume", or "package_size"
   - unit_label: customer-friendly label such as "each", "per lb", "per fl oz", or "2.00-GAL package"
   - explicit_quantity: true only if the receipt visibly shows QTY 2, 2 @ price, 2 EA, or a quantity column
   - source: "printed"

   For WEIGHTED items (sold by weight — look for lb, kg, oz, g on the receipt):
   - These appear as: "2.71 lb @ $1.97/lb" = 2.71 lbs at $1.97 per lb
   - code: barcode if visible or null
   - name: exact product name (e.g. "TOMATO 4X5")
   - quantity: the weight amount (e.g. 2.71)
   - unit: EXACTLY the weight unit printed — "lb", "kg", "oz", or "g"
   - unit_price: price per unit weight (e.g. 1.97)
   - price: total line price (quantity x unit_price)
   - quantity_type: "weight"
   - unit_label: "per lb", "per kg", "per oz", or "per g"

   For VOLUME items (sold by liquid volume — look for fl oz, ml, l, gal, pt, qt):
   - These include beverages, oils, cleaning products, juices, milk, etc.
   - name: exact product name
   - quantity: the volume amount as printed
   - unit: EXACTLY the volume unit printed — "fl oz", "ml", "l", "gal", "pt", "qt"
   - unit_price: price per volume unit
   - price: total line price
   - quantity_type: "volume"
   - unit_label: "per fl oz", "per ml", "per l", "per gal", "per pt", or "per qt"

   For MULTI-PACK items (e.g. "3 AT 1 FOR 0.60"):
   - name: exact product name
   - quantity: total number bought (e.g. 3)
   - unit: "each"
   - unit_price: price per single item (e.g. 0.60)
   - price: total line price (e.g. 1.80)

   UNIT RULES — VERY IMPORTANT:
   - NEVER default all items to "lb" — only use "lb" for actual weight-sold items
   - Read the receipt carefully — use EXACTLY the unit shown on the receipt
   - Weight units: lb, oz, kg, g
   - Volume units: fl oz, ml, l, liter, gal, pt, qt
   - Count units: each, ct
   - Examples:
     * Chicken breast sold by weight → unit: "lb"
     * Milk 64 fl oz carton → unit: "each" (it's sold as a single item)
     * Deli meat sliced per lb → unit: "lb"
     * Canned goods → unit: "each"
     * Shredded carrots 10 oz bag → unit: "each"
     * Bulk nuts sold per oz → unit: "oz"
     * Oil sold per fl oz → unit: "fl oz"

3. DISCOUNTS — extract ALL savings as SEPARATE items:
   - Include any discount, coupon, or savings line
   - Use NEGATIVE prices for all discounts
   - name format: "DISCOUNT: [description]"
   - Example: {"code": null, "name": "DISCOUNT GIVEN", "quantity": 1, "unit": "each", "unit_price": -3.47, "price": -3.47}

4. HANDWRITTEN / MANUAL TEXT
   - Extract handwritten items written on the receipt into handwritten_items.
   - A handwritten item such as "24/7 Red 100s $4.50" is a handwritten item.
   - Extract handwritten price changes, notes, or unclear negative values into manual_adjustments.
   - Do NOT treat a small handwritten negative value such as "-1.59" as a return unless the receipt clearly says RETURN, REFUND, VOID, or has clear return context.
   - Only put items in returned_items when return/refund evidence is clear.

5. TOTALS
   - subtotal: amount before discount and tax (0.00 if not shown)
   - discount: total discount amount as POSITIVE number (e.g. 3.47)
   - tax: tax amount charged (0.00 if not shown)
   - total: final total amount paid — must match receipt/invoice exactly
   - For invoices where the final total is not visible on this page, use total: null. Do NOT use 0.00 unless the document explicitly shows a zero total.
   - For wholesale/vendor price lists or catalog sheets without a final paid total, use subtotal: null, tax: 0.00, discount: 0.00, and total: null. Do NOT sum all catalog item prices into a fake total.
   - total_savings: total savings shown at bottom (0.00 if not shown)

STRICT RULES:
- Only extract what is CLEARLY visible — never guess or invent
- Item names must be EXACT as printed — do not paraphrase
- total must match exactly what is printed on the receipt/invoice; use null when not visible
- For weighted items ALWAYS capture unit and unit_price
- Extract labeled transaction/receipt/invoice/order numbers only into their dedicated top-level fields. Never put them into item names.
- Do NOT include survey URLs, cashier names, store membership numbers, full card numbers, authorization codes, or change due.

Return JSON only — no extra text, no markdown:
{
    "store": "store name",
    "address": "address or null",
    "date": "date or null",
    "time": "time or null",
    "payment_method": "payment method or null",
    "transaction_number": "transaction/reference number or null",
    "receipt_number": "receipt number or null",
    "invoice_number": "invoice number or null",
    "order_number": "order number or null",
    "subtotal": 0.00,
    "discount": 0.00,
    "tax": 0.00,
    "total": null,
    "total_savings": 0.00,
    "items": [
        {
            "code": "barcode or null",
            "name": "exact item name",
            "normalized_name": "search normalized item name",
            "product_size": "package size or null",
            "quantity": 1,
            "unit": "each",
            "unit_price": 0.00,
            "price": 0.00,
            "quantity_type": "each",
            "unit_label": "each",
            "explicit_quantity": false,
            "source": "printed"
        }
    ],
    "handwritten_items": [],
    "returned_items": [],
    "manual_adjustments": [],
    "validation": {"is_receipt": true, "confidence": 0.0},
    "validation_notes": []
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
    data = parse_receipt_json(raw)

    # ── Step 10: Check if Claude returned an error ──
    # This happens when receipt is unreadable or not a receipt
    if "error" in data:
        raise ValueError(data["error"])

    # ── Step 11: Attach image hash for future duplicate detection ──
    # Stored in database so scanning the same file again is detected

    data = normalize_receipt_data(data)
    validate_scan_quality(data)

    # Normalize item metadata for RAG/search. Keep each receipt line as its own event.
    import re as _re
    _size_re = _re.compile(r"\b(\d+(?:\.\d+)?)\s*-?\s*(GAL|GALLON|GALLONS|OZ|FL\s*OZ|LB|LBS|QT|QTS|PT|PTS|CT|EA|ML|L|LTR|LITER|LITERS)\b", _re.I)
    for _item in data.get("items", []) or []:
        _name = str(_item.get("name") or "")
        _m = _size_re.search(_name)
        if _m and not _item.get("product_size"):
            _unit = _re.sub(r"\s+", "", _m.group(2).upper())
            _item["product_size"] = f"{_m.group(1)}-{_unit}"
        if not _item.get("normalized_name"):
            _item["normalized_name"] = _name.lower().replace("pren", "prem").replace("prcm", "prem").strip()
        # If a product size exists and no explicit QTY marker exists, force quantity to 1.
        if _item.get("product_size") and not _re.search(r"\b(QTY\s*\d+|\d+\s*@|\d+\s+EA\b|\d+\s+FOR\b|\d+\s+AT\b)", _name, _re.I):
            _item["quantity"] = 1
            _item["unit"] = _item.get("unit") or "each"
            _item["unit_price"] = _item.get("price") or _item.get("unit_price")
            _item["explicit_quantity"] = False
            _item["quantity_note"] = "product size detected; quantity set to 1 unless receipt explicitly shows quantity"

    for _field in ("handwritten_items", "returned_items", "manual_adjustments", "validation_notes"):
        if _field not in data or data.get(_field) is None:
            data[_field] = []
    if not isinstance(data.get("validation"), dict):
        data["validation"] = {"is_receipt": True, "confidence": None}

    data["image_hash"] = image_hash

    if user_id:
        data["owner_user_id"] = user_id
    if guest_session_id:
        data["guest_session_id"] = guest_session_id

    return data


def scan_receipt_image_pages(
    files: list[tuple[bytes, str]],
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> dict:
    """Scan multiple receipt/invoice page photos as one combined document."""
    clean_files = [(content, name) for content, name in files if content]
    if not clean_files:
        raise ValueError("No receipt pages were uploaded.")
    if len(clean_files) > MAX_SCAN_IMAGE_PAGES:
        raise ValueError(f"Please upload {MAX_SCAN_IMAGE_PAGES} pages or fewer at one time.")

    for _, filename in clean_files:
        extension = filename.split(".")[-1].lower()
        if extension == "pdf":
            raise ValueError("Use the PDF upload option for PDF files.")
        if extension not in MEDIA_TYPES:
            raise ValueError(f"Unsupported page type: .{extension}. Please use jpg, png, webp, or gif.")

    page_images = [content for content, _ in clean_files]
    return scan_receipt_image(
        page_images[0],
        f"multi-page-receipt-{len(page_images)}-pages.jpg",
        user_id=user_id,
        guest_session_id=guest_session_id,
        image_hash_override=get_combined_image_hash(clean_files),
        page_images_override=page_images,
    )


def answer_question(question: str, receipts: list) -> str:
    """
    Answer a natural language question about the user's receipts.

    Uses Supabase MCP globally — works on Railway, mobile, anywhere.
    MCP URL: https://mcp.supabase.com/mcp?project_ref=okzsqmoxdzrbhhdrsazy

    Claude queries the database directly using MCP tools.
    Falls back to text mode if MCP is unavailable.

    Returns Claude's answer as a markdown string.
    """
    import os

    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")

    # ── Global Supabase MCP ──
    # Works everywhere — Railway, mobile, any environment
    # Claude uses MCP tools to query the database directly
    if supabase_key:
        try:
            message = claude_client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": f"""You are a helpful personal shopping assistant with direct access to the user's receipt database via Supabase MCP.

DATABASE TABLE: receipts
COLUMNS: id, store, address, date, time, payment_method, total, subtotal, discount, tax, total_savings, items (JSONB array), created_at

ITEMS JSONB ARRAY contains objects with: code, name, quantity, unit, unit_price, price

INSTRUCTIONS:
- Use the Supabase MCP tools to query the receipts table directly
- Query smartly — only fetch what you need to answer the question
- For price comparisons always use unit_price not total price
- For weighted items (lb, oz, kg, g) always show the unit
- Answer with exact numbers from the database — never make up data
- Use markdown tables for comparisons and ranked lists
- Use **bold** for store names and key numbers
- If data is not available, say so clearly

USER QUESTION: {question}

Use MCP tools to query the database and answer precisely:"""
                    }
                ],
                mcp_servers=[
                    {
                        "type": "url",
                        "url": "https://mcp.supabase.com/mcp?project_ref=okzsqmoxdzrbhhdrsazy",
                        "name": "supabase",
                        "authorization_token": supabase_key,
                    }
                ],
            )

            # Extract answer from response blocks
            # MCP responses may include tool_use blocks — we want the text
            answer = ""
            for block in message.content:
                if hasattr(block, "text") and block.text:
                    answer += block.text

            if answer.strip():
                print("[ask] ✓ Answered via Supabase MCP globally")
                return answer.strip()

        except Exception as e:
            print(f"[ask] MCP failed, using fallback: {e}")

    # ── Fallback: pass receipts as text ──
    # Used when SUPABASE_SERVICE_KEY is not set or MCP fails
    print("[ask] Answering via text fallback")
    receipts_text = json.dumps(receipts, indent=2)

    message = claude_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""You are a helpful personal shopping assistant.
You have access to the user's complete purchase history below.

YOUR JOB:
- Answer the user's question clearly and specifically
- Use exact prices, store names, dates, and item names from the data
- For weighted items (lb, kg, oz) compare by unit_price not total price
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


# ─────────────────────────────────────────
# CLAUDE DESIGN — Dashboard, Scan & Price Insights
# ─────────────────────────────────────────

def generate_dashboard_insights(receipts, total_spent, total_saved, store_counts, store_totals, top_store, avg_per_trip):
    """
    Generate AI spending insights for the dashboard.
    Uses Claude Sonnet for balanced speed and quality.
    Returns structured JSON with summary + insights + tip.
    """
    store_breakdown = ", ".join(f"{s}({c}x, ${store_totals[s]:.2f})" for s,c in sorted(store_counts.items(), key=lambda x:-x[1])[:5])
    recent_items = []
    for r in receipts[:5]:
        for item in (r.get("items") or [])[:3]:
            recent_items.append(item.get("name",""))
    recent_items_str = ", ".join(filter(None, recent_items))

    prompt = f"""Analyze this user's grocery receipt history and generate insights.

DATA:
- Total receipts: {len(receipts)}
- Total spent: ${total_spent:.2f}
- Total saved: ${total_saved:.2f}
- Average per trip: ${avg_per_trip:.2f}
- Top store: {top_store} (${store_totals.get(top_store,0):.2f} total)
- All stores: {store_breakdown}
- Recent items bought: {recent_items_str}

Return ONLY raw JSON — no markdown, no backticks:
{{
    "summary": "One personalized sentence about their spending habits based on actual data",
    "insights": [
        {{"emoji": "🏪", "label": "Top Store", "value": "{top_store}", "sub": "{store_counts.get(top_store,0)} visits"}},
        {{"emoji": "💰", "label": "Avg per Trip", "value": "${avg_per_trip:.2f}", "sub": "per receipt"}},
        {{"emoji": "🎉", "label": "Total Saved", "value": "${total_saved:.2f}", "sub": "in discounts"}}
    ],
    "tip": "One specific money-saving tip based on their actual shopping patterns"
}}"""

    message = claude_client.messages.create(
        model=MODEL_SONNET,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    if "```json" in raw: raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:   raw = raw.split("```")[1].split("```")[0].strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s != -1 and e != -1:
        try:
            return json.loads(raw[s:e+1])
        except:
            pass

    return {
        "summary": f"You have scanned {len(receipts)} receipts and spent ${total_spent:.2f} total, saving ${total_saved:.2f} in discounts.",
        "insights": [
            {"emoji": "🏪", "label": "Top Store", "value": top_store, "sub": f"{store_counts.get(top_store,0)} visits"},
            {"emoji": "💰", "label": "Avg per Trip", "value": f"${avg_per_trip:.2f}", "sub": "per receipt"},
            {"emoji": "🎉", "label": "Total Saved", "value": f"${total_saved:.2f}", "sub": "in discounts"}
        ],
        "tip": ""
    }


def generate_scan_insight(receipt: dict) -> str:
    """
    Generate AI analysis of a single scanned receipt.
    Uses claude-haiku-4-5 for speed — shown immediately after scan.
    """
    items_list = ", ".join(f"{i.get('name','')}: ${i.get('price',0):.2f}" for i in (receipt.get("items") or [])[:10])
    total       = receipt.get("total", 0)
    saved       = receipt.get("total_savings", 0)
    store       = receipt.get("store", "Unknown Store")
    date        = receipt.get("date", "")

    message = claude_client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"""Analyze this grocery receipt in 2-3 sentences. Be specific and helpful.

Receipt: {store} on {date}
Items: {items_list}
Total: ${total:.2f} | Saved: ${saved:.2f}

Give specific insights: best value items, expensive items, or one money-saving tip.
Be direct and conversational. No bullet points."""
        }]
    )
    return message.content[0].text.strip()


def generate_price_insight(item_name: str, stats: dict, points: list) -> str:
    """
    Generate AI insight about price trends for a tracked item.
    Uses claude-haiku-4-5 for speed.
    """
    if not stats:
        return ""

    store_breakdown = {}
    for p in points:
        s = p.get("store","Unknown")
        store_breakdown[s] = store_breakdown.get(s, [])
        store_breakdown[s].append(p.get("unit_price", 0))

    store_avgs = {s: sum(prices)/len(prices) for s,prices in store_breakdown.items()}
    cheapest   = min(store_avgs, key=store_avgs.get) if store_avgs else "N/A"
    stores_str = ", ".join(f"{s}: avg ${avg:.2f}" for s,avg in sorted(store_avgs.items(), key=lambda x:x[1]))

    message = claude_client.messages.create(
        model=MODEL_HAIKU,
        max_tokens=120,
        messages=[{
            "role": "user",
            "content": f"""Give a 1-2 sentence insight about "{item_name}" prices.

Stats: Lowest ${stats.get('lowest','?')}, Highest ${stats.get('highest','?')}, Average ${stats.get('average','?')}, Trend: {stats.get('trend','stable')}
Stores: {stores_str}
Cheapest store: {cheapest}

Be specific. Example: "Chicken breast is cheapest at Walmart at $1.97/lb — prices have been stable." No fluff."""
        }]
    )
    return message.content[0].text.strip()
