"""Authorization regression tests; no live database calls are made."""

from datetime import datetime, timedelta, timezone
import sys
import types


dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv)
anthropic = types.ModuleType("anthropic")
anthropic.Anthropic = lambda api_key=None: None
sys.modules.setdefault("anthropic", anthropic)
supabase_module = types.ModuleType("supabase")
supabase_module.Client = object
supabase_module.create_client = lambda *args, **kwargs: None
sys.modules.setdefault("supabase", supabase_module)

from app.services.rbac import AccessContext, RoleAssignment, can_access_receipt, require_permission
from app.routes.rbac import _resolve_reporting_range, _token_bucket
from fastapi import HTTPException


RECEIPT_A = {"id": 10, "user_id": "alice", "customer_id": "customer-a"}
RECEIPT_B = {"id": 20, "user_id": "bob", "customer_id": "customer-b"}


def context(user_id, role, customer_id=None, grants=None, assignments=None):
    return AccessContext(
        user_id=user_id,
        roles=[RoleAssignment(role, customer_id)],
        grants=grants or [],
        receipt_assignments=assignments or [],
    )


def test_customer_user_is_strictly_owner_scoped():
    user = context("alice", "customer_user", "customer-a")
    assert can_access_receipt(user, RECEIPT_A, "receipts.read")
    assert not can_access_receipt(user, {**RECEIPT_A, "user_id": "another-user"}, "receipts.read")
    assert not can_access_receipt(user, RECEIPT_B, "receipts.read")


def test_customer_owner_is_customer_scoped():
    owner = context("owner", "customer_owner", "customer-a")
    assert can_access_receipt(owner, RECEIPT_A, "receipts.correct_items")
    assert not can_access_receipt(owner, RECEIPT_B, "receipts.correct_items")


def test_global_roles_can_read_all_customers_but_auditor_cannot_edit():
    master = context("master", "master_user")
    auditor = context("audit", "auditor", "customer-a")
    assert can_access_receipt(master, RECEIPT_A, "receipts.read")
    assert can_access_receipt(master, RECEIPT_B, "receipts.read")
    assert can_access_receipt(auditor, RECEIPT_A, "receipts.read")
    assert not can_access_receipt(auditor, RECEIPT_A, "receipts.correct_items")


def test_support_requires_role_active_grant_and_exact_scope():
    grant = {
        "customer_id": "customer-a",
        "permissions": ["receipts.read"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    support = context("support", "support_agent", grants=[grant])
    ordinary = context("ordinary", "customer_user", grants=[grant])
    assert can_access_receipt(support, RECEIPT_A, "receipts.read")
    assert not can_access_receipt(support, RECEIPT_A, "receipts.correct_items")
    assert not can_access_receipt(support, RECEIPT_B, "receipts.read")
    assert not can_access_receipt(ordinary, RECEIPT_A, "receipts.read")


def test_expired_support_grant_is_denied():
    grant = {
        "customer_id": "customer-a",
        "permissions": ["receipts.read"],
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    assert not can_access_receipt(context("support", "support_agent", grants=[grant]), RECEIPT_A, "receipts.read")


def test_receipt_scoped_support_grant_does_not_expand_to_customer():
    grant = {
        "customer_id": "customer-a",
        "receipt_id": 10,
        "permissions": ["receipts.read"],
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
    }
    support = context("support", "support_agent", grants=[grant])
    assert can_access_receipt(support, RECEIPT_A, "receipts.read")
    assert not can_access_receipt(support, {**RECEIPT_A, "id": 11}, "receipts.read")


def test_receipt_assignment_is_exact_and_permission_limited():
    editor = context("editor", "receipt_editor", assignments=[{
        "receipt_id": 10,
        "permissions": ["receipts.read", "receipts.correct_items"],
    }])
    assert can_access_receipt(editor, RECEIPT_A, "receipts.correct_items")
    assert not can_access_receipt(editor, RECEIPT_A, "receipts.delete")
    assert not can_access_receipt(editor, RECEIPT_B, "receipts.read")


def test_database_permission_mapping_can_remove_static_permission():
    user = AccessContext(
        user_id="alice",
        roles=[RoleAssignment("customer_user", "customer-a")],
        role_permissions={"customer_user": {"receipts.read"}},
    )
    assert can_access_receipt(user, RECEIPT_A, "receipts.read")
    assert not can_access_receipt(user, RECEIPT_A, "receipts.delete")


def test_customer_owner_and_master_user_management_permissions():
    owner = context("owner", "customer_owner", "customer-a")
    master = context("master", "master_user")
    require_permission(owner, "users.manage", "customer-a")
    require_permission(master, "users.manage")


def test_customer_scoped_auditor_has_read_only_audit_permission():
    auditor = context("audit", "auditor", "customer-a")
    require_permission(auditor, "audit.read", "customer-a")
    assert not can_access_receipt(auditor, RECEIPT_A, "receipts.update")


def test_reporting_presets_use_calendar_boundaries():
    now = datetime(2026, 7, 23, 15, 30, tzinfo=timezone.utc)
    assert _resolve_reporting_range("day", now=now)["from_date"] == "2026-07-23"
    assert _resolve_reporting_range("week", now=now)["from_date"] == "2026-07-20"
    assert _resolve_reporting_range("month", now=now)["from_date"] == "2026-07-01"
    year = _resolve_reporting_range("year", now=now)
    assert year["from_date"] == "2026-01-01"
    assert year["granularity"] == "month"


def test_reporting_custom_range_is_inclusive_and_can_cross_years():
    report = _resolve_reporting_range(
        "month",
        "2024-11-15",
        "2026-02-10",
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert report["label"] == "custom"
    assert report["from_date"] == "2024-11-15"
    assert report["to_date"] == "2026-02-10"
    assert report["granularity"] == "month"


def test_hourly_reporting_labels_include_the_date_for_multi_day_ranges():
    created = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    assert _token_bucket(created, "hour") == "09:00"
    assert _token_bucket(created, "hour", include_date=True) == "Jan 01 09:00"


def test_reporting_range_rejects_incomplete_or_reversed_dates():
    for start, end in (("2026-01-01", None), ("2026-02-01", "2026-01-01")):
        try:
            _resolve_reporting_range("month", start, end)
            raise AssertionError("accepted an invalid reporting range")
        except HTTPException as error:
            assert error.status_code == 400
