"""Fail-fast production configuration checks with no secret values in output."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse


PRODUCTION_NAMES = {"production", "prod"}
SECURE_ENVIRONMENT_NAMES = PRODUCTION_NAMES | {"staging", "stage"}
REQUIRED_PRODUCTION_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "SUPABASE_SERVICE_KEY",
    "PUBLIC_BASE_URL",
    "PASSWORD_RESET_REDIRECT_URL",
    "CORS_ALLOWED_ORIGINS",
    "SUPPORT_EMAIL",
)


@dataclass(frozen=True)
class ProductionConfigReport:
    environment: str
    production: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.errors


def _value(name: str, environ: dict[str, str]) -> str:
    if name == "SUPABASE_SERVICE_KEY":
        return (
            environ.get("SUPABASE_SERVICE_KEY", "")
            or environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        ).strip()
    return environ.get(name, "").strip()


def _is_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_production_config(
    environ: dict[str, str] | None = None,
    *,
    force_production: bool = False,
) -> ProductionConfigReport:
    env = dict(os.environ if environ is None else environ)
    environment = env.get("APP_ENV", "development").strip().lower()
    production = force_production or environment in SECURE_ENVIRONMENT_NAMES
    errors: list[str] = []
    warnings: list[str] = []

    if not production:
        return ProductionConfigReport(environment, False, (), ())

    for name in REQUIRED_PRODUCTION_VARIABLES:
        value = _value(name, env)
        if not value or value.lower().startswith("your_") or "your-project" in value.lower():
            errors.append(f"{name} must be configured")

    for name in ("SUPABASE_URL", "PUBLIC_BASE_URL", "PASSWORD_RESET_REDIRECT_URL"):
        value = _value(name, env)
        if value and not _is_https_url(value):
            errors.append(f"{name} must use HTTPS in production")

    cors_origins = [
        item.strip().rstrip("/")
        for item in _value("CORS_ALLOWED_ORIGINS", env).split(",")
        if item.strip()
    ]
    if "*" in cors_origins:
        errors.append("CORS_ALLOWED_ORIGINS cannot contain * in production")
    for origin in cors_origins:
        if not _is_https_url(origin):
            errors.append("Every production CORS origin must be an HTTPS origin")

    anon_key = _value("SUPABASE_KEY", env)
    service_key = _value("SUPABASE_SERVICE_KEY", env)
    if anon_key and service_key and anon_key == service_key:
        errors.append("SUPABASE_SERVICE_KEY must differ from SUPABASE_KEY")

    support_email = _value("SUPPORT_EMAIL", env)
    if support_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", support_email):
        errors.append("SUPPORT_EMAIL must be a valid email address")

    public_base_url = _value("PUBLIC_BASE_URL", env).rstrip("/")
    reset_url = _value("PASSWORD_RESET_REDIRECT_URL", env)
    if public_base_url and reset_url and not reset_url.startswith(f"{public_base_url}/"):
        warnings.append("PASSWORD_RESET_REDIRECT_URL is not hosted under PUBLIC_BASE_URL")

    if env.get("LOG_JSON", "").strip().lower() not in {"1", "true", "yes", "on"}:
        warnings.append("LOG_JSON should be true for production log aggregation")

    return ProductionConfigReport(
        environment=environment,
        production=True,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def require_production_config() -> ProductionConfigReport:
    report = validate_production_config()
    if report.errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(report.errors))
    return report
