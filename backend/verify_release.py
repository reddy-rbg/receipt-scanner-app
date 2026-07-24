"""ReceiptAI release gate.

Use --offline in CI for repository checks. Run without --offline from a
production-configured shell to verify the deployed service and Supabase schema.
Secret values are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from app.production_config import validate_production_config


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
REQUIRED_TABLES = (
    "receipts",
    "receipt_items",
    "receipt_item_aliases",
    "agent_conversation_messages",
    "agent_feedback",
    "customers",
    "rbac_roles",
    "rbac_permissions",
    "rbac_role_permissions",
    "rbac_user_roles",
    "support_access_grants",
    "receipt_assignments",
    "access_audit_log",
    "ai_token_usage",
    "app_error_events",
)
RECEIPT_IDENTIFIER_COLUMNS = (
    "transaction_number",
    "receipt_number",
    "invoice_number",
    "order_number",
)


class ReleaseChecks:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.passes: list[str] = []

    def check(self, condition: bool, success: str, failure: str) -> None:
        if condition:
            self.passes.append(success)
        else:
            self.failures.append(failure)


def request_json(url: str, headers: dict[str, str] | None = None) -> object:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ReceiptAI-release-verifier/1.0", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def request_page(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ReceiptAI-release-verifier/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def check_repository(checks: ReleaseChecks) -> None:
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines()
    dependencies = [line.strip() for line in requirements if line.strip() and not line.lstrip().startswith("#")]
    checks.check(
        bool(dependencies) and all("==" in line for line in dependencies),
        "Backend dependencies are exactly pinned",
        "Every backend runtime dependency must use an exact == version",
    )

    app_json = json.loads((ROOT / "mobile" / "app.json").read_text(encoding="utf-8"))
    app_version = app_json["expo"]["version"]
    backend_source = (BACKEND / "main.py").read_text(encoding="utf-8")
    checks.check(
        f'version="{app_version}"' in backend_source,
        f"Mobile and backend versions match ({app_version})",
        "Mobile app version and FastAPI version do not match",
    )

    privacy_doc = (ROOT / "docs" / "PRIVACY_POLICY.md").read_text(encoding="utf-8")
    privacy_page = (BACKEND / "privacy" / "index.html").read_text(encoding="utf-8")
    support_page = (BACKEND / "support" / "index.html").read_text(encoding="utf-8")
    checks.check(
        "Before publishing" not in privacy_doc
        and "support@receiptai.app" in privacy_doc
        and "support@receiptai.app" in privacy_page
        and "support@receiptai.app" in support_page,
        "Privacy and support contacts are publishable",
        "Privacy/support content still contains a placeholder or missing contact",
    )

    production_python = [
        path
        for path in (BACKEND / "app").rglob("*.py")
        if path.name != "app_logger.py"
    ] + [BACKEND / "main.py"]
    unstructured_logs = [
        str(path.relative_to(ROOT))
        for path in production_python
        if re.search(r"(?<![\w])print\(", path.read_text(encoding="utf-8"))
    ]
    checks.check(
        not unstructured_logs,
        "Production Python paths use structured logging",
        "Unstructured print() calls remain in: " + ", ".join(unstructured_logs),
    )

    workflow = ROOT / ".github" / "workflows" / "quality.yml"
    workflow_source = workflow.read_text(encoding="utf-8") if workflow.exists() else ""
    checks.check(
        workflow.exists() and "npm audit --omit=dev --audit-level=critical" in workflow_source,
        "CI quality and critical-advisory gates exist",
        "CI must include the mobile critical npm advisory gate",
    )

    exception_source = (ROOT / "docs" / "SECURITY_EXCEPTIONS.md").read_text(encoding="utf-8")
    review_match = re.search(r"Review by: (\d{4}-\d{2}-\d{2})", exception_source)
    review_date = date.fromisoformat(review_match.group(1)) if review_match else None
    checks.check(
        review_date is not None and review_date >= date.today(),
        f"Security exception is current through {review_date}" if review_date else "",
        "Security exception is missing a valid future review date",
    )

    railway = json.loads((BACKEND / "railway.json").read_text(encoding="utf-8"))
    deploy = railway.get("deploy") or {}
    checks.check(
        deploy.get("healthcheckPath") == "/health/ready"
        and deploy.get("restartPolicyType") in {"ON_FAILURE", "ALWAYS"}
        and int(deploy.get("restartPolicyMaxRetries") or 0) > 0,
        "Railway health and restart policies are source-controlled",
        "Railway must use /health/ready and a bounded restart policy",
    )

    env_example = (BACKEND / ".env.example").read_text(encoding="utf-8")
    for name in (
        "APP_ENV",
        "ANTHROPIC_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_KEY",
        "SUPABASE_SERVICE_KEY",
        "PUBLIC_BASE_URL",
        "PASSWORD_RESET_REDIRECT_URL",
        "CORS_ALLOWED_ORIGINS",
        "SUPPORT_EMAIL",
    ):
        checks.check(
            re.search(rf"^{re.escape(name)}=", env_example, re.MULTILINE) is not None,
            f"{name} is documented",
            f"{name} is missing from backend/.env.example",
        )

    migration_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in BACKEND.glob("supabase_*.sql")
    ).lower()
    missing_migration_tables = [
        table
        for table in REQUIRED_TABLES
        if table != "receipts"
        and f"create table if not exists public.{table}" not in migration_source
    ]
    checks.check(
        not missing_migration_tables,
        "Release verifier table list matches repository migrations",
        "Release verifier references tables missing from migrations: "
        + ", ".join(missing_migration_tables),
    )


def check_production_environment(checks: ReleaseChecks) -> None:
    report = validate_production_config(force_production=True)
    for error in report.errors:
        checks.failures.append(error)
    if report.ready:
        checks.passes.append("Production environment is safely configured")
    for warning in report.warnings:
        print(f"WARNING: {warning}")


def check_deployment(checks: ReleaseChecks) -> None:
    base_url = os.environ["PUBLIC_BASE_URL"].rstrip("/")
    try:
        live = request_json(f"{base_url}/health/live")
        checks.check(
            isinstance(live, dict) and live.get("status") == "ok",
            "Production liveness endpoint is healthy",
            "Production liveness endpoint did not return status=ok",
        )
        ready = request_json(f"{base_url}/health/ready")
        checks.check(
            isinstance(ready, dict) and ready.get("status") == "ready" and ready.get("production") is True,
            "Production readiness endpoint is healthy",
            "Production readiness endpoint is not ready or APP_ENV is not production",
        )
        privacy = request_page(f"{base_url}/privacy/")
        support = request_page(f"{base_url}/support/")
        checks.check(
            "ReceiptAI Privacy Policy" in privacy,
            "Public privacy policy is reachable",
            "Public privacy policy is missing or invalid",
        )
        checks.check(
            "ReceiptAI Support" in support,
            "Public support page is reachable",
            "Public support page is missing or invalid",
        )
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as error:
        checks.failures.append(f"Deployment verification failed: {type(error).__name__}")


def check_supabase_schema(checks: ReleaseChecks) -> None:
    supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
    service_key = (
        os.environ.get("SUPABASE_SERVICE_KEY", "")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    )
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    }
    for table in REQUIRED_TABLES:
        try:
            request_json(f"{supabase_url}/rest/v1/{table}?select=*&limit=1", headers)
            checks.passes.append(f"Supabase table is available: {table}")
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            checks.failures.append(f"Supabase migration/table is unavailable: {table}")

    columns = ",".join(RECEIPT_IDENTIFIER_COLUMNS)
    try:
        request_json(f"{supabase_url}/rest/v1/receipts?select={columns}&limit=1", headers)
        checks.passes.append("Receipt identifier columns are available")
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        checks.failures.append("Receipt identifier columns migration is unavailable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Only verify repository release gates")
    args = parser.parse_args()

    load_dotenv(BACKEND / ".env")
    checks = ReleaseChecks()
    check_repository(checks)
    if not args.offline:
        check_production_environment(checks)
        if not checks.failures:
            check_deployment(checks)
            check_supabase_schema(checks)

    for message in checks.passes:
        print(f"PASS: {message}")
    for message in checks.failures:
        print(f"FAIL: {message}", file=sys.stderr)
    print(f"\nRelease checks: {len(checks.passes)} passed, {len(checks.failures)} failed")
    return 1 if checks.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
