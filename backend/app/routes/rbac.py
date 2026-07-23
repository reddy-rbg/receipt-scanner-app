"""Administrative RBAC endpoints. All authorization is enforced server-side."""

from datetime import datetime, timedelta, timezone
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config import supabase
from app.services import database, rbac


router = APIRouter(prefix="/rbac", tags=["access-control"])
CUSTOMER_REQUIRED_ROLES = {"customer_owner", "customer_user", "auditor", "service_account"}
TOKEN_PERIOD_DAYS = {"day": 1, "week": 7, "month": 31, "year": 366}


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str | None = Field(default=None, max_length=80)


class RoleAssignmentCreate(BaseModel):
    user_id: str
    role_key: str
    customer_id: str | None = None


class RolePermissionsUpdate(BaseModel):
    permissions: list[str]


class SupportGrantCreate(BaseModel):
    support_user_id: str
    customer_id: str | None = None
    receipt_id: int | None = None
    permissions: list[str] = Field(default_factory=lambda: ["receipts.read"])
    reason: str = Field(min_length=3, max_length=500)
    case_id: str | None = Field(default=None, max_length=120)
    expires_at: datetime


class ReceiptAssignmentCreate(BaseModel):
    assignee_user_id: str
    receipt_id: int
    permissions: list[str] = Field(default_factory=lambda: ["receipts.read", "receipts.correct_items"])
    expires_at: datetime | None = None


class BulkReceiptAssignmentCreate(BaseModel):
    assignee_user_id: str
    receipt_ids: list[int] = Field(default_factory=list)
    all_accessible: bool = False
    from_date: str | None = None
    to_date: str | None = None
    year: int | None = Field(default=None, ge=2000, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)
    permissions: list[str] = Field(default_factory=lambda: ["receipts.read", "receipts.correct_items"])
    expires_at: datetime | None = None


class OperatorCreate(BaseModel):
    email: str
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role_key: str
    customer_id: str | None = None


class UserStatusUpdate(BaseModel):
    active: bool


def _global_admin(context: rbac.AccessContext) -> bool:
    return bool(context.role_keys & {"platform_admin", "master_user"})


def _can_manage_customer(context: rbac.AccessContext, customer_id: str | None) -> bool:
    return _global_admin(context) or bool(customer_id and any(
        role.role_key == "customer_owner" and role.customer_id == customer_id
        for role in context.roles
    ))


def _validate_permissions(values: list[str]) -> list[str]:
    allowed = set().union(*rbac.ROLE_PERMISSIONS.values()) - {"*"}
    cleaned = sorted({value.strip() for value in values if value.strip()})
    if not cleaned or any(value not in allowed for value in cleaned):
        raise HTTPException(status_code=400, detail="One or more permissions are invalid.")
    return cleaned


def _require_assignment_manager(context: rbac.AccessContext) -> None:
    if not context.is_global and "customer_owner" not in context.role_keys:
        raise HTTPException(status_code=403, detail="Only an administrator or customer owner can assign receipt work.")


def _validate_receipt_assignee(user_id: str) -> None:
    rows = supabase.table("rbac_user_roles").select("id").eq("user_id", user_id).eq("role_key", "receipt_editor").eq("active", True).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=400, detail="The selected operator is not an active Receipt Editor.")


def _parse_utc(value: Any) -> datetime | None:
    try:
        text = str(value or "").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _token_bucket(created_at: datetime, period: str) -> str:
    if period == "day":
        return created_at.strftime("%H:00")
    if period == "week":
        return created_at.strftime("%a")
    if period == "year":
        return created_at.strftime("%b")
    return created_at.strftime("%b %d")


