# ─────────────────────────────────────────
# services/database.py
# All Supabase database logic lives here
# Think of this file as your "database assistant"
# Every function talks to Supabase and returns data
#
# Functions:
# save_receipt()         — save a new scanned receipt
# get_all_receipts()     — get all receipts newest first
# get_receipts_by_store()— filter by store name
# get_receipts_by_date() — filter by date range
# delete_receipt()       — delete by ID
# get_price_history()    — find all purchases of an item
# get_spending_summary() — full spending breakdown
# ─────────────────────────────────────────

# Import the supabase client we set up in config.py
# We reuse the same connection — don't create a new one here
import hashlib
import math
import os
import re
from datetime import datetime
from typing import Any

from app.config import supabase


PRODUCT_SIZE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*-?\s*(GAL|GALLON|GALLONS|OZ|FL\s*OZ|LB|LBS|QT|QTS|PT|PTS|CT|EA|ML|L|LTR|LITER|LITERS)\b",
    re.IGNORECASE,
)
EXPLICIT_QTY_RE = re.compile(r"\b(QTY\s*\d+|\d+\s*@|\d+\s+EA\b|\d+\s+FOR\b|\d+\s+AT\b)", re.IGNORECASE)
LOCAL_EMBEDDING_MODEL = os.getenv("RECEIPT_ITEM_EMBEDDING_MODEL", "receiptai-contextual-local-hash-v2")
EMBEDDING_DIMENSIONS = 1536
RECEIPT_ITEM_EMBEDDINGS_ENABLED = os.getenv("RECEIPT_ITEM_EMBEDDINGS_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
OPTIONAL_RECEIPT_IDENTIFIER_FIELDS = {
    "transaction_number", "receipt_number", "invoice_number", "order_number",
}


def insert_receipt_with_optional_identifiers(payload: dict):
    """Support rolling deploys before the identifier migration is applied."""
    try:
        return supabase.table("receipts").insert(payload).execute()
    except Exception as first_error:
        if not any(field in payload for field in OPTIONAL_RECEIPT_IDENTIFIER_FIELDS):
            raise
        legacy_payload = {key: value for key, value in payload.items() if key not in OPTIONAL_RECEIPT_IDENTIFIER_FIELDS}
        print(f"[receipts] Identifier columns unavailable; using legacy schema: {first_error}")
        return supabase.table("receipts").insert(legacy_payload).execute()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        return float(value)
    except Exception:
        return default


def normalize_item_name(name: str | None) -> str:
    if not name:
        return ""
    text = str(name).lower()
    text = text.replace("lowe's", "lowes").replace("pren", "prem").replace("prern", "prem").replace("prcm", "prem")
    text = re.sub(r"[^a-z0-9\.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_purchase_date(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%b %d"):
        try:
            parsed = datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt)
            if fmt == "%b %d":
                parsed = parsed.replace(year=datetime.now().year)
            return parsed
        except ValueError:
            continue
    return None


def find_product_size(name: str | None) -> str | None:
    if not name:
        return None
    match = PRODUCT_SIZE_RE.search(str(name))
    if not match:
        return None
    unit = re.sub(r"\s+", "", match.group(2).upper())
    return f"{match.group(1)}-{unit}"


def local_text_embedding(text: str) -> list[float]:
    """Create a deterministic local vector so receipt search stays Claude-only."""
    if not RECEIPT_ITEM_EMBEDDINGS_ENABLED or not text:
        return []

    normalized = normalize_item_name(text)
    tokens = normalized.split()
    features = tokens[:]
    compact = "".join(tokens)
    if compact:
        features.extend(compact[i:i + 3] for i in range(max(0, len(compact) - 2)))
    if not features:
        return []

    vector = [0.0] * EMBEDDING_DIMENSIONS
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[bucket] += sign

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return []
    return [value / magnitude for value in vector]


