"""Administrative RBAC endpoints. All authorization is enforced server-side."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import supabase
from app.services import rbac


router = APIRouter(prefix="/rbac", tags=["access-control"])


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
    return {"roles": result.data or []}


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
    if body.role_key not in {"platform_admin", "master_user", "support_agent"} and not body.customer_id:
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


@router.get("/audit")
def read_audit(request: Request, customer_id: str | None = None, limit: int = 100):
    context = rbac.get_access_context(request)
    if customer_id and not _can_manage_customer(context, customer_id):
        raise HTTPException(status_code=403, detail="You cannot view this audit log.")
    rbac.require_permission(context, "audit.read", customer_id)
    query = supabase.table("access_audit_log").select("*")
    if customer_id:
        query = query.eq("customer_id", customer_id)
    result = query.order("created_at", desc=True).limit(max(1, min(limit, 500))).execute()
    return {"events": result.data or []}