def _sum_token_rows(rows: list[dict]) -> dict[str, Any]:
    input_tokens = sum(int(row.get("input_tokens") or 0) for row in rows)
    output_tokens = sum(int(row.get("output_tokens") or 0) for row in rows)
    total_tokens = sum(int(row.get("total_tokens") or 0) for row in rows) or input_tokens + output_tokens
    cached_tokens = sum(int(row.get("cached_input_tokens") or 0) for row in rows)
    estimated_image_tokens_saved = sum(_estimated_image_tokens_saved(row) for row in rows)
    estimated_costs = [row.get("estimated_cost_usd") for row in rows if row.get("estimated_cost_usd") is not None]
    return {
        "events": len(rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_tokens,
        "total_tokens": total_tokens,
        "estimated_image_tokens_saved": estimated_image_tokens_saved,
        "estimated_cost_usd": round(sum(float(value or 0) for value in estimated_costs), 6) if estimated_costs else None,
    }


def _estimated_image_tokens_saved(row: dict) -> int:
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            import json

            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    if not isinstance(metadata, dict):
        return 0
    try:
        return int(metadata.get("estimated_image_tokens_saved") or 0)
    except Exception:
        return 0


@router.get("/me")
def access_profile(request: Request):
    context = rbac.get_access_context(request)
    return {
        "user_id": context.user_id,
        "email": context.email,
        "roles": [role.__dict__ for role in context.roles],
        "permissions": sorted(context.permissions()),
        "customer_ids": sorted(context.customer_ids),
        "rbac_available": context.rbac_available,
    }


@router.get("/roles")
def list_roles(request: Request):
    context = rbac.get_access_context(request)
    rbac.require_permission(context, "users.read")
    result = supabase.table("rbac_roles").select("role_key,display_name,description,is_system").order("role_key").execute()
    permission_rows = supabase.table("rbac_role_permissions").select("role_key,permission_key").execute().data or []
    mapped: dict[str, list[str]] = {}
    for row in permission_rows:
        mapped.setdefault(str(row.get("role_key")), []).append(str(row.get("permission_key")))
    roles = [{**row, "permissions": sorted(mapped.get(str(row.get("role_key")), []))} for row in (result.data or [])]
    return {"roles": roles}


@router.get("/customers")
def list_customers(request: Request):
    context = rbac.get_access_context(request)
    query = supabase.table("customers").select("id,name,slug,kind,created_at").order("name")
    if not context.is_global:
        ids = set(context.customer_ids)
        ids |= {str(grant.get("customer_id")) for grant in context.grants if grant.get("customer_id")}
        if not ids:
            return {"customers": []}
        query = query.in_("id", sorted(ids))
    return {"customers": query.execute().data or []}


def _user_dict(user: Any) -> dict[str, Any]:
    metadata = getattr(user, "user_metadata", None) or {}
    return {
        "id": str(getattr(user, "id", "")),
        "email": getattr(user, "email", None),
        "name": metadata.get("name") or metadata.get("full_name") or (getattr(user, "email", "") or "User").split("@")[0],
        "created_at": str(getattr(user, "created_at", "") or ""),
        "last_sign_in_at": str(getattr(user, "last_sign_in_at", "") or ""),
        "banned_until": str(getattr(user, "banned_until", "") or "") or None,
    }


def _visible_role_rows(context: rbac.AccessContext) -> list[dict]:
    query = supabase.table("rbac_user_roles").select("id,user_id,role_key,customer_id,active,created_at,assigned_by")
    if not context.is_global:
        if not context.customer_ids:
            return []
        scoped = query.in_("customer_id", sorted(context.customer_ids)).order("created_at", desc=True).execute().data or []
        created = supabase.table("rbac_user_roles").select("id,user_id,role_key,customer_id,active,created_at,assigned_by").eq("assigned_by", context.user_id).order("created_at", desc=True).execute().data or []
        return list({str(row.get("id")): row for row in scoped + created}.values())
    return query.order("created_at", desc=True).execute().data or []


@router.get("/users")
def list_users(request: Request):
    context = rbac.get_access_context(request)
    rbac.require_permission(context, "users.read")
    roles = _visible_role_rows(context)
    visible_ids = {str(row.get("user_id")) for row in roles}
    try:
        users = [_user_dict(user) for user in supabase.auth.admin.list_users(page=1, per_page=1000)]
    except Exception as error:
        print(f"[rbac] Could not list auth users: {error}")
        raise HTTPException(status_code=503, detail="User directory is temporarily unavailable.")
    if not context.is_global:
        users = [user for user in users if user["id"] in visible_ids]
    role_map: dict[str, list[dict]] = {}
    for row in roles:
        role_map.setdefault(str(row.get("user_id")), []).append(row)
    return {"users": [{**user, "roles": role_map.get(user["id"], [])} for user in users]}


@router.get("/user-roles")
def list_user_roles(request: Request):
    context = rbac.get_access_context(request)
    rbac.require_permission(context, "users.read")
    return {"assignments": _visible_role_rows(context)}


@router.post("/users", status_code=201)
def create_operator(body: OperatorCreate, request: Request):
    context = rbac.get_access_context(request)
    rbac.require_permission(context, "users.manage", body.customer_id)
    if body.role_key in {"platform_admin", "master_user", "support_agent", "service_account"} and "platform_admin" not in context.role_keys:
        raise HTTPException(status_code=403, detail="Platform administrator access required for this role.")
    if body.role_key not in rbac.ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail="Unknown role.")
    if body.role_key in CUSTOMER_REQUIRED_ROLES and not body.customer_id:
        raise HTTPException(status_code=400, detail="customer_id is required for this role.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", body.email.strip()):
        raise HTTPException(status_code=400, detail="A valid operator email is required.")
    if not (re.search(r"[A-Z]", body.password) and re.search(r"[a-z]", body.password) and re.search(r"[^A-Za-z0-9]", body.password)):
        raise HTTPException(status_code=400, detail="Password must include upper-case, lower-case, and special characters.")
    try:
        response = supabase.auth.admin.create_user({
            "email": body.email.strip().lower(),
            "password": body.password,
            "email_confirm": True,
            "user_metadata": {"name": body.name.strip(), "full_name": body.name.strip()},
        })
        user = response.user
        if not user:
            raise RuntimeError("User was not created")
        user_id = str(user.id)
        role_payload = {"user_id": user_id, "role_key": body.role_key, "customer_id": body.customer_id, "assigned_by": context.user_id, "active": True}
        supabase.table("rbac_user_roles").upsert(role_payload, on_conflict="user_id,role_key,customer_id").execute()
    except HTTPException:
        raise
    except Exception as error:
        message = str(error)
        if "already" in message.lower() or "registered" in message.lower():
            raise HTTPException(status_code=409, detail="A user with this email already exists.")
        raise HTTPException(status_code=500, detail=f"Could not create operator: {message}")
    rbac.clear_context_cache(user_id)
    rbac.audit(context, "user.create", "user", user_id, body.customer_id, metadata={"email": body.email.strip().lower(), "role_key": body.role_key})
    return {"user": _user_dict(user), "role": role_payload}


