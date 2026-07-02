"""Launch-critical ownership, guest isolation, and receipt-contract checks."""

from pathlib import Path
from types import SimpleNamespace
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

from fastapi import HTTPException
from app.routes import receipts
from app.services import database


class FakeQuery:
    def __init__(self, rows, calls):
        self.rows = rows
        self.calls = calls

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return method

    def execute(self):
        self.calls.append(("execute", (), {}))
        return SimpleNamespace(data=self.rows)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def table(self, name):
        self.calls.append(("table", (name,), {}))
        return FakeQuery(self.rows, self.calls)


def test_guest_session_rejects_shared_defaults():
    for value in (None, "", "guest", "default", "short"):
        try:
            receipts.validate_guest_session_id(value)
            raise AssertionError(f"accepted unsafe guest session: {value}")
        except HTTPException as error:
            assert error.status_code == 401
    assert receipts.validate_guest_session_id("guest_1719999999999_ab12cd34") == "guest_1719999999999_ab12cd34"


def test_agent_guest_session_uses_same_strict_contract():
    from app.routes import agent_route

    for value in (None, "", "guest", "default", "short", "guest/session/unsafe"):
        try:
            agent_route.validate_guest_session_id(value)
            raise AssertionError(f"accepted unsafe agent guest session: {value}")
        except HTTPException as error:
            assert error.status_code == 401
    assert agent_route.validate_guest_session_id("guest_1719999999999_ab12cd34") == "guest_1719999999999_ab12cd34"


def test_receipt_delete_refuses_unscoped_calls():
    original = database.supabase
    database.supabase = object()
    try:
        assert database.delete_receipt(42) == {}
    finally:
        database.supabase = original


def test_date_filter_is_owner_scoped_and_uses_purchase_date():
    fake = FakeSupabase([
        {"id": 1, "date": "06/15/26", "created_at": "2026-07-01T00:00:00Z"},
        {"id": 2, "date": "05/10/26", "created_at": "2026-06-01T00:00:00Z"},
    ])
    original = database.supabase
    database.supabase = fake
    try:
        rows = database.get_receipts_by_date("2026-06-01", "2026-06-30", user_id="user-1")
    finally:
        database.supabase = original
    assert [row["id"] for row in rows] == [1]
    assert any(call[0] == "eq" and call[1] == ("user_id", "user-1") for call in fake.calls)


def test_unscoped_legacy_query_router_is_not_registered():
    main_source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "include_router(queries.router)" not in main_source


def test_account_deletion_fails_closed_without_service_role():
    source = (Path(__file__).parent / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
    assert "SUPABASE_SERVICE_ROLE_KEY" in source
    assert "Account deletion is temporarily unavailable" in source
    assert "Account data could not be fully deleted" in source


def test_scan_contract_includes_labeled_receipt_identifiers():
    source = (Path(__file__).parent / "app" / "services" / "claude.py").read_text(encoding="utf-8")
    for field in ("transaction_number", "receipt_number", "invoice_number", "order_number"):
        assert field in source


if __name__ == "__main__":
    tests = [
        test_guest_session_rejects_shared_defaults,
        test_agent_guest_session_uses_same_strict_contract,
        test_receipt_delete_refuses_unscoped_calls,
        test_date_filter_is_owner_scoped_and_uses_purchase_date,
        test_unscoped_legacy_query_router_is_not_registered,
        test_account_deletion_fails_closed_without_service_role,
        test_scan_contract_includes_labeled_receipt_identifiers,
    ]
    for test in tests:
        test()
    print(f"Launch readiness checks passed: {len(tests)}")
