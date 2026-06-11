# ─────────────────────────────────────────
# routes/queries.py
# Smart query endpoints
# cheapest, summary, ask, price history, realtime price
#
# Endpoints:
# GET  /cheapest                  — find cheapest store for any item
# GET  /summary                   — full spending and savings summary
# POST /ask                       — natural language question answering
# GET  /price-history/{item_name} — price trend data for charting
# GET  /realtime-price/{item_name}— current market prices via web search
# ─────────────────────────────────────────

from fastapi import APIRouter
from app.services import claude, database

router = APIRouter()


def calculate_savings_for_receipt(receipt: dict) -> float:
    """
    Calculate total savings for a single receipt.

    Priority order:
    1. Use total_savings if printed on receipt (most accurate)
    2. Use discount field if available
    3. Add up all negative price items as fallback

    Handles all store formats:
    - Lowe's: prints "TOTAL SAVINGS THIS TRIP"
    - Walmart: shows "DISCOUNT GIVEN" in subtotal
    - Others: individual discount line items
    """

    # Priority 1 — total_savings printed on receipt
    if receipt.get("total_savings") and receipt["total_savings"] > 0:
        return receipt["total_savings"]

    # Priority 2 — discount field from subtotal section
    if receipt.get("discount") and receipt["discount"] > 0:
        return receipt["discount"]

    # Priority 3 — add up all negative price items
    items = receipt.get("items") or []
    item_discounts = sum(
        abs(item["price"])
        for item in items
        if item.get("price") and item["price"] < 0
    )

    return item_discounts


@router.get("/cheapest")
def get_cheapest(item: str):
    """
    Find the cheapest store for any item across all receipts.

    For weighted items (lb, kg) compares by unit_price
    so we compare apples to apples regardless of quantity.

    For regular items compares by unit_price or price.

    Example: /cheapest?item=tomato
    Returns cheapest store + all stores ranked by price
    """

    # Get all receipts from database
    receipts = database.get_all_receipts()

    # Search through every item in every receipt
    matches = []
    for receipt in receipts:
        for receipt_item in receipt.get("items", []):

            # Skip discount lines — they are not real items
            if receipt_item.get("price", 0) < 0:
                continue

            # Case insensitive partial match
            if item.lower() in receipt_item["name"].lower():

                # For weighted items use unit_price for comparison
                unit = receipt_item.get("unit", "each")
                unit_price = receipt_item.get("unit_price") or receipt_item.get("price")
                compare_price = unit_price if unit_price else receipt_item["price"]

                matches.append({
                    "store":         receipt["store"],
                    "address":       receipt.get("address"),
                    "date":          receipt["date"],
                    "code":          receipt_item.get("code"),
                    "item":          receipt_item["name"],
                    "quantity":      receipt_item.get("quantity", 1),
                    "unit":          unit,
                    "unit_price":    unit_price,
                    "price":         receipt_item["price"],
                    "compare_price": compare_price
                })

    if not matches:
        return {"message": f"No results found for '{item}'"}

    # Sort by compare_price — cheapest first
    matches.sort(key=lambda x: x["compare_price"])

    return {
        "search":      item,
        "cheapest":    matches[0],
        "total_found": len(matches),
        "all_results": matches
    }


@router.get("/summary")
def get_summary():
    """
    Full spending summary across all receipts.

    Calculates:
    - Total receipts scanned
    - Total money spent
    - Total money saved (using best available savings data)
    - Average spend per receipt
    - Breakdown by store with individual store totals
    """

    # Get all receipts
    receipts = database.get_all_receipts()

    if not receipts:
        return {"message": "No receipts found. Scan your first receipt!"}

    # Total money spent across all receipts
    total_spent = sum((r["total"] or 0) for r in receipts)

    # Total saved — use smart calculation for each receipt
    total_saved = sum(
        calculate_savings_for_receipt(r)
        for r in receipts
    )

    # Build per-store breakdown
    store_spending = {}
    for receipt in receipts:
        store = receipt["store"]

        # Create new entry for store if first time seeing it
        if store not in store_spending:
            store_spending[store] = {
                "store":         store,
                "address":       receipt.get("address"),
                "total_spent":   0,
                "total_saved":   0,
                "receipt_count": 0
            }

        # Add this receipt to store totals
        store_spending[store]["total_spent"]   += receipt["total"] or 0
        store_spending[store]["total_saved"]   += calculate_savings_for_receipt(receipt)
        store_spending[store]["receipt_count"] += 1

    # Sort stores by total spent — highest first
    stores_list = sorted(
        store_spending.values(),
        key=lambda x: x["total_spent"],
        reverse=True
    )

    # Round all values to 2 decimal places
    for store in stores_list:
        store["total_spent"] = round(store["total_spent"], 2)
        store["total_saved"] = round(store["total_saved"], 2)

    return {
        "total_receipts":      len(receipts),
        "total_spent":         round(total_spent, 2),
        "total_saved":         round(total_saved, 2),
        "average_per_receipt": round(total_spent / len(receipts), 2),
        "spending_by_store":   stores_list
    }


