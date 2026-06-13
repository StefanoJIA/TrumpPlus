from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


VALID_APP_ENVS = {"local", "test", "staging", "production"}
VALID_AUTH_MODES = {"header_stub", "disabled", "external"}


@dataclass(frozen=True)
class EnvironmentConfig:
    app_env: str
    auth_mode: str
    allow_insecure_auth_stub: bool
    dangerous_config_warnings: tuple[str, ...]
    insecure_auth_stub: bool


def load_environment() -> EnvironmentConfig:
    app_env = os.getenv("APP_ENV", "local").strip().lower()
    auth_mode = os.getenv("AUTH_MODE", "header_stub").strip().lower()
    allow_insecure = os.getenv("ALLOW_INSECURE_AUTH_STUB", "false").strip().lower() == "true"
    if app_env not in VALID_APP_ENVS:
        raise RuntimeError(f"Invalid APP_ENV: {app_env}")
    if auth_mode not in VALID_AUTH_MODES:
        raise RuntimeError(f"Invalid AUTH_MODE: {auth_mode}")
    warnings: list[str] = []
    insecure = auth_mode == "header_stub" and app_env in {"staging", "production"}
    if auth_mode == "header_stub" and app_env in {"staging", "production"}:
        raise RuntimeError("AUTH_MODE=header_stub is only allowed in local/test; use AUTH_MODE=external for staging/production")
    if app_env == "production" and allow_insecure:
        raise RuntimeError("ALLOW_INSECURE_AUTH_STUB=true is forbidden in production")
    if insecure and allow_insecure:
        warnings.append("insecure_header_stub_enabled_for_staging")
    return EnvironmentConfig(
        app_env=app_env,
        auth_mode=auth_mode,
        allow_insecure_auth_stub=allow_insecure,
        dangerous_config_warnings=tuple(warnings),
        insecure_auth_stub=insecure and allow_insecure,
    )


def security_health() -> dict[str, Any]:
    config = load_environment()
    return {
        "app_env": config.app_env,
        "auth_mode": config.auth_mode,
        "insecure_auth_stub": config.insecure_auth_stub,
        "manual_publish_only": True,
        "platform_publish_api_enabled": False,
        "truth_social_direct_scraper_enabled": False,
        "dangerous_config_warnings": list(config.dangerous_config_warnings),
        "permissions_policy_loaded": Path("app/config/approval_policy.yaml").exists(),
        "source_policy_loaded": Path("app/config/source_policy.yaml").exists(),
    }


def validate_startup_environment() -> None:
    load_environment()
