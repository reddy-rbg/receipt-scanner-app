# ─────────────────────────────────────────
# routes/receipts.py
# All receipt API endpoints live here
# Each function handles one URL in your API
#
# Endpoints:
# POST   /scan-receipt      — upload and scan a receipt (image or PDF)
# GET    /receipts          — get all saved receipts
# GET    /receipts/store/   — filter receipts by store name
# GET    /receipts/date     — filter receipts by date range
# DELETE /receipts/{id}     — delete a receipt by ID
# ─────────────────────────────────────────

# APIRouter groups related endpoints together
# like a mini FastAPI app for receipts only
from fastapi import APIRouter, File, UploadFile, HTTPException

# Import our service files
# claude.py   — all Claude AI logic (scanning, answering)
# database.py — all Supabase database logic
from app.services import claude, database

# Import supported file types from config
# MEDIA_TYPES     — image extensions and their mime types
# SUPPORTED_EXTENSIONS — all supported types including PDF
from app.config import MEDIA_TYPES, SUPPORTED_EXTENSIONS

# Create the router
# This gets connected to the main FastAPI app in main.py
router = APIRouter()


# ── ENDPOINT 1: Scan a receipt ──
# URL: POST http://127.0.0.1:8000/scan-receipt
# Accepts: image files (jpg, png, webp, gif) OR PDF files
# Returns: extracted receipt data or duplicate warning
@router.post("/scan-receipt")
async def scan_receipt(file: UploadFile = File(...)):
    """
    Upload a receipt image or PDF — Claude scans it and saves to database.

    Supported formats:
    - Images: jpg, jpeg, png, gif, webp
    - Documents: pdf (automatically converted to image)

    Flow:
    1. Check file type is supported
    2. Read file bytes
    3. Send to Claude for scanning
       - PDFs are automatically converted to images first
       - Claude generates image hash for duplicate detection
       - If duplicate: return existing receipt with warning
       - If new: Claude extracts all receipt data
    4. Save new receipt to Supabase database
    5. Return success response with extracted data

    Error codes:
    - 400: unsupported file type
    - 422: receipt unreadable (blurry, wrong file, not a receipt)
    - 500: unexpected server error
    """

    # ── Check file type ──
    # Split filename by "." and take the last part (extension)
    # e.g. "receipt.pdf" → ["receipt", "pdf"] → "pdf"
    extension = file.filename.split(".")[-1].lower()

    # Check against ALL supported extensions (images + PDF)
    # SUPPORTED_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp", "pdf"]
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: .{extension}. "
                f"Please use jpg, png, webp, gif, or pdf."
            )
        )

    # ── Read file bytes ──
    # await = wait for file to finish reading before continuing
    # file_bytes = raw binary data of the uploaded file
    file_bytes = await file.read()

    # ── Send to Claude for scanning ──
    try:
        # scan_receipt_image handles:
        # - PDF detection and conversion to image
        # - Duplicate detection via image hash
        # - Sending image to Claude API
        # - Parsing Claude's JSON response
        # - Returning structured receipt data
        receipt_data = claude.scan_receipt_image(file_bytes, file.filename)

    except ValueError as e:
        # ValueError is raised when:
        # - Receipt is too blurry to read
        # - File is not a receipt
        # - PDF cannot be converted
        # - Claude is not confident in the extracted data
        # Return 422 with Claude's specific message to show user
        raise HTTPException(
            status_code=422,
            detail=str(e)
        )

    except Exception as e:
        # Catch any unexpected errors
        # Return full error detail so we can debug
        raise HTTPException(
            status_code=500,
            detail=f"Error scanning receipt: {str(e)}"
        )

    # ── Handle duplicate receipt ──
    # If the exact same file was uploaded before
    # receipt_data will have duplicate=True flag set
    # Return existing data with a friendly warning instead of saving again
    if receipt_data.get("duplicate"):
        return {
            "success":  False,
            "duplicate": True,
            # e.g. "This receipt was already scanned!"
            "message":  receipt_data["message"],
            # Return the existing receipt from the database
            "receipt":  receipt_data["existing_receipt"]
        }

    # ── Save new receipt to database ──
    # Wrap in try/except so we see the exact database error if it fails
    try:
        # .get() safely retrieves each field
        # If a field doesn't exist use the default value (0.00 or None)
        saved = database.save_receipt(
            # Store info
            store=receipt_data.get("store"),
            address=receipt_data.get("address"),          # store address if visible

            # Purchase timing
            date=receipt_data.get("date"),                # date printed on receipt
            time=receipt_data.get("time"),                # time of purchase if visible
            payment_method=receipt_data.get("payment_method"),  # AMEX, VISA, CASH etc

            # Items and money
            total=receipt_data.get("total"),              # final total paid
            items=receipt_data.get("items"),              # list of all items bought
            subtotal=receipt_data.get("subtotal", 0.00),  # total before tax
            discount=receipt_data.get("discount", 0.00),  # discount amount applied
            tax=receipt_data.get("tax", 0.00),            # tax charged
            total_savings=receipt_data.get("total_savings", 0.00),  # savings on receipt

            # Duplicate detection
            image_hash=receipt_data.get("image_hash")     # MD5 hash of image
        )

    except Exception as e:
        # Show exact database error for debugging
        raise HTTPException(
            status_code=500,
            detail=f"Database save error: {str(e)}"
        )

    # ── Return success response ──
    return {
        "success":  True,
        "duplicate": False,
        "message":  "Receipt scanned and saved!",
        "filename": file.filename,
        "receipt":  receipt_data,
        "saved_id": saved.get("id")  # the ID assigned by Supabase
    }


