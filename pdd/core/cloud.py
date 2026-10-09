"""Explicit self-hosted service configuration for PDD clients.

Endpoint names and get_jwt_token are retained for wire compatibility.
Bearer tokens belong to the configured server; no identity exchange is needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from pdd.core.execution import is_server_execution
from pdd.get_jwt_token import (
    AuthError,
    NetworkError,
    RateLimitError,
    TokenError,
    UserCancelledError,
)

# Legacy names remain import-compatible with existing command extensions.
FIREBASE_API_KEY_ENV = "NEXT_PUBLIC_FIREBASE_API_KEY"
GITHUB_CLIENT_ID_ENV = "GITHUB_CLIENT_ID"
PDD_CLOUD_URL_ENV = "PDD_CLOUD_URL"
PDD_CLOUD_TOKEN_ENV = "PDD_CLOUD_TOKEN"
PDD_CLOUD_TOKEN_FILE_ENV = "PDD_CLOUD_TOKEN_FILE"
PDD_JWT_TOKEN_ENV = "PDD_JWT_TOKEN"
PDD_CLOUD_TIMEOUT_ENV = "PDD_CLOUD_TIMEOUT"
DEFAULT_BASE_URL = ""
DEFAULT_CLOUD_TIMEOUT = 900
CLOUD_CONNECT_TIMEOUT = 30

CLOUD_ENDPOINTS = {
    name: f"/{name}"
    for name in (
        "generateCode",
        "generateExample",
        "generateTest",
        "generateBugTest",
        "fixCode",
        "crashCode",
        "verifyCode",
        "syncState",
        "trackUsage",
        "getCreditBalance",
        "llmInvoke",
        "registerSession",
        "listSessions",
        "heartbeatSession",
        "deregisterSession",
        "submitCommand",
        "getCommands",
        "getCommandStatus",
        "updateCommand",
        "cancelCommand",
        "submitExample",
        "listExamples",
        "searchExamples",
    )
}


def get_cloud_timeout() -> int:
    try:
        value = int(os.environ.get(PDD_CLOUD_TIMEOUT_ENV, str(DEFAULT_CLOUD_TIMEOUT)))
        return value if value > 0 else DEFAULT_CLOUD_TIMEOUT
    except ValueError:
        return DEFAULT_CLOUD_TIMEOUT


def get_cloud_request_timeout() -> tuple[int, int]:
    return CLOUD_CONNECT_TIMEOUT, get_cloud_timeout()


def get_cloud_token() -> str | None:
    """Read a bearer token without touching GitHub, Firebase, or the keyring."""
    token = os.environ.get(PDD_CLOUD_TOKEN_ENV)
    if token:
        return token.strip() or None
    token_file = os.environ.get(PDD_CLOUD_TOKEN_FILE_ENV)
    if token_file:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip() or None
    return os.environ.get(PDD_JWT_TOKEN_ENV) or None


class CloudConfig:
    """Compatibility interface for command-specific remote adapters."""

    @staticmethod
    def ensure_default_env() -> None:
        os.environ.setdefault(
            "PDD_ENV", "self-hosted" if os.environ.get(PDD_CLOUD_URL_ENV) else "local"
        )

    @staticmethod
    def _ensure_default_env() -> None:
        CloudConfig.ensure_default_env()

    @staticmethod
    def get_base_url() -> str:
        url = os.environ.get(PDD_CLOUD_URL_ENV, "").strip().rstrip("/")
        if not url:
            return DEFAULT_BASE_URL
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "PDD_CLOUD_URL must be an HTTP(S) base URL without credentials, query, or fragment"
            )
        return url

    @staticmethod
    def get_endpoint_url(endpoint_name: str) -> str:
        base = CloudConfig.get_base_url()
        if not base:
            raise ValueError(
                "Set PDD_CLOUD_URL and PDD_CLOUD_TOKEN to use a self-hosted server"
            )
        return f"{base}{CLOUD_ENDPOINTS.get(endpoint_name, f'/{endpoint_name}')}"

    @staticmethod
    def get_jwt_token(verbose: bool = False, app_name: str = "PDD CLI") -> str | None:
        """Return the configured bearer token under the legacy method name."""
        if not CloudConfig.get_base_url():
            return None
        return get_cloud_token()

    @staticmethod
    def is_server_configured() -> bool:
        return bool(CloudConfig.get_base_url() and get_cloud_token())

    @staticmethod
    def is_running_in_cloud() -> bool:
        return bool(
            is_server_execution()
            or os.environ.get("K_SERVICE")
            or os.environ.get("FUNCTIONS_EMULATOR")
        )

    @staticmethod
    def is_cloud_enabled() -> bool:
        if (
            os.environ.get("PDD_FORCE_LOCAL", "").strip().lower()
            in {"1", "true", "yes", "on"}
            or CloudConfig.is_running_in_cloud()
        ):
            return False
        return CloudConfig.is_server_configured()


__all__ = [
    "CLOUD_CONNECT_TIMEOUT",
    "CLOUD_ENDPOINTS",
    "DEFAULT_BASE_URL",
    "DEFAULT_CLOUD_TIMEOUT",
    "FIREBASE_API_KEY_ENV",
    "GITHUB_CLIENT_ID_ENV",
    "PDD_CLOUD_TIMEOUT_ENV",
    "PDD_CLOUD_TOKEN_ENV",
    "PDD_CLOUD_TOKEN_FILE_ENV",
    "PDD_CLOUD_URL_ENV",
    "PDD_JWT_TOKEN_ENV",
    "AuthError",
    "CloudConfig",
    "NetworkError",
    "RateLimitError",
    "TokenError",
    "UserCancelledError",
    "get_cloud_request_timeout",
    "get_cloud_timeout",
    "get_cloud_token",
]
