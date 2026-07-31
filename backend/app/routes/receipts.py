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
import re
import time

from fastapi import APIRouter, File, UploadFile, HTTPException, Request
from pydantic import BaseModel

# Import our service files
# claude.py   — all Claude AI logic (scanning, answering)
# database.py — all Supabase database logic
from app.services import claude, database, rbac, token_usage
from app.services import agent as agent_service
from app.services.app_logger import get_logger

# Import supported file types from config
# MEDIA_TYPES     — image extensions and their mime types
# SUPPORTED_EXTENSIONS — all supported types including PDF
from app.config import MEDIA_TYPES, SUPPORTED_EXTENSIONS

# Create the router
# This gets connected to the main FastAPI app in main.py
router = APIRouter()
logger = get_logger(__name__)
_SCAN_RATE_BUCKETS: dict[str, list[float]] = {}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def enforce_scan_rate_limit(owner: str) -> None:
    now = time.monotonic()
    recent = [stamp for stamp in _SCAN_RATE_BUCKETS.get(owner, []) if now - stamp < 3600]
    if len(recent) >= 20:
        raise HTTPException(status_code=429, detail="Receipt scan limit reached. Please try again later.")
    recent.append(now)
    _SCAN_RATE_BUCKETS[owner] = recent
    if len(_SCAN_RATE_BUCKETS) > 5000:
        _SCAN_RATE_BUCKETS.clear()


def validate_upload_size(data: bytes) -> None:
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Receipt file is too large. Please upload a file under 15 MB.")


def record_scan_token_usage(
    receipt_data: dict,
    *,
    user_id: str | None = None,
    guest_session_id: str | None = None,
    customer_id: str | None = None,
    receipt_id: int | None = None,
    filename: str | None = None,
    file_bytes: int | None = None,
) -> None:
    usage = receipt_data.get("_token_usage") or {}
    extension = (filename or "").split(".")[-1].lower() if filename else None
    token_usage.record_token_usage(
        feature=usage.get("feature") or "receipt_scan",
        operation=usage.get("operation") or "unknown_scan",
        model=usage.get("model") or "unknown",
        user_id=user_id,
        guest_session_id=guest_session_id,
        customer_id=customer_id,
        receipt_id=receipt_id,
        filename=filename,
        file_type=extension,
        file_bytes=file_bytes,
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cached_input_tokens=usage.get("cached_input_tokens", 0),
        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        optimized=bool(usage.get("optimized")),
        optimization=usage.get("optimization"),
        metadata=usage.get("metadata") or {},
    )


def public_receipt_data(receipt_data: dict) -> dict:
    return {key: value for key, value in receipt_data.items() if not str(key).startswith("_")}


class ReceiptItemUpdate(BaseModel):
    name: str | None = None
    price: float | None = None
    quantity: float | None = None
    unit_price: float | None = None
    unit: str | None = None
    product_size: str | None = None
    code: str | None = None
    category: str | None = None
    session_id: str | None = None


class ReceiptMetadataUpdate(BaseModel):
    store: str | None = None
    address: str | None = None
    date: str | None = None
    time: str | None = None
    payment_method: str | None = None
    transaction_number: str | None = None
    receipt_number: str | None = None
    invoice_number: str | None = None
    order_number: str | None = None


class LivePriceCheckRequest(BaseModel):
    item_name: str
    current_price: float | None = None
    store: str | None = None
    source_url: str | None = None
    session_id: str | None = None
    live_search: bool = False


class BackfillVectorsRequest(BaseModel):
    session_id: str | None = None
    limit: int = 1000


def _receipt_duplicate_response(existing: dict, message: str = "This receipt was already scanned."):
    return {
        "success": False,
        "duplicate": True,
        "already_scanned": True,
        "message": message,
        "receipt": existing,
        "saved_id": existing.get("id"),
    }