# ── ENDPOINT 2: Get all receipts ──
# URL: GET http://127.0.0.1:8000/receipts
# Returns all saved receipts ordered by newest first
@router.get("/receipts")
def get_receipts():
    """
    Return all saved receipts from the database.
    Ordered by newest first so latest receipts appear at top.
    Used by the receipts list in the UI.
    """

    # Fetch all receipts from Supabase
    receipts = database.get_all_receipts()

    return {
        # Total count so UI knows how many receipts to expect
        "total_receipts": len(receipts),
        "receipts": receipts
    }


# ── ENDPOINT 3: Get receipts by store ──
# URL: GET http://127.0.0.1:8000/receipts/store/walmart
# store_name comes from the URL path
# Uses partial case insensitive matching
# so "lowes" matches "LOWE'S HOME CENTERS, LLC"
@router.get("/receipts/store/{store_name}")
def get_by_store(store_name: str):
    """
    Filter receipts by store name.

    Matching is:
    - Case insensitive: "walmart" matches "WALMART"
    - Partial: "lowe" matches "LOWE'S HOME CENTERS, LLC"
    - "dine" matches "DINEFINE RESTAURANT"

    Returns matching receipts ordered by newest first.
    """

    receipts = database.get_receipts_by_store(store_name)

    # If no receipts found for this store return helpful message
    if not receipts:
        return {
            "message": (
                f"No receipts found for store: '{store_name}'. "
                f"Try a shorter search term."
            )
        }

    return {
        "store_search": store_name,
        "total_found":  len(receipts),
        "receipts":     receipts
    }


# ── ENDPOINT 4: Get receipts by date range ──
# URL: GET http://127.0.0.1:8000/receipts/date?from_date=2026-01-01&to_date=2026-05-01
# from_date and to_date come from URL query parameters
# Dates should be in YYYY-MM-DD format
@router.get("/receipts/date")
def get_by_date(from_date: str, to_date: str):
    """
    Filter receipts between two dates.

    Both parameters are required.
    Date format: YYYY-MM-DD (e.g. 2026-01-01)

    Returns receipts in that date range ordered by newest first.
    """

    receipts = database.get_receipts_by_date(from_date, to_date)

    if not receipts:
        return {
            "message": f"No receipts found between {from_date} and {to_date}."
        }

    return {
        "from":        from_date,
        "to":          to_date,
        "total_found": len(receipts),
        "receipts":    receipts
    }


# ── ENDPOINT 5: Delete a receipt ──
# URL: DELETE http://127.0.0.1:8000/receipts/5
# receipt_id comes from the URL path
# This permanently deletes the receipt — cannot be undone
@router.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id: int):
    """
    Permanently delete a receipt by its ID.

    This cannot be undone — the UI shows a confirmation
    dialog before calling this endpoint.

    The receipt ID can be found in the receipts list
    shown as #1, #2 etc in the UI.
    """

    # Attempt to delete — returns deleted record or empty dict
    deleted = database.delete_receipt(receipt_id)

    # If nothing was deleted that ID doesn't exist in database
    if not deleted:
        return {
            "message": (
                f"No receipt found with id: {receipt_id}. "
                f"Already deleted?"
            )
        }

    return {
        "success": True,
        "message": f"Receipt #{receipt_id} deleted successfully."
    }