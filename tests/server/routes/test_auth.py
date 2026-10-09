"""Verify the local browser's self-hosted authentication contract."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pdd.server.routes.auth import router


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PDD_CLOUD_URL", "https://server.example")
    monkeypatch.setenv("PDD_CLOUD_TOKEN", "server-token")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        yield client


def test_status_and_login_report_configuration(client):
    assert client.get("/api/v1/auth/status").json() == {
        "authenticated": True,
        "cached": False,
        "expires_at": None,
    }
    assert client.post("/api/v1/auth/login", json={"no_browser": False}).json() == {
        "success": True,
        "error": None,
    }
    assert client.get("/api/v1/auth/login/poll/legacy").json()["status"] == "error"


def test_missing_configuration_explains_local_mode(client, monkeypatch):
    monkeypatch.delenv("PDD_CLOUD_URL")
    assert not client.get("/api/v1/auth/status").json()["authenticated"]
    response = client.post("/api/v1/auth/login").json()
    assert not response["success"]
    assert "PDD_CLOUD_TOKEN" in response["error"]
    assert client.get("/api/v1/auth/jwt-token").json() == {"jwt": None}


@pytest.mark.parametrize(
    "origin", ["http://localhost:9876", "http://127.0.0.1:9876", "http://[::1]:9876"]
)
def test_loopback_browsers_can_read_the_configured_token(client, origin):
    assert client.get("/api/v1/auth/jwt-token", headers={"Origin": origin}).json() == {
        "jwt": "server-token"
    }


@pytest.mark.parametrize(
    "origin", ["https://evil.example", "null", "http://localhost.evil.example"]
)
def test_external_origins_cannot_read_tokens(client, origin):
    assert (
        client.get("/api/v1/auth/jwt-token", headers={"Origin": origin}).status_code
        == 403
    )


def test_logout_explains_operator_revocation(client):
    result = client.post("/api/v1/auth/logout").json()
    assert not result["success"]
    assert "Revoke tokens" in result["message"]


def test_connection_probe_checks_the_configured_server(client):
    response = httpx.Response(200, json={"sessions": []})
    with patch("pdd.server.routes.auth.httpx.AsyncClient") as create_client:
        http_client = AsyncMock()
        http_client.get.return_value = response
        create_client.return_value.__aenter__.return_value = http_client
        result = client.post("/api/v1/auth/test").json()
    assert result["success"]
    http_client.get.assert_awaited_once_with(
        "https://server.example/listSessions",
        headers={"Authorization": "Bearer server-token"},
    )
