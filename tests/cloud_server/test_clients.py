"""Send requests from the existing adapters to the self-hosted API."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pdd.cloud_server import inference
from pdd.core.cloud import CloudConfig
from pdd.llm_invoke import _llm_invoke_cloud
from pdd.remote_session import RemoteSessionManager
from pdd.server.routes import auth, config


@pytest.fixture
def configured_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDD_CLOUD_URL", "http://self-hosted.test")
    monkeypatch.setenv("PDD_CLOUD_TOKEN", "a" * 48)
    monkeypatch.delenv("PDD_FORCE_LOCAL", raising=False)


@pytest.mark.asyncio
async def test_remote_session_adapter_uses_the_relay(
    client: TestClient,
    configured_server: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async_client = httpx.AsyncClient

    def create_client(**kwargs: Any) -> httpx.AsyncClient:
        return async_client(transport=httpx.ASGITransport(app=client.app), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", create_client)
    manager = RemoteSessionManager("a" * 48, tmp_path)
    url = await manager.register("my project")
    assert url.endswith(str(manager.session_id))
    assert await manager.register("my project") == url
    sessions = await manager.list_sessions("a" * 48)
    assert len(sessions) == 1
    assert sessions[0].project_name == "my project"
    response = client.post(
        "/submitCommand",
        json={
            "sessionId": manager.session_id,
            "type": "sync",
            "payload": {"args": {"args": ["demo"]}},
        },
    )
    command_id = response.json()["commandId"]
    pending = await manager.get_pending_commands()
    assert pending[0].command_id == command_id
    assert pending[0].payload["args"] == {"args": ["demo"]}
    await manager.update_command(command_id, "processing")
    assert await manager._get_command_status(command_id) == "processing"
    await manager.update_command(
        command_id, "completed", {"stdout": "done", "success": True}
    )
    assert await manager._get_command_status(command_id) == "completed"
    assert await manager.get_pending_commands() == []
    assert await manager.deregister()
    assert await manager.list_sessions("a" * 48) == []


def test_llm_adapter_parses_self_hosted_response(
    client: TestClient, configured_server: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def post(url: str, **kwargs: Any) -> requests.Response:
        response = client.post(
            url.replace("http://self-hosted.test", ""),
            json=kwargs["json"],
            headers=kwargs["headers"],
        )
        result = requests.Response()
        result.status_code = response.status_code
        result._content = response.content
        return result

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(
        inference,
        "llm_invoke",
        Mock(
            return_value={
                "result": {"answer": "value"},
                "cost": 0.1,
                "model_name": "server-model",
                "thinking_output": "reasoning",
            }
        ),
    )
    result = _llm_invoke_cloud(
        prompt="question",
        input_json={},
        strength=0.5,
        temperature=0,
        verbose=False,
        output_pydantic=None,
        output_schema={"type": "object"},
        time=0.25,
        use_batch_mode=False,
        messages=None,
        language="python",
    )
    assert result["result"] == {"answer": "value"}
    assert result["cost"] == 0.1
    assert result["model_name"] == "server-model"
    assert result["thinking_output"] == "reasoning"


def test_local_browser_gets_self_hosted_configuration(configured_server: None) -> None:
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(config.router)
    with TestClient(app, client=("127.0.0.1", 1234)) as browser:
        assert browser.get("/api/v1/config/cloud-url").json()["cloud_enabled"] is True
        assert browser.get("/api/v1/auth/status").json()["authenticated"] is True
        assert browser.get("/api/v1/auth/jwt-token").json() == {"jwt": "a" * 48}
        assert (
            browser.get(
                "/api/v1/auth/jwt-token",
                headers={"Origin": "https://untrusted.example"},
            ).status_code
            == 403
        )
        assert browser.post("/api/v1/auth/login", json={}).json()["success"] is True
    with TestClient(app, client=("192.0.2.1", 1234)) as remote:
        assert remote.get("/api/v1/auth/jwt-token").status_code == 403


def test_bearer_token_file_rotation_does_not_exchange_identity(
    configured_server: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("first-token", encoding="utf-8")
    monkeypatch.delenv("PDD_CLOUD_TOKEN")
    monkeypatch.setenv("PDD_CLOUD_TOKEN_FILE", str(token_file))
    assert CloudConfig.get_jwt_token() == "first-token"
    token_file.write_text("second-token", encoding="utf-8")
    assert CloudConfig.get_jwt_token() == "second-token"


def test_default_configuration_does_not_reuse_vendor_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("PDD_CLOUD_URL", "PDD_CLOUD_TOKEN", "PDD_CLOUD_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PDD_JWT_TOKEN", "old-vendor-token")
    monkeypatch.setenv("NEXT_PUBLIC_FIREBASE_API_KEY", "old-key")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "old-id")
    assert CloudConfig.get_base_url() == ""
    assert CloudConfig.get_jwt_token() is None
    assert not CloudConfig.is_cloud_enabled()
    with pytest.raises(ValueError, match="PDD_CLOUD_URL"):
        CloudConfig.get_endpoint_url("generateCode")
