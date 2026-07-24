"""Static and backend contract checks for the separate operations console."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "ops_dashboard" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "ops_dashboard" / "app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
RBAC_ROUTES = (ROOT / "app" / "routes" / "rbac.py").read_text(encoding="utf-8")
RECEIPT_ROUTES = (ROOT / "app" / "routes" / "receipts.py").read_text(encoding="utf-8")
AUTH_ROUTES = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "app" / "config.py").read_text(encoding="utf-8")


def test_operations_console_is_served_separately():
    assert 'app.mount(' in MAIN
    assert '"/ops"' in MAIN
    assert "Operations console" in INDEX


def test_customer_only_accounts_are_not_operator_accounts():
    assert "operatorRoles" in APP
    assert "customer_user" not in APP.split("operatorRoles=new Set(", 1)[1].split("]", 1)[0]
    assert "has no operations-console role" in APP


def test_dashboard_covers_all_operator_workflows():
    for route in (
        "/rbac/users", "/rbac/customers", "/rbac/user-roles",
        "/rbac/support-grants", "/rbac/receipt-assignments", "/rbac/audit",
    ):
        assert route in APP
    for page in ("Receipts", "Assignments", "Support access", "Users", "Customers", "Roles & permissions", "Audit log"):
        assert page in APP


def test_dashboard_directory_endpoints_are_backend_authorized():
    assert 'rbac.require_permission(context, "users.read")' in RBAC_ROUTES
    assert 'rbac.require_permission(context, "users.manage", body.customer_id)' in RBAC_ROUTES
    assert "You cannot deactivate your own account" in RBAC_ROUTES


def test_receipt_editor_updates_use_central_receipt_authorization():
    assert 'get_receipt_for_access(access, receipt_id, "receipts.update")' in RECEIPT_ROUTES
    assert 'get_receipt_for_access(access, receipt_id, "receipts.correct_items")' in RECEIPT_ROUTES


def test_support_access_is_case_based_and_self_approval_is_blocked():
    assert "Support users cannot approve their own access" in RBAC_ROUTES
    assert 'body.case_id or f"manual-' in RBAC_ROUTES
    assert "expires_at must be in the future" in RBAC_ROUTES


def test_operator_login_never_mutates_the_service_role_client():
    assert "def create_auth_client()" in CONFIG
    assert "create_auth_client().auth" in AUTH_ROUTES
    assert "database.supabase.auth.sign_in" not in AUTH_ROUTES


def test_receipt_editor_can_be_created_for_receipt_only_assignments():
    assert 'CUSTOMER_REQUIRED_ROLES = {"customer_owner", "customer_user", "auditor", "service_account"}' in RBAC_ROUTES
    assert "Receipt Editors may be created without a customer" in APP
    assert "operatorFormError" in APP


def test_bulk_assignment_supports_multiple_and_calendar_scopes():
    assert '/receipt-assignments/bulk' in RBAC_ROUTES
    assert 'all_accessible: bool = False' in RBAC_ROUTES
    assert 'from_date: str | None = None' in RBAC_ROUTES
    assert 'year: int | None' in RBAC_ROUTES
    assert 'range(0, len(payloads), 250)' in RBAC_ROUTES
    for label in ("Selected receipts", "Date range", "One month", "One year", "All accessible receipts"):
        assert label in APP


def test_token_and_issue_dashboards_have_calendar_and_diagnostic_filters():
    for field in ("from_date", "to_date", "operation", "model", "file_type"):
        assert field in RBAC_ROUTES
        assert field in APP
    for field in ("severity", "source", "error_type", "request_id"):
        assert field in RBAC_ROUTES
        assert field in APP
    for label in ("Today", "This week", "This month", "This year", "Apply filters", "Reset"):
        assert label in APP
    assert "AI_INPUT_COST_PER_MILLION_TOKENS" in APP
    assert "does not block or schedule AI work" in APP
    assert "Result limit reached" in APP