def find_already_scanned_receipt(receipt_data: dict, user_id: str | None = None, guest_session_id: str | None = None) -> dict | None:
    """Detect the same receipt even when it was retaken and the image hash changed."""
    if not receipt_data:
        return None

    try:
        q = database.supabase.table("receipts").select("*")
        if user_id:
            q = q.eq("user_id", user_id)
        elif guest_session_id:
            q = q.eq("is_guest", True).eq("guest_session_id", guest_session_id)
        else:
            return None

        result = q.order("created_at", desc=True).limit(200).execute()
        for existing in result.data or []:
            if agent_service.looks_like_same_receipt(receipt_data, existing):
                return existing
    except Exception as e:
        logger.warning("Semantic duplicate receipt check skipped: %s", e)
    return None


def clear_receipt_memory_caches(user_id: str | None = None, guest_session_id: str | None = None):
    agent_service.clear_owner_data_caches(user_id=user_id, guest_session_id=guest_session_id)


def get_user_id_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.replace("Bearer ", "").strip()
    if not token or token == "guest":
        return None
    try:
        user_response = database.supabase.auth.get_user(token)
        if user_response and user_response.user:
            return str(user_response.user.id)
    except Exception as e:
        logger.warning("Receipt token validation failed: %s", e)
    return None


def validate_guest_session_id(session_id: str | None) -> str:
    value = (session_id or "").strip()
    if (
        len(value) < 12
        or len(value) > 160
        or value in {"guest", "default"}
        or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
    ):
        raise HTTPException(status_code=401, detail="A valid guest session is required.")
    return value


def require_owner(request: Request, session_id: str | None = None) -> tuple[str | None, str | None]:
    user_id = get_user_id_from_request(request)
    if user_id:
        return user_id, None
    return None, validate_guest_session_id(session_id)


# ── ENDPOINT 1: Scan a receipt ──
# URL: POST http://127.0.0.1:8000/scan-receipt
# Accepts: image files (jpg, png, webp, gif) OR PDF files
# Returns: extracted receipt data or duplicate warning
@router.post("/scan-receipt")
async def scan_receipt(request: Request, file: UploadFile = File(...)):
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
    file_bytes = await file.read()
    validate_upload_size(file_bytes)

    # ── Extract user_id from Authorization header ──
    # Mobile app sends: Authorization: Bearer <token>
    user_id = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "").strip()
        try:
            user_response = database.supabase.auth.get_user(token)
            if user_response and user_response.user:
                user_id = str(user_response.user.id)
                logger.info("Authenticated receipt scan", extra={"user_id": user_id})
        except Exception as e:
            logger.warning("Could not resolve receipt-scan user token: %s", e)
            # Continue without user_id — will save as guest/anonymous
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    access = rbac.get_access_context(request)
    customer_id = rbac.primary_customer_id(access)
    rbac.require_permission(access, "receipts.upload", customer_id)
    enforce_scan_rate_limit(f"user:{user_id}")

    # ── Send to Claude for scanning ──
    try:
        # scan_receipt_image handles:
        # - PDF detection and conversion to image
        # - Duplicate detection via image hash
        # - Sending image to Claude API
        # - Parsing Claude's JSON response
        # - Returning structured receipt data
        receipt_data = claude.scan_receipt_image(file_bytes, file.filename, user_id=user_id)

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
        return _receipt_duplicate_response(
            receipt_data["existing_receipt"],
            receipt_data.get("message") or "This receipt was already scanned.",
        )

    existing_receipt = find_already_scanned_receipt(receipt_data, user_id=user_id)
    if existing_receipt:
        return _receipt_duplicate_response(existing_receipt)

    # ── Save new receipt to database ──
    # Wrap in try/except so we see the exact database error if it fails
    try:
        # .get() safely retrieves each field
        # If a field doesn't exist use the default value (0.00 or None)
        saved = database.save_receipt(
            # Store info
            store=receipt_data.get("store"),
            address=receipt_data.get("address"),

            # Purchase timing
            date=receipt_data.get("date"),
            time=receipt_data.get("time"),
            payment_method=receipt_data.get("payment_method"),

            # Items and money
            total=receipt_data.get("total"),
            items=receipt_data.get("items"),
            subtotal=receipt_data.get("subtotal", 0.00),
            discount=receipt_data.get("discount", 0.00),
            tax=receipt_data.get("tax", 0.00),
            total_savings=receipt_data.get("total_savings", 0.00),

            # User ownership — links receipt to logged-in user
            user_id=user_id,
            customer_id=customer_id,

            # Duplicate detection
            image_hash=receipt_data.get("image_hash"),
            transaction_number=receipt_data.get("transaction_number"),
            receipt_number=receipt_data.get("receipt_number"),
            invoice_number=receipt_data.get("invoice_number"),
            order_number=receipt_data.get("order_number"),
        )
        clear_receipt_memory_caches(user_id=user_id)
        record_scan_token_usage(
            receipt_data,
            user_id=user_id,
            customer_id=customer_id,
            receipt_id=saved.get("id"),
            filename=file.filename,
            file_bytes=len(file_bytes),
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
        "receipt":  public_receipt_data(receipt_data),
        "saved_id": saved.get("id")  # the ID assigned by Supabase
    }


