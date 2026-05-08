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
from app.config import supabase


def save_receipt(store: str, date: str, total: float, items: list,
                 subtotal: float = 0.00, discount: float = 0.00,
                 tax: float = 0.00, address: str = None,
                 total_savings: float = 0.00, time: str = None,
                 payment_method: str = None,
                 image_hash: str = None) -> dict:
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
        "address":        address,         # store address if visible
        "date":           date,            # date on receipt
        "time":           time,            # time of purchase
        "payment_method": payment_method,  # AMEX, VISA, CASH etc
        "total":          total,           # final total paid
        "items":          items,           # stored as JSON in Supabase
        "subtotal":       subtotal,        # before tax
        "discount":       discount,        # discount amount applied
        "tax":            tax,             # tax charged
        "total_savings":  total_savings,   # savings shown at bottom
        "image_hash":     image_hash       # MD5 hash for duplicate detection
    }).execute()

    # response.data is a list of inserted rows
    # We return the first (and only) inserted row
    # If nothing was inserted return empty dict
    return response.data[0] if response.data else {}


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