"""Administrative RBAC endpoints. All authorization is enforced server-side."""

from datetime import datetime, timezone
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import supabase
from app.services import rbac


router = APIRouter(prefix="/rbac", tags=["access-control"])
CUSTOMER_REQUIRED_ROLES = {"customer_owner", "customer_user", "auditor", "service_account"}


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
        query = query.in_("customer_id", sorted(context.customer_ids))
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