@router.post("/ask")
async def ask_question(question: dict):
    """
    Answer any natural language question about receipts.

    How it works:
    1. Get the question from request body
    2. Fetch all receipts from database
    3. Send receipts + question to Claude
    4. Claude reads data and answers in plain English

    Example questions:
    - "Where did I buy tomatoes cheapest?"
    - "How much have I spent at Walmart?"
    - "Show me all receipts in a table"
    - "How much did I save this month?"
    """

    # Get question from request body
    user_question = question.get("question", "")

    if not user_question:
        return {"error": "Please provide a question"}

    # Get all receipts to give Claude context
    receipts = database.get_all_receipts()

    if not receipts:
        return {"answer": "No receipts found yet. Scan some receipts first!"}

    # Send question + receipts to Claude for answering
    answer = claude.answer_question(user_question, receipts)

    return {
        "question": user_question,
        "answer":   answer
    }


@router.get("/price-history/{item_name}")
def get_price_history(item_name: str):
    """
    Get full price history for a specific item across all receipts.
    Used to draw price trend charts in the UI.

    Returns all purchases of the item sorted by date oldest first
    so the chart shows left to right = oldest to newest.

    Also returns stats:
    - lowest price ever paid
    - highest price ever paid
    - average price paid
    - most recent price
    - trend (up/down/stable)
    """

    # Get all receipts from database
    receipts = database.get_all_receipts()
    matches = []

    for receipt in receipts:
        for item in receipt.get("items", []):

            # Skip discount lines — not real purchases
            if item.get("price", 0) < 0:
                continue

            # Case insensitive partial match
            # "tomato" matches "TOMATO 4X5"
            if item_name.lower() in item["name"].lower():
                matches.append({
                    # Use receipt date for chart x-axis
                    # Fall back to created_at date if receipt date not available
                    "date":       receipt.get("date") or receipt.get("created_at", "")[:10],
                    "store":      receipt["store"],
                    "item":       item["name"],
                    "price":      item["price"],
                    "unit":       item.get("unit", "each"),
                    # unit_price is what we chart — more meaningful than total for weighted items
                    "unit_price": item.get("unit_price") or item["price"],
                    "quantity":   item.get("quantity", 1),
                    "receipt_id": receipt["id"]
                })

    # Sort oldest to newest for chart display
    # Left side of chart = oldest purchase
    # Right side of chart = most recent purchase
    matches.sort(key=lambda x: x["date"])

    if not matches:
        return {"message": f"No price history found for '{item_name}'"}

    # Calculate price statistics
    prices = [m["unit_price"] for m in matches]

    # Determine trend by comparing first and last price
    if prices[-1] > prices[0]:
        trend = "up"      # price increased over time
    elif prices[-1] < prices[0]:
        trend = "down"    # price decreased over time
    else:
        trend = "stable"  # price stayed the same

    return {
        "item":        item_name,
        "data_points": matches,
        "stats": {
            "lowest":  round(min(prices), 2),   # cheapest you ever paid
            "highest": round(max(prices), 2),   # most expensive you ever paid
            "average": round(sum(prices) / len(prices), 2),  # average price
            "current": round(prices[-1], 2),    # most recent price
            "trend":   trend                    # up, down, or stable
        }
    }


@router.get("/realtime-price/{item_name}")
async def get_realtime_price(item_name: str):
    """
    Get current real-time market price for an item using Claude web search.

    Claude searches the web for current retail prices at major US stores
    like Walmart, Kroger, Target etc and returns structured price data.

    This lets users compare what they paid vs current market prices.
    """

    # Call Claude with web search to find current prices
    result = claude.get_realtime_price(item_name)
    return result
    
@router.post("/optimize-shopping-list")
async def optimize_shopping_list(body: dict):
    """
    Takes a shopping list and recommends which store to buy each item from
    based on the user's actual receipt history.

    Input: {"items": ["milk", "eggs", "bread", "tomatoes"]}

    Output: For each item, which store had the cheapest price and when,
    plus total estimated savings vs buying everything at one store.
    """

    items = body.get("items", [])

    if not items:
        return {"error": "Please provide a list of items"}

    # Get all receipts for price history context
    receipts = database.get_all_receipts()

    if not receipts:
        return {"error": "No receipt history found. Scan some receipts first!"}

    # Build price history for each requested item
    # This gives Claude real data to work with
    item_prices = {}

    for item_name in items:
        matches = []
        for receipt in receipts:
            for item in receipt.get("items", []):
                # Skip discounts
                if item.get("price", 0) < 0:
                    continue
                # Case insensitive match
                if item_name.lower() in item["name"].lower():
                    unit = item.get("unit", "each")
                    unit_price = item.get("unit_price") or item.get("price")
                    matches.append({
                        "store":      receipt["store"],
                        "date":       receipt.get("date", ""),
                        "item":       item["name"],
                        "price":      item["price"],
                        "unit":       unit,
                        "unit_price": unit_price,
                    })

        # Sort by cheapest unit price
        matches.sort(key=lambda x: x["unit_price"] or x["price"])
        item_prices[item_name] = matches

    # Ask Claude to optimize the shopping list
    result = claude.optimize_shopping_list(items, item_prices)
    return result