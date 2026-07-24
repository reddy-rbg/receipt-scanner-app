"""Backend-enforced RBAC plus customer/receipt scope authorization."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from app.config import supabase
from app.services.app_logger import get_logger

logger = get_logger(__name__)

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "platform_admin": {"*"},
    "master_user": {
        "users.read", "users.manage", "receipts.read", "receipts.update", "receipts.delete",
        "receipts.correct_items", "receipts.view_image", "analytics.read_customer",
        "analytics.read_global", "reports.export", "support.approve_access", "audit.read",
    },
    "customer_owner": {
        "users.read", "users.manage", "receipts.upload", "receipts.read", "receipts.update",
        "receipts.delete", "receipts.correct_items", "receipts.view_image",
        "analytics.read_own", "analytics.read_customer", "support.approve_access", "audit.read",
    },
    "customer_user": {
        "receipts.upload", "receipts.read", "receipts.update", "receipts.delete",
        "receipts.correct_items", "receipts.view_image", "analytics.read_own",
    },
    "support_agent": {"support.request_access"},
    "receipt_editor": {"receipts.read", "receipts.update", "receipts.correct_items"},
    "auditor": {"receipts.read", "audit.read"},
    "service_account": {"receipts.upload", "receipts.read", "receipts.reprocess"},
}

GLOBAL_DATA_ROLES = {"platform_admin", "master_user"}
OWNER_PERMISSIONS = ROLE_PERMISSIONS["customer_user"]
_CONTEXT_CACHE: dict[str, tuple[float, "AccessContext"]] = {}


@dataclass(frozen=True)
class RoleAssignment:
    role_key: str
    customer_id: str | None = None


@dataclass
class AccessContext:
    user_id: str
    email: str = ""
    roles: list[RoleAssignment] = field(default_factory=list)
    grants: list[dict] = field(default_factory=list)
    receipt_assignments: list[dict] = field(default_factory=list)
    role_permissions: dict[str, set[str]] = field(default_factory=dict)
    rbac_available: bool = True

    @property
    def role_keys(self) -> set[str]:
        return {role.role_key for role in self.roles}

    @property
    def customer_ids(self) -> set[str]:
        return {str(role.customer_id) for role in self.roles if role.customer_id}

    @property
    def is_global(self) -> bool:
        return bool(self.role_keys & GLOBAL_DATA_ROLES)

    def permissions(self) -> set[str]:
        result: set[str] = set()
        for role in self.role_keys:
            result |= self.role_permissions.get(role, ROLE_PERMISSIONS.get(role, set()))
        return result

    def role_allows(self, role_key: str, permission: str) -> bool:
        permissions = self.role_permissions.get(role_key, ROLE_PERMISSIONS.get(role_key, set()))
        return "*" in permissions or permission in permissions


def _active(row: dict) -> bool:
    if row.get("revoked_at"):
        return False
    expires = row.get("expires_at")
    if not expires:
        return True
    try:
        parsed = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        return parsed > datetime.now(timezone.utc)
    except Exception:
        return False


def _token_user(request: Request) -> tuple[str, str]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    token = auth[7:].strip()
    if not token or token == "guest":
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        response = supabase.auth.get_user(token)
        if response and response.user:
            return str(response.user.id), str(response.user.email or "")
    except Exception as error:
        logger.warning("RBAC token validation failed: %s", error)
    raise HTTPException(status_code=401, detail="Invalid or expired session.")


def _load_context(user_id: str, email: str = "") -> AccessContext:
    cached = _CONTEXT_CACHE.get(user_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    bootstrap_ids = {value.strip() for value in os.getenv("RBAC_BOOTSTRAP_ADMIN_USER_IDS", "").split(",") if value.strip()}
    roles: list[RoleAssignment] = []
    grants: list[dict] = []
    assignments: list[dict] = []
    permission_map: dict[str, set[str]] = {}
    available = True
    try:
        rows = supabase.table("rbac_user_roles").select("role_key,customer_id,active").eq("user_id", user_id).eq("active", True).execute().data or []
        roles = [RoleAssignment(str(row.get("role_key")), str(row.get("customer_id")) if row.get("customer_id") else None) for row in rows]
        role_keys = [role.role_key for role in roles]
        if role_keys:
            permission_rows = supabase.table("rbac_role_permissions").select("role_key,permission_key").in_("role_key", role_keys).execute().data or []
            for row in permission_rows:
                permission_map.setdefault(str(row.get("role_key")), set()).add(str(row.get("permission_key")))
        grants = [row for row in (
            supabase.table("support_access_grants")
            .select("id,customer_id,receipt_id,permissions,case_id,reason,expires_at,revoked_at")
            .eq("support_user_id", user_id).execute().data or []
        ) if _active(row)]
        assignments = [row for row in (
            supabase.table("receipt_assignments")
            .select("id,receipt_id,permissions,expires_at,revoked_at")
            .eq("assignee_user_id", user_id).execute().data or []
        ) if _active(row)]
    except Exception as error:
        # Safe rolling-deploy behavior: before the migration, preserve only the
        # existing user's own-data permissions. Never grant cross-user access.
        logger.warning("RBAC scoped tables unavailable; using owner-only fallback: %s", error)
        roles = [RoleAssignment("customer_user", None)]
        available = False

    if user_id in bootstrap_ids and "platform_admin" not in {role.role_key for role in roles}:
        roles.append(RoleAssignment("platform_admin", None))
    if not roles:
        roles = [RoleAssignment("customer_user", None)]
    context = AccessContext(user_id, email, roles, grants, assignments, permission_map, available)
    _CONTEXT_CACHE[user_id] = (time.monotonic() + 30, context)
    if len(_CONTEXT_CACHE) > 500:
        _CONTEXT_CACHE.clear()
    return context


def get_access_context(request: Request) -> AccessContext:
    user_id, email = _token_user(request)
    return _load_context(user_id, email)


def clear_context_cache(user_id: str | None = None) -> None:
    if user_id:
        _CONTEXT_CACHE.pop(user_id, None)
    else:
        _CONTEXT_CACHE.clear()


def primary_customer_id(context: AccessContext) -> str | None:
    for preferred in ("customer_owner", "customer_user", "receipt_editor", "service_account"):
        for role in context.roles:
            if role.role_key == preferred and role.customer_id:
                return role.customer_id
    return next(iter(context.customer_ids), None)


def role_has_permission(role_key: str, permission: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(role_key, set())
    return "*" in permissions or permission in permissions


def require_permission(context: AccessContext, permission: str, customer_id: str | None = None) -> None:
    for role in context.roles:
        if not context.role_allows(role.role_key, permission):
            continue
        if role.role_key in GLOBAL_DATA_ROLES:
            return
        if customer_id and role.customer_id == customer_id:
            return
        if not customer_id:
            return
    raise HTTPException(status_code=403, detail="You do not have permission for this action.")


def _grant_allows(grant: dict, receipt: dict, permission: str) -> bool:
    if not _active(grant):
        return False
    permissions = set(grant.get("permissions") or [])
    if permission not in permissions and "*" not in permissions:
        return False
    receipt_id = grant.get("receipt_id")
    customer_id = grant.get("customer_id")
    if receipt_id is not None:
        return str(receipt_id) == str(receipt.get("id"))
    return bool(customer_id and str(customer_id) == str(receipt.get("customer_id")))


def can_access_receipt(context: AccessContext, receipt: dict, permission: str) -> bool:
    if str(receipt.get("user_id") or "") == context.user_id and any(
        context.role_allows(role.role_key, permission) for role in context.roles
    ):
        return True
    customer_id = str(receipt.get("customer_id")) if receipt.get("customer_id") else None
    for role in context.roles:
        if not context.role_allows(role.role_key, permission):
            continue
        if role.role_key in GLOBAL_DATA_ROLES:
            return True
        if customer_id and role.customer_id == customer_id and role.role_key in {"customer_owner", "receipt_editor", "auditor", "service_account"}:
            return True
    if "support_agent" in context.role_keys and any(_grant_allows(grant, receipt, permission) for grant in context.grants):
        return True
    for assignment in context.receipt_assignments:
        if not _active(assignment):
            continue
        permissions = set(assignment.get("permissions") or [])
        if str(assignment.get("receipt_id")) == str(receipt.get("id")) and (permission in permissions or "*" in permissions):
            return True
    return False


def get_receipt_for_access(context: AccessContext, receipt_id: int, permission: str) -> dict:
    try:
        rows = supabase.table("receipts").select("*").eq("id", receipt_id).limit(1).execute().data or []
    except Exception as error:
        logger.warning("RBAC receipt lookup failed: %s", error)
        raise HTTPException(status_code=503, detail="Receipt data is temporarily unavailable.")
    if not rows or not can_access_receipt(context, rows[0], permission):
        # Do not reveal whether another customer's receipt exists.
        raise HTTPException(status_code=404, detail="Receipt not found.")
    return rows[0]


def list_accessible_receipts(context: AccessContext, permission: str = "receipts.read", limit: int = 1000) -> list[dict]:
    limit = max(1, min(limit, 5000))
    queries = []
    base = supabase.table("receipts").select("*")
    if context.is_global and any(context.role_allows(role, permission) for role in context.role_keys):
        queries.append(base.order("created_at", desc=True).limit(limit))
    else:
        queries.append(supabase.table("receipts").select("*").eq("user_id", context.user_id).order("created_at", desc=True).limit(limit))
        scoped_customers = {
            role.customer_id for role in context.roles
            if role.customer_id and context.role_allows(role.role_key, permission) and role.role_key != "customer_user"
        }
        if "support_agent" in context.role_keys:
            scoped_customers |= {str(grant.get("customer_id")) for grant in context.grants if not grant.get("receipt_id") and grant.get("customer_id") and (permission in set(grant.get("permissions") or []) or "*" in set(grant.get("permissions") or []))}
        if scoped_customers:
            queries.append(supabase.table("receipts").select("*").in_("customer_id", list(scoped_customers)).order("created_at", desc=True).limit(limit))
        grant_receipts = [grant.get("receipt_id") for grant in context.grants] if "support_agent" in context.role_keys else []
        receipt_ids = {
            int(value) for value in grant_receipts + [row.get("receipt_id") for row in context.receipt_assignments]
            if value is not None
        }
        if receipt_ids:
            queries.append(supabase.table("receipts").select("*").in_("id", list(receipt_ids)).order("created_at", desc=True).limit(limit))

    rows: list[dict] = []
    seen = set()
    try:
        for query in queries:
            for receipt in query.execute().data or []:
                receipt_id = receipt.get("id")
                if receipt_id in seen or not can_access_receipt(context, receipt, permission):
                    continue
                seen.add(receipt_id)
                rows.append(receipt)
    except Exception as error:
        logger.warning("RBAC accessible receipt query failed: %s", error)
        raise HTTPException(status_code=503, detail="Receipt data is temporarily unavailable.")
    rows.sort(key=lambda row: str(row.get("created_at") or row.get("date") or ""), reverse=True)
    return rows[:limit]


def audit(context: AccessContext, action: str, resource_type: str, resource_id: Any = None, customer_id: str | None = None, reason: str | None = None, metadata: dict | None = None) -> None:
    try:
        supabase.table("access_audit_log").insert({
            "actor_user_id": context.user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id is not None else None,
            "customer_id": customer_id,
            "reason": reason,
            "metadata": metadata or {},
        }).execute()
    except Exception as error:
        logger.warning("RBAC audit write unavailable: %s", error)
