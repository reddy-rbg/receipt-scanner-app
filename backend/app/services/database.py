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
import re
from typing import Any

from app.config import supabase


PRODUCT_SIZE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*-?\s*(GAL|GALLON|GALLONS|OZ|FL\s*OZ|LB|LBS|QT|QTS|PT|PTS|CT|EA|ML|L|LTR|LITER|LITERS)\b",
    re.IGNORECASE,
)
EXPLICIT_QTY_RE = re.compile(r"\b(QTY\s*\d+|\d+\s*@|\d+\s+EA\b|\d+\s+FOR\b|\d+\s+AT\b)", re.IGNORECASE)


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


def find_product_size(name: str | None) -> str | None:
    if not name:
        return None
    match = PRODUCT_SIZE_RE.search(str(name))
    if not match:
        return None
    unit = re.sub(r"\s+", "", match.group(2).upper())
    return f"{match.group(1)}-{unit}"


def save_receipt_items(
    receipt: dict,
    items: list | None,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    is_guest: bool = False,
    expires_at: str | None = None,
) -> None:
    """Write normalized item rows for fast agent queries. Safe no-op until receipt_items table exists."""
    if not receipt or not receipt.get("id") or not items:
        return

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
        return

    try:
        supabase.table("receipt_items").delete().eq("receipt_id", receipt_id).execute()
        supabase.table("receipt_items").insert(rows).execute()
    except Exception as e:
        print(f"[receipt_items] Skipped normalized item save: {e}")


def save_receipt(store: str, date: str, total: float, items: list,
                 subtotal: float = 0.00, discount: float = 0.00,
                 tax: float = 0.00, address: str = None,
                 total_savings: float = 0.00, time: str = None,
                 payment_method: str = None,
                 image_hash: str = None,
                 user_id: str = None) -> dict:
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
    response = supabase.table("receipts").insert({
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
    }).execute()

    # response.data is a list of inserted rows
    # We return the first (and only) inserted row
    # If nothing was inserted return empty dict
    saved = response.data[0] if response.data else {}
    save_receipt_items(saved, items, user_id=user_id, is_guest=False)
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


def get_receipts_by_store(store_name: str) -> list:
    """
    Search receipts by store name.
    Uses ilike (case insensitive LIKE) so:
    - "walmart" matches "WALMART SUPERCENTER"
    - "lowes" matches "LOWE'S HOME CENTERS, LLC"
    - "dine" matches "DINEFINE RESTAURANT"
    The % signs mean anything before or after the search term
    """

    response = supabase.table("receipts")\
        .select("*")\
        .ilike("store", f"%{store_name}%")\
        .order("created_at", desc=True)\
        .execute()

    return response.data


def get_receipts_by_date(from_date: str, to_date: str) -> list:
    """
    Get receipts between two dates.

    gte = greater than or equal (from_date)
    lte = less than or equal (to_date)

    Example: from_date="2026-01-01", to_date="2026-05-01"
    Returns all receipts scanned in that range
    """

    response = supabase.table("receipts")\
        .select("*")\
        .gte("created_at", from_date)\
        .lte("created_at", to_date)\
        .order("created_at", desc=True)\
        .execute()

    return response.data


def delete_receipt(receipt_id: int) -> dict:
    """
    Permanently delete a single receipt by its ID.
    .eq("id", receipt_id) means where id = receipt_id
    Returns the deleted record so we can confirm what was removed
    """

    try:
        supabase.table("receipt_items")\
            .delete()\
            .eq("receipt_id", receipt_id)\
            .execute()
    except Exception as e:
        print(f"[receipt_items] Could not delete item rows for receipt {receipt_id}: {e}")

    response = supabase.table("receipts")\
        .delete()\
        .eq("id", receipt_id)\
        .execute()

    # Return deleted record or empty dict if nothing found
    return response.data[0] if response.data else {}


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