def _embedding_vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def _receipt_item_embedding_text(row: dict) -> str:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    category = metadata.get("category") or metadata.get("department") or metadata.get("type")
    price = row.get("unit_price") or row.get("line_price")
    line_total = row.get("line_price")
    quantity = row.get("quantity")
    unit = row.get("unit")
    explicit_quantity = "explicit quantity" if row.get("explicit_quantity") else "single receipt line"
    parts = [
        f"Item: {row.get('item_name_original')}",
        f"Normalized item: {row.get('item_name_normalized')}",
        f"Receipt code: {row.get('code')}",
        f"Package size: {row.get('product_size')}",
        f"Store: {row.get('store')}",
        f"Purchase date: {row.get('purchase_date')}",
        f"Quantity: {quantity} {unit}".strip() if quantity else None,
        f"Unit price: ${price}" if price else None,
        f"Line total: ${line_total}" if line_total else None,
        f"Category: {category}" if category else None,
        f"Quantity rule: {explicit_quantity}",
        "Context: receipt item row for grocery price memory, cheapest-store lookup, repeated-purchase history, and typo-tolerant item search.",
    ]
    return " | ".join(str(part) for part in parts if part and str(part).strip() and not str(part).endswith("None"))


def save_receipt_item_embeddings(rows: list[dict], receipt_id: int | str) -> None:
    """Populate pgvector rows for Claude-only receipt item retrieval."""
    if not RECEIPT_ITEM_EMBEDDINGS_ENABLED or not rows:
        return

    embedding_rows = []
    for row in rows:
        if not row.get("user_id") and not row.get("guest_session_id"):
            continue
        item_text = _receipt_item_embedding_text(row)
        embedding = local_text_embedding(item_text)
        if not embedding:
            continue
        embedding_rows.append({
            "user_id": row.get("user_id"),
            "guest_session_id": row.get("guest_session_id"),
            "receipt_id": row.get("receipt_id"),
            "line_index": row.get("line_index"),
            "item_name": row.get("item_name_original"),
            "item_text": item_text,
            "embedding": _embedding_vector_literal(embedding),
            "model": LOCAL_EMBEDDING_MODEL,
        })

    if not embedding_rows:
        return

    try:
        supabase.table("receipt_item_embeddings").delete().eq("receipt_id", receipt_id).execute()
        supabase.table("receipt_item_embeddings").insert(embedding_rows).execute()
    except Exception as e:
        print(f"[receipt_item_embeddings] Skipped vector save: {e}")


def save_receipt_items(
    receipt: dict,
    items: list | None,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    is_guest: bool = False,
    expires_at: str | None = None,
) -> dict:
    """Write normalized item rows for fast agent queries. Safe no-op until receipt_items table exists."""
    if not receipt or not receipt.get("id") or not items:
        return {"success": True, "receipt_id": receipt.get("id") if receipt else None, "items": 0}

    rows = []
    receipt_id = receipt.get("id")
    store = receipt.get("store")
    date = receipt.get("date")
    created_at = receipt.get("created_at")

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or item.get("item") or "").strip()
        if not name:
            continue

        product_size = item.get("product_size") or find_product_size(name)
        explicit_quantity = bool(item.get("explicit_quantity")) or bool(EXPLICIT_QTY_RE.search(name))
        raw_quantity = _safe_float(item.get("quantity"), 1.0) or 1.0
        quantity = 1.0 if product_size and not explicit_quantity else raw_quantity
        line_price = _safe_float(item.get("price"), 0.0)
        unit_price = _safe_float(item.get("unit_price"), line_price)
        if product_size and not explicit_quantity:
            unit_price = line_price or unit_price

        rows.append({
            "receipt_id": receipt_id,
            "line_index": index,
            "user_id": user_id,
            "is_guest": is_guest,
            "guest_session_id": guest_session_id,
            "expires_at": expires_at,
            "store": store,
            "purchase_date": date,
            "receipt_created_at": created_at,
            "code": item.get("code"),
            "item_name_original": name,
            "item_name_normalized": normalize_item_name(item.get("normalized_name") or name),
            "product_size": product_size,
            "quantity": quantity,
            "raw_quantity": raw_quantity,
            "unit": item.get("unit") or "each",
            "unit_price": round(unit_price, 2) if unit_price else None,
            "line_price": round(line_price, 2) if line_price else None,
            "source": item.get("source") or "printed",
            "confidence": item.get("confidence"),
            "explicit_quantity": explicit_quantity,
            "metadata": item,
        })

    if not rows:
        return {"success": True, "receipt_id": receipt_id, "items": 0}

    try:
        supabase.table("receipt_items").delete().eq("receipt_id", receipt_id).execute()
        supabase.table("receipt_items").insert(rows).execute()
        save_receipt_item_embeddings(rows, receipt_id)
        return {"success": True, "receipt_id": receipt_id, "items": len(rows)}
    except Exception as e:
        print(f"[receipt_items] Skipped normalized item save: {e}")
        return {"success": False, "receipt_id": receipt_id, "items": 0, "error": str(e)}