@router.patch("/users/{user_id}/status")
def update_user_status(user_id: str, body: UserStatusUpdate, request: Request):
    context = rbac.get_access_context(request)
    if user_id == context.user_id and not body.active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")
    rows = supabase.table("rbac_user_roles").select("customer_id,role_key").eq("user_id", user_id).eq("active", True).execute().data or []
    protected_target = any(row.get("role_key") in {"platform_admin", "master_user"} for row in rows)
    if protected_target and "platform_admin" not in context.role_keys:
        raise HTTPException(status_code=403, detail="Only a platform administrator can change this account.")
    if context.is_global:
        rbac.require_permission(context, "users.manage")
    else:
        manageable = [row for row in rows if row.get("customer_id") in context.customer_ids and row.get("role_key") not in {"platform_admin", "master_user", "support_agent", "service_account"}]
        if not manageable:
            raise HTTPException(status_code=403, detail="You cannot manage this user.")
        rbac.require_permission(context, "users.manage", str(manageable[0].get("customer_id")))
    supabase.auth.admin.update_user_by_id(user_id, {"ban_duration": "none" if body.active else "876000h"})
    rbac.clear_context_cache(user_id)
    rbac.audit(context, "user.activate" if body.active else "user.deactivate", "user", user_id, metadata={"active": body.active})
    return {"success": True, "active": body.active}


