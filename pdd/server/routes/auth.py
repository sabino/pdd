"""Expose configured self-hosted credentials to the local browser."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pdd.core.cloud import CloudConfig

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class AuthStatus(BaseModel):
    authenticated: bool
    cached: bool = False
    expires_at: float | None = None


class JWTTokenResponse(BaseModel):
    jwt: str | None = None


class LoginRequest(BaseModel):
    no_browser: bool = True


class LoginResponse(BaseModel):
    success: bool
    error: str | None = None


class LogoutResult(BaseModel):
    success: bool
    message: str


class CloudConnectionTestResponse(BaseModel):
    success: bool
    message: str
    status_code: int | None = None
    response_time_ms: float | None = None
    error: str | None = None


def require_local_browser(request: Request) -> None:
    try:
        is_local = bool(request.client and ip_address(request.client.host).is_loopback)
    except ValueError:
        is_local = False
    origin = request.headers.get("origin")
    if origin:
        origin_url = urlsplit(origin)
        try:
            origin_is_local = bool(
                origin_url.hostname
                and (
                    origin_url.hostname == "localhost"
                    or ip_address(origin_url.hostname).is_loopback
                )
            )
        except ValueError:
            origin_is_local = False
        is_local = is_local and origin_is_local
    if not is_local:
        raise HTTPException(
            status_code=403,
            detail="Service credentials are available only to a local browser",
        )


@router.get("/status", response_model=AuthStatus)
async def get_auth_status() -> AuthStatus:
    return AuthStatus(authenticated=CloudConfig.is_server_configured())


@router.get("/jwt-token", response_model=JWTTokenResponse)
async def get_jwt_token(request: Request) -> JWTTokenResponse:
    require_local_browser(request)
    return JWTTokenResponse(jwt=CloudConfig.get_jwt_token())


@router.post("/login", response_model=LoginResponse)
async def start_login(request: LoginRequest | None = None) -> LoginResponse:
    configured = CloudConfig.is_server_configured()
    return LoginResponse(
        success=configured,
        error=None
        if configured
        else "Set PDD_CLOUD_URL and PDD_CLOUD_TOKEN or PDD_CLOUD_TOKEN_FILE, then restart pdd connect",
    )


@router.post("/logout", response_model=LogoutResult)
async def logout() -> LogoutResult:
    return LogoutResult(
        success=False,
        message="Unset PDD_CLOUD_TOKEN and PDD_CLOUD_TOKEN_FILE, then restart pdd connect. Revoke tokens in the server configuration.",
    )


@router.get("/login/poll/{poll_id}")
async def poll_login_status(poll_id: str) -> dict[str, str]:
    return {
        "status": "error",
        "message": "Self-hosted authentication uses configured bearer tokens",
    }


@router.post("/test", response_model=CloudConnectionTestResponse)
async def test_cloud_connection() -> CloudConnectionTestResponse:
    token = CloudConfig.get_jwt_token()
    if not token:
        return CloudConnectionTestResponse(
            success=False, message="No self-hosted server credentials configured"
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                CloudConfig.get_endpoint_url("listSessions"),
                headers={"Authorization": f"Bearer {token}"},
            )
        return CloudConnectionTestResponse(
            success=response.is_success,
            message="Server connected"
            if response.is_success
            else "Server rejected the connection",
            status_code=response.status_code,
        )
    except httpx.RequestError:
        return CloudConnectionTestResponse(
            success=False, message="Could not reach the configured server"
        )