# ── ENDPOINT 2: Get all receipts ──
# URL: GET http://127.0.0.1:8000/receipts
# Returns all saved receipts ordered by newest first
@router.post("/scan-receipt-pages")
async def scan_receipt_pages(request: Request, files: list[UploadFile] = File(...)):
    """Scan multiple receipt/invoice photos as one combined document."""
    user_id = get_user_id_from_request(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")
    access = rbac.get_access_context(request)
    customer_id = rbac.primary_customer_id(access)
    rbac.require_permission(access, "receipts.upload", customer_id)
    enforce_scan_rate_limit(f"user:{user_id}")
    if not files or len(files) < 2:
        raise HTTPException(status_code=400, detail="Upload at least 2 page photos for multi-page scanning.")

    page_files: list[tuple[bytes, str]] = []
    for file in files:
        extension = file.filename.split(".")[-1].lower()
        if extension not in MEDIA_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported page type: .{extension}. Please use jpg, png, webp, or gif.")
        page_bytes = await file.read()
        validate_upload_size(page_bytes)
        page_files.append((page_bytes, file.filename))

    try:
        receipt_data = claude.scan_receipt_image_pages(page_files, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scanning receipt pages: {str(e)}")

    if receipt_data.get("duplicate"):
        return _receipt_duplicate_response(
            receipt_data["existing_receipt"],
            receipt_data.get("message") or "This receipt was already scanned.",
        )

    existing_receipt = find_already_scanned_receipt(receipt_data, user_id=user_id)
    if existing_receipt:
        return _receipt_duplicate_response(existing_receipt)

    try:
        saved = database.save_receipt(
            store=receipt_data.get("store"),
            address=receipt_data.get("address"),
            date=receipt_data.get("date"),
            time=receipt_data.get("time"),
            payment_method=receipt_data.get("payment_method"),
            total=receipt_data.get("total"),
            items=receipt_data.get("items"),
            subtotal=receipt_data.get("subtotal", 0.00),
            discount=receipt_data.get("discount", 0.00),
            tax=receipt_data.get("tax", 0.00),
            total_savings=receipt_data.get("total_savings", 0.00),
            user_id=user_id,
            customer_id=customer_id,
            image_hash=receipt_data.get("image_hash"),
            transaction_number=receipt_data.get("transaction_number"),
            receipt_number=receipt_data.get("receipt_number"),
            invoice_number=receipt_data.get("invoice_number"),
            order_number=receipt_data.get("order_number"),
        )
        clear_receipt_memory_caches(user_id=user_id)
        record_scan_token_usage(
            receipt_data,
            user_id=user_id,
            customer_id=customer_id,
            receipt_id=saved.get("id"),
            filename=f"{len(files)} pages",
            file_bytes=sum(len(content) for content, _ in page_files),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database save error: {str(e)}")

    return {
        "success": True,
        "duplicate": False,
        "message": "Receipt pages scanned and saved!",
        "filename": f"{len(files)} pages",
        "receipt": public_receipt_data(receipt_data),
        "saved_id": saved.get("id"),
    }


@router.get("/receipts")
def get_receipts(request: Request):
    """
    Return receipts for the current user only.
    - Logged in users see ONLY their own receipts
    - No token = no receipts returned (must log in)
    """
    access = rbac.get_access_context(request)
    receipts = rbac.list_accessible_receipts(access)
    return {"total_receipts": len(receipts), "receipts": receipts}


# ── ENDPOINT 3: Get receipts by store ──
# URL: GET http://127.0.0.1:8000/receipts/store/walmart
# store_name comes from the URL path
# Uses partial case insensitive matching
# so "lowes" matches "LOWE'S HOME CENTERS, LLC"
@router.get("/receipts/store/{store_name}")
def get_by_store(store_name: str, request: Request, session_id: str | None = None):
    """
    Filter receipts by store name.

    Matching is:
    - Case insensitive: "walmart" matches "WALMART"
    - Partial: "lowe" matches "LOWE'S HOME CENTERS, LLC"
    - "dine" matches "DINEFINE RESTAURANT"

    Returns matching receipts ordered by newest first.
    """

    user_id = get_user_id_from_request(request)
    if user_id:
        receipts = [row for row in rbac.list_accessible_receipts(rbac.get_access_context(request)) if store_name.casefold() in str(row.get("store") or "").casefold()]
    else:
        receipts = database.get_receipts_by_store(store_name, guest_session_id=validate_guest_session_id(session_id))

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
def get_by_date(from_date: str, to_date: str, request: Request, session_id: str | None = None):
    """
    Filter receipts between two dates.

    Both parameters are required.
    Date format: YYYY-MM-DD (e.g. 2026-01-01)

    Returns receipts in that date range ordered by newest first.
    """

    user_id = get_user_id_from_request(request)
    if user_id:
        start, end = database.parse_purchase_date(from_date), database.parse_purchase_date(to_date)
        receipts = [
            row for row in rbac.list_accessible_receipts(rbac.get_access_context(request))
            if start and end and (parsed := database.parse_purchase_date(row.get("date") or row.get("created_at"))) and start <= parsed <= end
        ]
    else:
        receipts = database.get_receipts_by_date(from_date, to_date, guest_session_id=validate_guest_session_id(session_id))

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




# ── ENDPOINT: Cleanup expired guest receipts ──
# Called automatically or manually to delete guest data older than 24 hours
def cleanup_guest_receipts():
    """
    Delete all guest receipts older than 24 hours.
    Should be called periodically (e.g. every hour via a cron job).
    """
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        result = database.supabase.table("receipts")            .delete()            .eq("is_guest", True)            .lt("expires_at", cutoff)            .execute()
        deleted_count = len(result.data) if result.data else 0
        logger.info("Deleted %s expired guest receipts", deleted_count)
        return {"success": True, "deleted": deleted_count, "message": f"Deleted {deleted_count} expired guest receipts."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup error: {str(e)}")


# ── ENDPOINT: Save guest receipt ──
@router.post("/guest/scan-receipt")
async def guest_scan_receipt(file: UploadFile = File(...), session_id: str | None = None):
    """
    Scan a receipt for guest users.
    Automatically marks it as guest data with 24-hour expiry.
    """
    from datetime import datetime, timedelta, timezone

    session_id = validate_guest_session_id(session_id)
    enforce_scan_rate_limit(f"guest:{session_id}")
    extension = file.filename.split(".")[-1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{extension}")

    file_bytes = await file.read()
    validate_upload_size(file_bytes)

    try:
        receipt_data = claude.scan_receipt_image(file_bytes, file.filename, guest_session_id=session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scanning receipt: {str(e)}")

    if receipt_data.get("duplicate"):
        return _receipt_duplicate_response(
            receipt_data["existing_receipt"],
            receipt_data.get("message") or "This receipt was already scanned.",
        )

    existing_receipt = find_already_scanned_receipt(receipt_data, guest_session_id=session_id)
    if existing_receipt:
        return _receipt_duplicate_response(existing_receipt)

    # Set 24-hour expiry for guest receipts
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    try:
        saved = database.insert_receipt_with_optional_identifiers({
            "store":            receipt_data.get("store"),
            "address":          receipt_data.get("address"),
            "date":             receipt_data.get("date"),
            "time":             receipt_data.get("time"),
            "payment_method":   receipt_data.get("payment_method"),
            "total":            receipt_data.get("total"),
            "items":            receipt_data.get("items"),
            "subtotal":         receipt_data.get("subtotal", 0.00),
            "discount":         receipt_data.get("discount", 0.00),
            "tax":              receipt_data.get("tax", 0.00),
            "total_savings":    receipt_data.get("total_savings", 0.00),
            "image_hash":       receipt_data.get("image_hash"),
            "is_guest":         True,
            "guest_session_id": session_id,
            "expires_at":       expires_at,
            "transaction_number": receipt_data.get("transaction_number"),
            "receipt_number": receipt_data.get("receipt_number"),
            "invoice_number": receipt_data.get("invoice_number"),
            "order_number": receipt_data.get("order_number"),
        })
        saved_receipt = saved.data[0] if saved.data else {}
        database.save_receipt_items(
            saved_receipt,
            receipt_data.get("items"),
            guest_session_id=session_id,
            is_guest=True,
            expires_at=expires_at,
        )
        clear_receipt_memory_caches(guest_session_id=session_id)
        record_scan_token_usage(
            receipt_data,
            guest_session_id=session_id,
            receipt_id=saved_receipt.get("id") if saved_receipt else None,
            filename=file.filename,
            file_bytes=len(file_bytes),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database save error: {str(e)}")

    return {
        "success":  True,
        "duplicate": False,
        "message":  "Receipt scanned! Note: Guest data expires in 24 hours.",
        "receipt":  public_receipt_data(receipt_data),
        "expires_at": expires_at,
        "saved_id": saved_receipt.get("id") if saved_receipt else None
    }



# ── ENDPOINT: Summary stats for current user ──
@router.post("/guest/scan-receipt-pages")
async def guest_scan_receipt_pages(files: list[UploadFile] = File(...), session_id: str | None = None):
    """Scan multiple receipt/invoice photos as one combined guest document."""
    from datetime import datetime, timedelta, timezone

    session_id = validate_guest_session_id(session_id)
    enforce_scan_rate_limit(f"guest:{session_id}")
    if not files or len(files) < 2:
        raise HTTPException(status_code=400, detail="Upload at least 2 page photos for multi-page scanning.")

    page_files: list[tuple[bytes, str]] = []
    for file in files:
        extension = file.filename.split(".")[-1].lower()
        if extension not in MEDIA_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported page type: .{extension}. Please use jpg, png, webp, or gif.")
        page_bytes = await file.read()
        validate_upload_size(page_bytes)
        page_files.append((page_bytes, file.filename))

    try:
        receipt_data = claude.scan_receipt_image_pages(page_files, guest_session_id=session_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scanning receipt pages: {str(e)}")

    if receipt_data.get("duplicate"):
        return _receipt_duplicate_response(
            receipt_data["existing_receipt"],
            receipt_data.get("message") or "This receipt was already scanned.",
        )

    existing_receipt = find_already_scanned_receipt(receipt_data, guest_session_id=session_id)
    if existing_receipt:
        return _receipt_duplicate_response(existing_receipt)

    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    try:
        saved = database.insert_receipt_with_optional_identifiers({
            "store": receipt_data.get("store"),
            "address": receipt_data.get("address"),
            "date": receipt_data.get("date"),
            "time": receipt_data.get("time"),
            "payment_method": receipt_data.get("payment_method"),
            "total": receipt_data.get("total"),
            "items": receipt_data.get("items"),
            "subtotal": receipt_data.get("subtotal", 0.00),
            "discount": receipt_data.get("discount", 0.00),
            "tax": receipt_data.get("tax", 0.00),
            "total_savings": receipt_data.get("total_savings", 0.00),
            "image_hash": receipt_data.get("image_hash"),
            "is_guest": True,
            "guest_session_id": session_id,
            "expires_at": expires_at,
            "transaction_number": receipt_data.get("transaction_number"),
            "receipt_number": receipt_data.get("receipt_number"),
            "invoice_number": receipt_data.get("invoice_number"),
            "order_number": receipt_data.get("order_number"),
        })
        saved_receipt = saved.data[0] if saved.data else {}
        database.save_receipt_items(
            saved_receipt,
            receipt_data.get("items"),
            guest_session_id=session_id,
            is_guest=True,
            expires_at=expires_at,
        )
        clear_receipt_memory_caches(guest_session_id=session_id)
        record_scan_token_usage(
            receipt_data,
            guest_session_id=session_id,
            receipt_id=saved_receipt.get("id") if saved_receipt else None,
            filename=f"{len(files)} pages",
            file_bytes=sum(len(content) for content, _ in page_files),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database save error: {str(e)}")

    return {
        "success": True,
        "duplicate": False,
        "message": "Receipt pages scanned! Note: Guest data expires in 24 hours.",
        "receipt": public_receipt_data(receipt_data),
        "expires_at": expires_at,
        "saved_id": saved_receipt.get("id") if saved_receipt else None,
    }


@router.get("/guest/receipts")
def get_guest_receipts(session_id: str):
    """Return only receipts owned by the opaque guest session."""
    guest_session_id = validate_guest_session_id(session_id)
    try:
        result = database.supabase.table("receipts")\
            .select("*")\
            .eq("is_guest", True)\
            .eq("guest_session_id", guest_session_id)\
            .order("created_at", desc=True)\
            .execute()
        rows = result.data or []
    except Exception as e:
        logger.exception("Guest receipt listing failed")
        raise HTTPException(status_code=503, detail="Receipt data is temporarily unavailable.")
    return {"total_receipts": len(rows), "receipts": rows}


@router.get("/summary")
def get_summary(request: Request, session_id: str | None = None):
    """Return spending summary for exactly one authenticated or guest owner."""
    try:
        user_id = get_user_id_from_request(request)
        if user_id:
            receipts = rbac.list_accessible_receipts(rbac.get_access_context(request))
        else:
            guest_session_id = validate_guest_session_id(session_id)
            receipts = database.supabase.table("receipts").select("total,total_savings,store").eq("is_guest", True).eq("guest_session_id", guest_session_id).execute().data or []
        total_spent   = sum(r.get("total") or 0 for r in receipts)
        total_saved   = sum(r.get("total_savings") or 0 for r in receipts)
        unique_stores = len(set(r.get("store","") for r in receipts if r.get("store")))
        return {
            "total_receipts": len(receipts),
            "total_spent":    round(total_spent, 2),
            "total_saved":    round(total_saved, 2),
            "unique_stores":  unique_stores,
        }
    except Exception as e:
        logger.exception("Receipt summary failed")
        raise HTTPException(status_code=503, detail="Summary is temporarily unavailable.")

# ── ENDPOINT 5: Delete a receipt ──
# URL: DELETE http://127.0.0.1:8000/receipts/5
# receipt_id comes from the URL path
# This permanently deletes the receipt — cannot be undone
@router.get("/price-memory")
def get_price_memory(request: Request, session_id: str | None = None, limit: int = 100):
    """
    Return personal Price Memory / Price DNA profiles.
    Logged-in users are filtered by JWT. Guests must provide session_id.
    """
    user_id, guest_session_id = require_owner(request, session_id)

    profiles = agent_service.build_price_memory(user_id=user_id, guest_session_id=guest_session_id, limit=1000)
    return {
        "success": True,
        "count": len(profiles),
        "items": profiles[:max(1, min(limit, 300))],
    }


@router.get("/price-memory/search")
def search_price_memory(request: Request, item: str, session_id: str | None = None):
    """
    Search personal Price Memory for one item.
    Use this before the next purchase to decide good price / avoid price.
    """
    user_id, guest_session_id = require_owner(request, session_id)

    result = agent_service.search_price_memory(item, user_id=user_id, guest_session_id=guest_session_id)
    return {"success": True, **result}


@router.post("/receipts/backfill-vectors")
def backfill_vectors(request: Request, payload: BackfillVectorsRequest | None = None):
    """Backfill normalized item rows and local vectors for existing receipts."""
    payload = payload or BackfillVectorsRequest()
    user_id, guest_session_id = require_owner(request, payload.session_id)

    result = database.backfill_receipt_vectors(
        user_id=user_id,
        guest_session_id=guest_session_id,
        limit=max(1, min(payload.limit or 1000, 10000)),
    )
    clear_receipt_memory_caches(user_id=user_id, guest_session_id=guest_session_id)
    return result


@router.get("/shopping-plan")
def get_shopping_plan(request: Request, session_id: str | None = None):
    """
    Build the next shopping plan from personal Price Memory.
    """
    user_id, guest_session_id = require_owner(request, session_id)

    plan = agent_service.build_next_shopping_plan(user_id=user_id, guest_session_id=guest_session_id)
    return {"success": True, **plan}


@router.get("/price-alerts")
def get_price_alerts(request: Request, session_id: str | None = None):
    """
    Return proactive Price Memory alerts.
    """
    user_id, guest_session_id = require_owner(request, session_id)

    alerts = agent_service.build_price_alerts(user_id=user_id, guest_session_id=guest_session_id)
    return {"success": True, **alerts}


@router.post("/live-price-check")
def live_price_check(body: LivePriceCheckRequest, request: Request):
    """
    Compare a current shelf/web price against the user's receipt-based Price Memory.
    For true live provider lookups, set live_search=true; otherwise send current_price.
    """
    user_id, guest_session_id = require_owner(request, body.session_id)
    if not body.item_name.strip():
        raise HTTPException(status_code=400, detail="item_name is required.")
    if body.current_price is None and not body.live_search:
        raise HTTPException(status_code=400, detail="Send current_price or set live_search=true.")

    result = agent_service.build_live_price_check(
        item_query=body.item_name,
        current_price=body.current_price,
        store=body.store,
        source_url=body.source_url,
        user_id=user_id,
        guest_session_id=guest_session_id,
        live_search=body.live_search,
    )
    return result


@router.patch("/receipts/{receipt_id}/items/{line_index}")
def update_receipt_item(receipt_id: int, line_index: int, body: ReceiptItemUpdate, request: Request):
    """
    Correct one scanned receipt item. This keeps Price Memory accurate after OCR mistakes.
    Updates both receipts.items JSON and the normalized receipt_items row.
    """
    user_id = get_user_id_from_request(request)
    guest_session_id = None

    try:
        if user_id:
            access = rbac.get_access_context(request)
            receipt = rbac.get_receipt_for_access(access, receipt_id, "receipts.correct_items")
        else:
            guest_session_id = validate_guest_session_id(body.session_id)
            rows = database.supabase.table("receipts").select("*").eq("id", receipt_id).eq("is_guest", True).eq("guest_session_id", guest_session_id).limit(1).execute().data or []
            receipt = rows[0] if rows else None
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not load receipt: {str(e)}")

    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")

    items = receipt.get("items") or []
    if line_index < 0 or line_index >= len(items) or not isinstance(items[line_index], dict):
        raise HTTPException(status_code=404, detail="Receipt item not found.")

    item = dict(items[line_index])
    if body.name is not None and body.name.strip():
        item["name"] = body.name.strip()
    if body.price is not None:
        item["price"] = round(float(body.price), 2)
    if body.quantity is not None:
        item["quantity"] = float(body.quantity)
    if body.unit_price is not None:
        item["unit_price"] = round(float(body.unit_price), 2)
    if body.unit is not None and body.unit.strip():
        item["unit"] = body.unit.strip()
    if body.product_size is not None:
        item["product_size"] = body.product_size.strip() or None
    if body.code is not None:
        item["code"] = body.code.strip() or None
    if body.category is not None:
        item["category"] = body.category.strip() or None

    item["corrected_by_user"] = True
    items[line_index] = item

    try:
        updated = database.supabase.table("receipts")\
            .update({"items": items})\
            .eq("id", receipt_id)\
            .execute()

        normalized_name = database.normalize_item_name(item.get("normalized_name") or item.get("name") or item.get("item"))
        line_price = item.get("price")
        quantity = item.get("quantity", 1) or 1
        unit_price = item.get("unit_price") or line_price
        receipt_item_update = {
            "code": item.get("code"),
            "item_name_original": item.get("name") or item.get("item") or "Unknown item",
            "item_name_normalized": normalized_name,
            "product_size": item.get("product_size") or database.find_product_size(item.get("name") or item.get("item")),
            "quantity": quantity,
            "raw_quantity": quantity,
            "unit": item.get("unit") or "each",
            "unit_price": round(float(unit_price), 2) if unit_price is not None else None,
            "line_price": round(float(line_price), 2) if line_price is not None else None,
            "metadata": item,
        }
        database.supabase.table("receipt_items")\
            .update(receipt_item_update)\
            .eq("receipt_id", receipt_id)\
            .eq("line_index", line_index)\
            .execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not update receipt item: {str(e)}")

    clear_receipt_memory_caches(user_id=user_id, guest_session_id=guest_session_id)
    if user_id:
        rbac.audit(access, "receipt.item.correct", "receipt", receipt_id, receipt.get("customer_id"), metadata={"line_index": line_index})

    return {
        "success": True,
        "message": "Receipt item corrected.",
        "receipt": (updated.data or [receipt])[0],
        "item": item,
    }


@router.patch("/receipts/{receipt_id}")
def update_receipt_metadata(receipt_id: int, body: ReceiptMetadataUpdate, request: Request):
    """Update operator-editable receipt header fields after centralized authorization."""
    access = rbac.get_access_context(request)
    receipt = rbac.get_receipt_for_access(access, receipt_id, "receipts.update")
    allowed = body.model_dump(exclude_none=True)
    cleaned = {
        key: (value.strip() if isinstance(value, str) else value)
        for key, value in allowed.items()
    }
    if not cleaned:
        raise HTTPException(status_code=400, detail="No receipt fields were provided.")
    try:
        result = database.supabase.table("receipts").update(cleaned).eq("id", receipt_id).execute()
        item_fields = {}
        if "store" in cleaned:
            item_fields["store"] = cleaned["store"]
        if "date" in cleaned:
            item_fields["purchase_date"] = cleaned["date"]
        if item_fields:
            database.supabase.table("receipt_items").update(item_fields).eq("receipt_id", receipt_id).execute()
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Could not update receipt: {error}")
    clear_receipt_memory_caches(user_id=receipt.get("user_id"), guest_session_id=receipt.get("guest_session_id"))
    rbac.audit(access, "receipt.update", "receipt", receipt_id, receipt.get("customer_id"), metadata={"fields": sorted(cleaned)})
    return {"success": True, "receipt": (result.data or [{**receipt, **cleaned}])[0]}


@router.delete("/receipts/{receipt_id}")
def delete_receipt(receipt_id: int, request: Request, session_id: str | None = None):
    """
    Permanently delete a receipt by its ID.

    This cannot be undone — the UI shows a confirmation
    dialog before calling this endpoint.

    The receipt ID can be found in the receipts list
    shown as #1, #2 etc in the UI.
    """

    # Attempt to delete — returns deleted record or empty dict
    user_id = get_user_id_from_request(request)
    if user_id:
        access = rbac.get_access_context(request)
        receipt = rbac.get_receipt_for_access(access, receipt_id, "receipts.delete")
        deleted = database.delete_receipt_after_authorization(receipt)
        if deleted:
            rbac.audit(access, "receipt.delete", "receipt", receipt_id, receipt.get("customer_id"))
    else:
        deleted = database.delete_receipt(receipt_id, guest_session_id=validate_guest_session_id(session_id))

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