@router.post("/customers", status_code=201)
def create_customer(body: CustomerCreate, request: Request):
    context = rbac.get_access_context(request)
    if "platform_admin" not in context.role_keys:
        raise HTTPException(status_code=403, detail="Platform administrator access required.")
    payload = {"name": body.name.strip(), "slug": (body.slug or body.name).strip().lower().replace(" ", "-"), "kind": "organization", "created_by": context.user_id}
    result = supabase.table("customers").insert(payload).execute()
    created = (result.data or [{}])[0]
    rbac.audit(context, "customer.create", "customer", created.get("id"), created.get("id"), metadata=payload)
    return created


@router.post("/user-roles", status_code=201)
def assign_role(body: RoleAssignmentCreate, request: Request):
    context = rbac.get_access_context(request)
    if body.role_key in {"platform_admin", "master_user", "support_agent", "service_account"}:
        if "platform_admin" not in context.role_keys:
            raise HTTPException(status_code=403, detail="Platform administrator access required for this role.")
    elif not _can_manage_customer(context, body.customer_id):
        raise HTTPException(status_code=403, detail="You cannot manage roles for this customer.")
    if body.role_key not in rbac.ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail="Unknown role.")
    if body.role_key in CUSTOMER_REQUIRED_ROLES and not body.customer_id:
        raise HTTPException(status_code=400, detail="customer_id is required for this role.")
    payload = {**body.model_dump(), "assigned_by": context.user_id, "active": True}
    result = supabase.table("rbac_user_roles").upsert(payload, on_conflict="user_id,role_key,customer_id").execute()
    rbac.clear_context_cache(body.user_id)
    rbac.audit(context, "role.assign", "user", body.user_id, body.customer_id, metadata={"role_key": body.role_key})
    return (result.data or [payload])[0]


@router.put("/roles/{role_key}/permissions")
def update_role_permissions(role_key: str, body: RolePermissionsUpdate, request: Request):
    context = rbac.get_access_context(request)
    if "platform_admin" not in context.role_keys:
        raise HTTPException(status_code=403, detail="Platform administrator access required.")
    if role_key == "platform_admin":
        raise HTTPException(status_code=400, detail="Platform administrator permissions cannot be reduced through the API.")
    if role_key not in rbac.ROLE_PERMISSIONS:
        raise HTTPException(status_code=404, detail="Role not found.")
    permissions = _validate_permissions(body.permissions)
    supabase.table("rbac_role_permissions").delete().eq("role_key", role_key).execute()
    if permissions:
        supabase.table("rbac_role_permissions").insert([{"role_key": role_key, "permission_key": value} for value in permissions]).execute()
    rbac.clear_context_cache()
    rbac.audit(context, "role.permissions.update", "role", role_key, metadata={"permissions": permissions})
    return {"success": True, "role_key": role_key, "permissions": permissions}