def backfill_receipt_vectors(
    user_id: str | None = None,
    guest_session_id: str | None = None,
    limit: int = 1000,
) -> dict:
    """
    Rebuild normalized receipt_items and local vector rows from existing receipt JSON.
    With no owner filter this should be run only from a trusted service-role environment.
    """
    processed = 0
    skipped = 0
    failed = 0
    items_written = 0
    errors: list[dict] = []

    page_size = 100
    max_rows = max(1, min(int(limit or 1000), 10000))

    for start in range(0, max_rows, page_size):
        end = min(start + page_size - 1, max_rows - 1)
        q = supabase.table("receipts").select(
            "id,store,date,created_at,items,user_id,is_guest,guest_session_id,expires_at"
        )
        if user_id:
            q = q.eq("user_id", user_id)
        elif guest_session_id:
            q = q.eq("is_guest", True).eq("guest_session_id", guest_session_id)
        result = q.order("created_at", desc=True).range(start, end).execute()
        receipts = result.data or []
        if not receipts:
            break

        for receipt in receipts:
            items = receipt.get("items") if isinstance(receipt.get("items"), list) else []
            if not items:
                skipped += 1
                continue
            outcome = save_receipt_items(
                receipt,
                items,
                user_id=receipt.get("user_id"),
                guest_session_id=receipt.get("guest_session_id"),
                is_guest=bool(receipt.get("is_guest")),
                expires_at=receipt.get("expires_at"),
            )
            if outcome.get("success"):
                processed += 1
                items_written += int(outcome.get("items") or 0)
            else:
                failed += 1
                errors.append({
                    "receipt_id": receipt.get("id"),
                    "error": outcome.get("error") or "Unknown error",
                })

        if len(receipts) < page_size:
            break

    return {
        "success": failed == 0,
        "processed_receipts": processed,
        "skipped_receipts": skipped,
        "failed_receipts": failed,
        "items_written": items_written,
        "errors": errors[:20],
    }


def save_receipt(store: str, date: str, total: float, items: list,
                 subtotal: float = 0.00, discount: float = 0.00,
                 tax: float = 0.00, address: str = None,
                 total_savings: float = 0.00, time: str = None,
                 payment_method: str = None,
                 image_hash: str = None,
                 user_id: str = None,
                 transaction_number: str | None = None,
                 receipt_number: str | None = None,
                 invoice_number: str | None = None,
                 order_number: str | None = None) -> dict:
    """
    Save a scanned receipt to the database.

    Parameters:
    - store          : store name (e.g. "LOWE'S HOME CENTERS")
    - address        : store address if visible on receipt
    - date           : date printed on receipt
    - time           : time of purchase if visible
    - payment_method : how they paid (AMEX, VISA, CASH etc)
    - total          : final total amount paid
    - items          : list of items with code, name, qty, price
    - subtotal       : amount before tax
    - discount       : discount amount applied
    - tax            : tax amount charged
    - total_savings  : total savings shown at bottom of receipt
    - image_hash     : MD5 hash of image for duplicate detection

    Returns the saved record including auto-generated ID
    """

    # .table("receipts") — which Supabase table to insert into
    # .insert({...})     — the data to insert as a dictionary
    # .execute()         — actually run the query
    response = insert_receipt_with_optional_identifiers({
        "store":          store,
        "address":        address,
        "date":           date,
        "time":           time,
        "payment_method": payment_method,
        "total":          total,
        "items":          items,
        "subtotal":       subtotal,
        "discount":       discount,
        "tax":            tax,
        "total_savings":  total_savings,
        "image_hash":     image_hash,
        "user_id":        user_id,         # ✅ links receipt to logged-in user
        "transaction_number": transaction_number,
        "receipt_number": receipt_number,
        "invoice_number": invoice_number,
        "order_number": order_number,
    })

    # response.data is a list of inserted rows
    # We return the first (and only) inserted row
    # If nothing was inserted return empty dict
    saved = response.data[0] if response.data else {}
    save_receipt_items(saved, items, user_id=user_id, is_guest=False)
    if saved:
        from app.services import agent
        agent.clear_owner_data_caches(user_id=user_id)
    return saved


