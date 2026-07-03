"""Password recovery contract checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent
AUTH = (ROOT / "app" / "routes" / "auth.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.py").read_text(encoding="utf-8")
PAGE = (ROOT / "reset_password" / "index.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "reset_password" / "reset.js").read_text(encoding="utf-8")


def test_recovery_email_always_has_a_public_reset_target():
    assert 'reset_redirect_url = f"{str(request.base_url).rstrip(\'/\')}/reset-password/"' in AUTH
    assert 'payload_data["redirect_to"] = reset_redirect_url' in AUTH


def test_reset_endpoint_verifies_token_before_password_update():
    verification = AUTH.index("database.supabase.auth.get_user(token)")
    update = AUTH.index('auth.admin.update_user_by_id', verification)
    assert verification < update
    assert "validate_password(req.new_password)" in AUTH


def test_reset_page_is_hosted_and_removes_token_from_address_bar():
    assert '"/reset-password"' in MAIN
    assert "Choose a new password" in PAGE
    assert "history.replaceState" in SCRIPT
    assert "access_token:accessToken" in SCRIPT