@router.delete("/user-roles/{assignment_id}")
def revoke_role(assignment_id: str, request: Request):
    context = rbac.get_access_context(request)
    rows = supabase.table("rbac_user_roles").select("*").eq("id", assignment_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Role assignment not found.")
    row = rows[0]
    if row.get("role_key") in {"platform_admin", "master_user", "support_agent", "service_account"}:
        allowed = "platform_admin" in context.role_keys
    else:
        allowed = _can_manage_customer(context, row.get("customer_id"))
    if not allowed:
        raise HTTPException(status_code=403, detail="You cannot revoke this role.")
    supabase.table("rbac_user_roles").update({"active": False}).eq("id", assignment_id).execute()
    rbac.clear_context_cache(str(row.get("user_id")))
    rbac.audit(context, "role.revoke", "user", row.get("user_id"), row.get("customer_id"), metadata={"role_key": row.get("role_key")})
    return {"success": True}


@router.post("/support-grants", status_code=201)
def grant_support_access(body: SupportGrantCreate, request: Request):
    context = rbac.get_access_context(request)
    if body.support_user_id == context.user_id:
        raise HTTPException(status_code=403, detail="Support users cannot approve their own access.")
    support_roles = supabase.table("rbac_user_roles").select("id").eq("user_id", body.support_user_id).eq("role_key", "support_agent").eq("active", True).limit(1).execute().data or []
    if not support_roles:
        raise HTTPException(status_code=400, detail="The selected user is not an active support agent.")
    if body.receipt_id is not None:
        receipt = rbac.get_receipt_for_access(context, body.receipt_id, "support.approve_access")
        receipt_customer_id = receipt.get("customer_id")
        if body.customer_id and str(body.customer_id) != str(receipt_customer_id):
            raise HTTPException(status_code=400, detail="Receipt does not belong to the selected customer.")
        body.customer_id = receipt_customer_id
    if not body.customer_id or not _can_manage_customer(context, body.customer_id):
        raise HTTPException(status_code=403, detail="You cannot approve access for this customer.")
    if body.expires_at.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="expires_at must be in the future.")
    permissions = _validate_permissions(body.permissions)
    permitted = {"receipts.read", "receipts.update", "receipts.correct_items", "receipts.view_image"}
    if any(value not in permitted for value in permissions):
        raise HTTPException(status_code=400, detail="Support grants may contain receipt-support permissions only.")
    payload: dict[str, Any] = body.model_dump(mode="json")
    payload["case_id"] = body.case_id or f"manual-{int(datetime.now(timezone.utc).timestamp())}"
    payload.update({"permissions": permissions, "approved_by": context.user_id})
    result = supabase.table("support_access_grants").insert(payload).execute()
    rbac.clear_context_cache(body.support_user_id)
    created = (result.data or [payload])[0]
    rbac.audit(context, "support.grant", "support_access_grant", created.get("id"), body.customer_id, body.reason, {"support_user_id": body.support_user_id, "permissions": permissions})
    return created