def get_all_receipts() -> list:
    """
    Get all receipts from database ordered by newest first.
    Used by the receipts list page and summary endpoint.
    """

    response = supabase.table("receipts")\
        .select("*")\
        .order("created_at", desc=True)\
        .execute()

    # response.data is a list of receipt dictionaries
    return response.data


def get_receipts_by_store(
    store_name: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> list:
    """
    Search receipts by store name.
    Uses ilike (case insensitive LIKE) so:
    - "walmart" matches "WALMART SUPERCENTER"
    - "lowes" matches "LOWE'S HOME CENTERS, LLC"
    - "dine" matches "DINEFINE RESTAURANT"
    The % signs mean anything before or after the search term
    """

    query = supabase.table("receipts").select("*")
    if user_id:
        query = query.eq("user_id", user_id)
    elif guest_session_id:
        query = query.eq("is_guest", True).eq("guest_session_id", guest_session_id)
    else:
        return []
    response = query.ilike("store", f"%{store_name}%")\
        .order("created_at", desc=True).execute()

    return response.data


def get_receipts_by_date(
    from_date: str,
    to_date: str,
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> list:
    """
    Get receipts between two dates.

    gte = greater than or equal (from_date)
    lte = less than or equal (to_date)

    Example: from_date="2026-01-01", to_date="2026-05-01"
    Returns all receipts scanned in that range
    """

    query = supabase.table("receipts").select("*")
    if user_id:
        query = query.eq("user_id", user_id)
    elif guest_session_id:
        query = query.eq("is_guest", True).eq("guest_session_id", guest_session_id)
    else:
        return []
    response = query.order("created_at", desc=True).execute()
    start = parse_purchase_date(from_date)
    end = parse_purchase_date(to_date)
    if not start or not end:
        return []
    return [
        receipt
        for receipt in (response.data or [])
        if (parsed := parse_purchase_date(receipt.get("date") or receipt.get("created_at")))
        and start <= parsed <= end
    ]


def delete_receipt(
    receipt_id: int,
    user_id: str | None = None,
    guest_session_id: str | None = None,
) -> dict:
    """
    Permanently delete a single receipt by its ID.
    .eq("id", receipt_id) means where id = receipt_id
    Returns the deleted record so we can confirm what was removed
    """

    if not user_id and not guest_session_id:
        return {}

    owner_query = supabase.table("receipts").select("id,user_id,is_guest,guest_session_id").eq("id", receipt_id)
    if user_id:
        owner_query = owner_query.eq("user_id", user_id)
    else:
        owner_query = owner_query.eq("is_guest", True).eq("guest_session_id", guest_session_id)
    owned = owner_query.limit(1).execute().data or []
    if not owned:
        return {}

    try:
        supabase.table("receipt_items")\
            .delete()\
            .eq("receipt_id", receipt_id)\
            .execute()
    except Exception as e:
        print(f"[receipt_items] Could not delete item rows for receipt {receipt_id}: {e}")

    delete_query = supabase.table("receipts").delete().eq("id", receipt_id)
    if user_id:
        delete_query = delete_query.eq("user_id", user_id)
    else:
        delete_query = delete_query.eq("is_guest", True).eq("guest_session_id", guest_session_id)
    response = delete_query.execute()

    # Return deleted record or empty dict if nothing found
    deleted = response.data[0] if response.data else {}
    if deleted:
        from app.services import agent
        agent.clear_owner_data_caches(
            user_id=deleted.get("user_id"),
            guest_session_id=deleted.get("guest_session_id"),
        )
    return deleted


def get_price_history(item_name: str) -> list:
    """
    Find all purchases of a specific item across all receipts.
    Used to compare prices over time and across stores.

    Example: get_price_history("milk")
    Returns every time milk was bought, from which store,
    at what price, and on what date.
    """

    normalized_query = normalize_item_name(item_name)
    try:
        response = supabase.table("receipt_items")\
            .select("receipt_id,store,purchase_date,code,item_name_original,line_price,quantity,unit_price,unit,item_name_normalized")\
            .ilike("item_name_normalized", f"%{normalized_query}%")\
            .order("receipt_created_at", desc=True)\
            .execute()
        rows = response.data or []
        if rows:
            return [{
                "store":      row.get("store"),
                "address":    None,
                "date":       row.get("purchase_date"),
                "time":       None,
                "code":       row.get("code"),
                "item":       row.get("item_name_original"),
                "price":      row.get("line_price"),
                "quantity":   row.get("quantity", 1),
                "unit_price": row.get("unit_price") or row.get("line_price"),
                "unit":       row.get("unit") or "each",
                "receipt_id": row.get("receipt_id"),
            } for row in rows]
    except Exception as e:
        print(f"[receipt_items] Price history fallback: {e}")

    # Get every receipt from the database
    response = supabase.table("receipts").select("*").execute()
    receipts = response.data

    # Go through every receipt and every item in each receipt
    matches = []
    for receipt in receipts:
        for item in receipt.get("items", []):
            # .lower() makes comparison case insensitive
            # "seed" matches "SCOTTS TB 10-LB EZ SEED T"
            if item_name.lower() in item["name"].lower():
                matches.append({
                    "store":      receipt["store"],
                    "address":    receipt.get("address"),
                    "date":       receipt["date"],
                    "time":       receipt.get("time"),
                    "code":       item.get("code"),        # product code
                    "item":       item["name"],
                    "price":      item["price"],
                    "quantity":   item.get("quantity", 1),
                    "unit_price": item.get("unit_price", item["price"]),
                    "receipt_id": receipt["id"]
                })

    # Sort by date newest first
    matches.sort(key=lambda x: x["date"] or "", reverse=True)
    return matches


def get_spending_summary() -> dict:
    """
    Calculate a full spending summary across all receipts.

    Returns:
    - Total number of receipts scanned
    - Total money spent across all stores
    - Total money saved through discounts
    - Average spend per receipt
    - Breakdown of spending by store (sorted highest to lowest)
    """

    # Get all receipts from database
    response = supabase.table("receipts").select("*").execute()
    receipts = response.data

    # If no receipts exist return empty dict
    if not receipts:
        return {}

    # Add up total spending across all receipts
    # sum() adds up all values in the list
    # r["total"] gets the total field from each receipt
    # We use or 0 to handle None values safely
    total_spent = sum((r["total"] or 0) for r in receipts)

    # Add up all savings shown on receipts
    # .get("total_savings", 0) returns 0 if field doesn't exist
    total_savings = sum(r.get("total_savings") or 0 for r in receipts)

    # Build a spending breakdown per store
    # store_spending is a dictionary where key = store name
    store_spending = {}
    for receipt in receipts:
        store = receipt["store"]

        # If we haven't seen this store before create a new entry
        if store not in store_spending:
            store_spending[store] = {
                "store":         store,
                "address":       receipt.get("address"),
                "total_spent":   0,
                "total_saved":   0,
                "receipt_count": 0
            }

        # Add this receipt's values to the store's running totals
        store_spending[store]["total_spent"]   += receipt["total"] or 0
        store_spending[store]["total_saved"]   += receipt.get("total_savings") or 0
        store_spending[store]["receipt_count"] += 1

    # Convert dictionary to a sorted list
    # sorted() arranges by total_spent highest first
    stores_list = sorted(
        store_spending.values(),
        key=lambda x: x["total_spent"],
        reverse=True
    )

    return {
        "total_receipts":      len(receipts),
        "total_spent":         round(total_spent, 2),
        "total_saved":         round(total_savings, 2),
        "average_per_receipt": round(total_spent / len(receipts), 2),
        "spending_by_store":   stores_list
    }
