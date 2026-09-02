"""Production configuration must fail closed without leaking secret values."""

from pathlib import Path

from app.production_config import validate_production_config


def valid_environment() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "ANTHROPIC_API_KEY": "secret-anthropic",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_KEY": "public-anon-key",
        "SUPABASE_SERVICE_KEY": "private-service-key",
        "PUBLIC_BASE_URL": "https://api.receiptai.app",
        "PASSWORD_RESET_REDIRECT_URL": "https://api.receiptai.app/reset-password/",
        "CORS_ALLOWED_ORIGINS": "https://receiptai.app",
        "SUPPORT_EMAIL": "support@receiptai.app",
        "LOG_JSON": "true",
    }


def test_valid_production_environment_is_ready():
    report = validate_production_config(valid_environment())
    assert report.production
    assert report.ready
    assert not report.errors


def test_staging_uses_the_same_fail_closed_checks_as_production():
    env = valid_environment()
    env["APP_ENV"] = "staging"
    report = validate_production_config(env)
    assert report.production
    assert report.ready

    env["ANTHROPIC_API_KEY"] = ""
    report = validate_production_config(env)
    assert not report.ready
    assert "ANTHROPIC_API_KEY must be configured" in report.errors


def test_missing_secrets_and_wildcard_cors_fail_closed():
    env = valid_environment()
    env["ANTHROPIC_API_KEY"] = ""
    env["CORS_ALLOWED_ORIGINS"] = "*"
    report = validate_production_config(env)
    assert not report.ready
    assert "ANTHROPIC_API_KEY must be configured" in report.errors
    assert "CORS_ALLOWED_ORIGINS cannot contain * in production" in report.errors


def test_http_urls_and_reused_service_key_are_rejected():
    env = valid_environment()
    env["PUBLIC_BASE_URL"] = "http://api.receiptai.app"
    env["SUPABASE_SERVICE_KEY"] = env["SUPABASE_KEY"]
    report = validate_production_config(env)
    assert not report.ready
    assert "PUBLIC_BASE_URL must use HTTPS in production" in report.errors
    assert "SUPABASE_SERVICE_KEY must differ from SUPABASE_KEY" in report.errors


def test_legacy_receipt_qa_cannot_use_global_service_role_mcp():
    source = (
        Path(__file__).parent / "app" / "services" / "claude.py"
    ).read_text(encoding="utf-8")
    function = source.split("def answer_question(", 1)[1].split(
        "def optimize_shopping_list(", 1
    )[0]
    assert "SUPABASE_SERVICE_KEY" not in function
    assert "mcp_servers" not in function
    assert "owner-scoped receipt list" in function


def test_railway_launches_with_fail_closed_production_validation():
    root = Path(__file__).parent
    railway = (root / "railway.json").read_text(encoding="utf-8")
    procfile = (root / "Procfile").read_text(encoding="utf-8")
    main_source = (root / "main.py").read_text(encoding="utf-8")

    assert '"startCommand": "APP_ENV=production ' in railway
    assert procfile.startswith("web: APP_ENV=production ")
    assert "status_code=200 if report.ready else 503" in main_source


if __name__ == "__main__":
    tests = [
        test_valid_production_environment_is_ready,
        test_staging_uses_the_same_fail_closed_checks_as_production,
        test_missing_secrets_and_wildcard_cors_fail_closed,
        test_http_urls_and_reused_service_key_are_rejected,
        test_legacy_receipt_qa_cannot_use_global_service_role_mcp,
        test_railway_launches_with_fail_closed_production_validation,
    ]
    for test in tests:
        test()
    print(f"Production configuration checks passed: {len(tests)}")