@router.post("/support-grants/{grant_id}/revoke")
def revoke_support_access(grant_id: str, request: Request):
    context = rbac.get_access_context(request)
    rows = supabase.table("support_access_grants").select("*").eq("id", grant_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Support grant not found.")
    row = rows[0]
    if not _can_manage_customer(context, row.get("customer_id")):
        raise HTTPException(status_code=403, detail="You cannot revoke this grant.")
    supabase.table("support_access_grants").update({"revoked_at": datetime.now(timezone.utc).isoformat(), "revoked_by": context.user_id}).eq("id", grant_id).execute()
    rbac.clear_context_cache(str(row.get("support_user_id")))
    rbac.audit(context, "support.revoke", "support_access_grant", grant_id, row.get("customer_id"))
    return {"success": True}


@router.get("/support-grants")
def list_support_grants(request: Request):
    context = rbac.get_access_context(request)
    query = supabase.table("support_access_grants").select("*")
    if "support_agent" in context.role_keys and not context.is_global:
        query = query.eq("support_user_id", context.user_id)
    elif not context.is_global:
        if not context.customer_ids or "support.approve_access" not in context.permissions():
            return {"grants": []}
        query = query.in_("customer_id", sorted(context.customer_ids))
    return {"grants": query.order("created_at", desc=True).limit(500).execute().data or []}


@router.post("/receipt-assignments", status_code=201)
def assign_receipt(body: ReceiptAssignmentCreate, request: Request):
    context = rbac.get_access_context(request)
    _require_assignment_manager(context)
    _validate_receipt_assignee(body.assignee_user_id)
    receipt = rbac.get_receipt_for_access(context, body.receipt_id, "receipts.update")
    permissions = _validate_permissions(body.permissions)
    permitted = {"receipts.read", "receipts.update", "receipts.correct_items", "receipts.view_image"}
    if any(value not in permitted for value in permissions):
        raise HTTPException(status_code=400, detail="Receipt assignments may contain receipt permissions only.")
    payload = {**body.model_dump(mode="json"), "permissions": permissions, "assigned_by": context.user_id}
    result = supabase.table("receipt_assignments").insert(payload).execute()
    rbac.clear_context_cache(body.assignee_user_id)
    created = (result.data or [payload])[0]
    rbac.audit(context, "receipt.assign", "receipt", body.receipt_id, receipt.get("customer_id"), metadata={"assignee_user_id": body.assignee_user_id, "permissions": permissions})
    return created


@router.post("/receipt-assignments/bulk", status_code=201)
def assign_receipts_bulk(body: BulkReceiptAssignmentCreate, request: Request):
    """Assign an authorized receipt set selected explicitly or by calendar filters."""
    context = rbac.get_access_context(request)
    _require_assignment_manager(context)
    _validate_receipt_assignee(body.assignee_user_id)
    permissions = _validate_permissions(body.permissions)
    permitted = {"receipts.read", "receipts.update", "receipts.correct_items", "receipts.view_image"}
    if any(value not in permitted for value in permissions):
        raise HTTPException(status_code=400, detail="Receipt assignments may contain receipt permissions only.")

    receipts = rbac.list_accessible_receipts(context, permission="receipts.update", limit=5000)
    explicit_ids = {int(value) for value in body.receipt_ids}
    start = database.parse_purchase_date(body.from_date) if body.from_date else None
    end = database.parse_purchase_date(body.to_date) if body.to_date else None
    if bool(body.from_date) != bool(body.to_date) or (body.from_date and (not start or not end or start > end)):
        raise HTTPException(status_code=400, detail="Send a valid from_date and to_date range.")
    has_filter = bool(explicit_ids or body.all_accessible or start or body.year)
    if not has_filter:
        raise HTTPException(status_code=400, detail="Select receipts, a date range, month, year, or all receipts.")

    selected: list[dict] = []
    for receipt in receipts:
        receipt_id = int(receipt.get("id"))
        purchased = database.parse_purchase_date(receipt.get("date") or receipt.get("created_at"))
        matches = body.all_accessible or receipt_id in explicit_ids
        if start and end and purchased and start <= purchased <= end:
            matches = True
        if body.year and purchased and purchased.year == body.year and (not body.month or purchased.month == body.month):
            matches = True
        if matches:
            selected.append(receipt)
    if not selected:
        raise HTTPException(status_code=404, detail="No authorized receipts matched this assignment filter.")

    payloads = [{
        "assignee_user_id": body.assignee_user_id,
        "receipt_id": receipt["id"],
        "permissions": permissions,
        "assigned_by": context.user_id,
        "expires_at": body.expires_at.isoformat() if body.expires_at else None,
        "revoked_at": None,
    } for receipt in selected]
    assignment_rows: list[dict] = []
    for start_index in range(0, len(payloads), 250):
        batch = payloads[start_index:start_index + 250]
        result = supabase.table("receipt_assignments").upsert(batch, on_conflict="assignee_user_id,receipt_id").execute()
        assignment_rows.extend(result.data or [])
    rbac.clear_context_cache(body.assignee_user_id)
    selected_ids = [int(receipt["id"]) for receipt in selected]
    rbac.audit(context, "receipt.assignment.bulk", "receipt_set", customer_id=rbac.primary_customer_id(context), metadata={
        "assignee_user_id": body.assignee_user_id,
        "receipt_count": len(selected_ids),
        "receipt_ids": selected_ids[:200],
        "all_accessible": body.all_accessible,
        "from_date": body.from_date,
        "to_date": body.to_date,
        "year": body.year,
        "month": body.month,
    })
    return {"success": True, "assigned": len(selected_ids), "receipt_ids": selected_ids, "assignments": assignment_rows}


@router.delete("/receipt-assignments/{assignment_id}")
def revoke_receipt_assignment(assignment_id: str, request: Request):
    context = rbac.get_access_context(request)
    rows = supabase.table("receipt_assignments").select("*").eq("id", assignment_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Receipt assignment not found.")
    row = rows[0]
    receipt = rbac.get_receipt_for_access(context, int(row["receipt_id"]), "receipts.update")
    supabase.table("receipt_assignments").update({"revoked_at": datetime.now(timezone.utc).isoformat()}).eq("id", assignment_id).execute()
    rbac.clear_context_cache(str(row.get("assignee_user_id")))
    rbac.audit(context, "receipt.assignment.revoke", "receipt", row.get("receipt_id"), receipt.get("customer_id"))
    return {"success": True}


@router.get("/receipt-assignments")
def list_receipt_assignments(request: Request):
    context = rbac.get_access_context(request)
    query = supabase.table("receipt_assignments").select("*")
    if not context.is_global:
        visible_receipt_ids = {str(row.get("id")) for row in rbac.list_accessible_receipts(context, limit=5000)}
        if not visible_receipt_ids:
            return {"assignments": []}
        query = query.in_("receipt_id", sorted(visible_receipt_ids))
    rows = query.order("created_at", desc=True).limit(1000).execute().data or []
    return {"assignments": rows}


@router.get("/overview")
def operations_overview(request: Request):
    context = rbac.get_access_context(request)
    receipts = rbac.list_accessible_receipts(context, limit=5000)
    total_spend = round(sum(float(row.get("total") or 0) for row in receipts), 2)
    open_assignments = 0
    active_support_grants = 0
    try:
        assignment_rows = list_receipt_assignments(request).get("assignments", [])
        open_assignments = sum(1 for row in assignment_rows if rbac._active(row))
        grant_rows = list_support_grants(request).get("grants", [])
        active_support_grants = sum(1 for row in grant_rows if rbac._active(row))
    except HTTPException:
        pass
    return {
        "receipts": len(receipts),
        "total_spend": total_spend,
        "customers": len(context.customer_ids) if not context.is_global else None,
        "open_assignments": open_assignments,
        "active_support_grants": active_support_grants,
        "roles": sorted(context.role_keys),
    }


@router.get("/token-usage")
def token_usage_summary(
    request: Request,
    period: str = Query(default="month", pattern="^(day|week|month|year)$"),
    limit: int = Query(default=5000, ge=1, le=10000),
):
    """Operations dashboard AI usage summary.

    Reads only the current operator's authorized customer scope unless the
    operator has global data access. Missing table is reported cleanly so the
    scanner continues working before the migration is installed.
    """
    context = rbac.get_access_context(request)
    if context.is_global:
        rbac.require_permission(context, "analytics.read_global")
    else:
        customer_id = rbac.primary_customer_id(context)
        rbac.require_permission(context, "analytics.read_customer", customer_id)
        if not context.customer_ids:
            return {"available": True, "period": period, "summary": _sum_token_rows([]), "series": [], "by_operation": [], "by_model": [], "by_file_type": [], "by_optimization": [], "recent": []}

    since = datetime.now(timezone.utc) - timedelta(days=TOKEN_PERIOD_DAYS[period])
    query = supabase.table("ai_token_usage").select("*").gte("created_at", since.isoformat()).order("created_at", desc=True).limit(limit)
    if not context.is_global:
        query = query.in_("customer_id", sorted(context.customer_ids))

    try:
        rows = query.execute().data or []
    except Exception as error:
        print(f"[token_usage] Summary unavailable: {error}")
        return {
            "available": False,
            "period": period,
            "message": "Token usage tracking is not configured yet.",
            "summary": _sum_token_rows([]),
            "series": [],
            "by_operation": [],
            "by_model": [],
            "by_file_type": [],
            "by_optimization": [],
            "recent": [],
        }

    buckets: dict[str, list[dict]] = {}
    by_operation: dict[str, list[dict]] = {}
    by_model: dict[str, list[dict]] = {}
    by_file_type: dict[str, list[dict]] = {}
    by_optimization: dict[str, list[dict]] = {}
    for row in rows:
        created = _parse_utc(row.get("created_at")) or datetime.now(timezone.utc)
        buckets.setdefault(_token_bucket(created, period), []).append(row)
        by_operation.setdefault(str(row.get("operation") or "unknown"), []).append(row)
        by_model.setdefault(str(row.get("model") or "unknown"), []).append(row)
        by_file_type.setdefault(str(row.get("file_type") or "unknown"), []).append(row)
        optimization = str(row.get("optimization") or ("optimized" if row.get("optimized") else "not_optimized"))
        by_optimization.setdefault(optimization, []).append(row)

    def ranked(mapping: dict[str, list[dict]]) -> list[dict[str, Any]]:
        return sorted(
            [{"key": key, **_sum_token_rows(values)} for key, values in mapping.items()],
            key=lambda item: item["total_tokens"],
            reverse=True,
        )[:10]

    summary = _sum_token_rows(rows)
    optimized_events = [row for row in rows if row.get("optimized")]
    return {
        "available": True,
        "period": period,
        "since": since.isoformat(),
        "summary": {**summary, "optimized_events": len(optimized_events)},
        "series": [{"label": key, **_sum_token_rows(values)} for key, values in reversed(list(buckets.items()))],
        "by_operation": ranked(by_operation),
        "by_model": ranked(by_model),
        "by_file_type": ranked(by_file_type),
        "by_optimization": ranked(by_optimization),
        "recent": rows[:25],
    }


def _issue_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize recent issue rows for operations dashboard cards."""
    severity_counts = {"error": 0, "warning": 0, "info": 0}
    sources: set[str] = set()
    for event in events:
        severity = str(event.get("severity") or "info").lower()
        severity_counts[severity if severity in severity_counts else "info"] += 1
        if event.get("source"):
            sources.add(str(event["source"]))
    return {
        "total": len(events),
        "errors": severity_counts["error"],
        "warnings": severity_counts["warning"],
        "info": severity_counts["info"],
        "sources": len(sources),
        "latest": events[0].get("created_at") if events else None,
    }


@router.get("/error-events")
def error_events(
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    severity: str | None = Query(default=None),
):
    """Return recent backend issues for the operations dashboard."""
    normalized_severity = severity.lower() if severity else None
    if normalized_severity and normalized_severity not in {"error", "warning", "info"}:
        raise HTTPException(status_code=400, detail="severity must be one of: error, warning, info")
    context = rbac.get_access_context(request)
    if context.is_global:
        rbac.require_permission(context, "audit.read")
        query = supabase.table("app_error_events").select("*")
    else:
        customer_id = rbac.primary_customer_id(context)
        rbac.require_permission(context, "audit.read", customer_id)
        if not context.customer_ids:
            return {"available": True, "summary": _issue_summary([]), "events": []}
        query = supabase.table("app_error_events").select("*").in_("customer_id", sorted(context.customer_ids))
    if normalized_severity:
        query = query.eq("severity", normalized_severity)
    try:
        events = query.order("created_at", desc=True).limit(limit).execute().data or []
        return {
            "available": True,
            "summary": _issue_summary(events),
            "events": events,
        }
    except Exception as error:
        print(f"[error_events] Summary unavailable: {error}")
        return {
            "available": False,
            "message": "Issue tracking is not configured yet.",
            "summary": _issue_summary([]),
            "events": [],
        }


@router.get("/audit")
def read_audit(request: Request, customer_id: str | None = None, limit: int = 100):
    context = rbac.get_access_context(request)
    if not context.is_global and not customer_id:
        customer_id = rbac.primary_customer_id(context)
        if not customer_id:
            raise HTTPException(status_code=403, detail="A customer scope is required.")
    if customer_id and not context.is_global and customer_id not in context.customer_ids:
        raise HTTPException(status_code=403, detail="You cannot view this audit log.")
    rbac.require_permission(context, "audit.read", customer_id)
    query = supabase.table("access_audit_log").select("*")
    if customer_id:
        query = query.eq("customer_id", customer_id)
    result = query.order("created_at", desc=True).limit(max(1, min(limit, 500))).execute()
    return {"events": result.data or []}
