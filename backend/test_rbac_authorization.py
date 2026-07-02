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

from app.services.rbac import AccessContext, RoleAssignment, can_access_receipt


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
