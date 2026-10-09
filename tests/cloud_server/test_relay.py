"""Check lifecycle, persistence, ownership, and retry behavior against SQLite."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from pdd.cloud_server.app import create_app
from pdd.cloud_server.config import ServerSettings
from pdd.cloud_server.store import open_database

OTHER_HEADERS = {"Authorization": "Bearer " + "b" * 48}


def register(client: TestClient) -> str:
    response = client.post(
        "/registerSession",
        json={
            "projectPath": "/workspace/demo",
            "metadata": {"hostname": "workstation"},
        },
    )
    assert response.status_code == 200
    assert response.json()["cloudUrl"].startswith("http://127.0.0.1:9877/connect/")
    return str(response.json()["sessionId"])


def submit(client: TestClient, session_id: str) -> str:
    response = client.post(
        "/submitCommand",
        json={
            "sessionId": session_id,
            "type": "sync",
            "payload": {"args": {"args": ["demo"]}, "options": {"local": True}},
        },
    )
    assert response.status_code == 200
    return str(response.json()["commandId"])


def test_authentication_is_required(client: TestClient) -> None:
    client.headers.clear()
    assert client.get("/health").status_code == 200
    for headers in ({}, {"Authorization": "Bearer invalid"}):
        response = client.get("/listSessions", headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_session_and_command_lifecycle(client: TestClient) -> None:
    session_id = register(client)
    sessions = client.get("/listSessions").json()["sessions"]
    assert sessions[0]["projectName"] == "demo"
    assert sessions[0]["status"] == "active"
    assert datetime.fromisoformat(sessions[0]["createdAt"]).tzinfo is not None
    assert (
        client.post("/heartbeatSession", json={"sessionId": session_id}).status_code
        == 200
    )
    command_id = submit(client, session_id)
    pending = client.get("/getCommands", params={"sessionId": session_id}).json()[
        "commands"
    ]
    assert pending[0]["commandId"] == command_id
    assert pending[0]["payload"]["options"] == {"local": True}
    reference = {"sessionId": session_id, "commandId": command_id}
    assert (
        client.post(
            "/updateCommand", json={**reference, "status": "processing"}
        ).status_code
        == 200
    )
    assert client.get("/getCommands", params={"sessionId": session_id}).json() == {
        "commands": []
    }
    completed = {
        **reference,
        "status": "completed",
        "response": {"success": True, "stdout": "done"},
    }
    assert client.post("/updateCommand", json=completed).status_code == 200
    assert client.post("/updateCommand", json=completed).status_code == 200
    result = client.get("/getCommandStatus", params=reference).json()["command"]
    assert result["status"] == "completed"
    assert result["response"]["stdout"] == "done"
    assert (
        client.post(
            "/updateCommand", json={**reference, "status": "processing"}
        ).status_code
        == 409
    )
    assert client.post("/cancelCommand", json=reference).status_code == 409


def test_owner_cannot_access_another_users_state(client: TestClient) -> None:
    session_id = register(client)
    command_id = submit(client, session_id)
    assert client.get("/listSessions", headers=OTHER_HEADERS).json() == {"sessions": []}
    for endpoint in ("/heartbeatSession", "/deregisterSession"):
        assert (
            client.post(
                endpoint, headers=OTHER_HEADERS, json={"sessionId": session_id}
            ).status_code
            == 404
        )
    assert (
        client.get(
            "/getCommands", headers=OTHER_HEADERS, params={"sessionId": session_id}
        ).status_code
        == 404
    )
    reference = {"sessionId": session_id, "commandId": command_id}
    assert (
        client.get(
            "/getCommandStatus", headers=OTHER_HEADERS, params=reference
        ).status_code
        == 404
    )
    assert (
        client.post("/cancelCommand", headers=OTHER_HEADERS, json=reference).status_code
        == 404
    )
    assert (
        client.post(
            "/updateCommand",
            headers=OTHER_HEADERS,
            json={**reference, "status": "completed"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/submitCommand",
            headers=OTHER_HEADERS,
            json={"sessionId": session_id, "type": "sync"},
        ).status_code
        == 404
    )


def test_cancelled_commands_stay_cancelled(client: TestClient) -> None:
    session_id = register(client)
    command_id = submit(client, session_id)
    reference = {"sessionId": session_id, "commandId": command_id}
    assert client.post("/cancelCommand", json=reference).status_code == 200
    late = client.post(
        "/updateCommand",
        json={**reference, "status": "completed", "response": {"success": True}},
    )
    assert late.status_code == 200
    assert late.json()["command"]["status"] == "cancelled"
    assert client.get("/getCommands", params={"sessionId": session_id}).json() == {
        "commands": []
    }


def test_deregister_cancels_pending_work_idempotently(client: TestClient) -> None:
    session_id = register(client)
    command_id = submit(client, session_id)
    for _ in range(2):
        assert (
            client.post(
                "/deregisterSession", json={"sessionId": session_id}
            ).status_code
            == 200
        )
    assert client.get("/listSessions").json() == {"sessions": []}
    assert (
        client.get(
            "/getCommandStatus",
            params={"sessionId": session_id, "commandId": command_id},
        ).json()["command"]["status"]
        == "cancelled"
    )
    assert (
        client.post("/heartbeatSession", json={"sessionId": session_id}).status_code
        == 404
    )
    assert (
        client.post(
            "/submitCommand", json={"sessionId": session_id, "type": "sync"}
        ).status_code
        == 409
    )


def test_retry_keys_do_not_duplicate_work(client: TestClient) -> None:
    headers = {"Idempotency-Key": "registration-1"}
    body = {"projectPath": "/workspace/demo"}
    first = client.post("/registerSession", headers=headers, json=body).json()
    assert client.post("/registerSession", headers=headers, json=body).json() == first
    assert (
        client.post(
            "/registerSession", headers=headers, json={"projectPath": "/other"}
        ).status_code
        == 409
    )
    assert len(client.get("/listSessions").json()["sessions"]) == 1
    headers = {"Idempotency-Key": "command-1"}
    body = {"sessionId": first["sessionId"], "type": "sync"}
    command = client.post("/submitCommand", headers=headers, json=body).json()
    assert client.post("/submitCommand", headers=headers, json=body).json() == command
    assert (
        client.post(
            "/submitCommand", headers=headers, json={**body, "type": "fix"}
        ).status_code
        == 409
    )
    assert (
        len(
            client.get("/getCommands", params={"sessionId": first["sessionId"]}).json()[
                "commands"
            ]
        )
        == 1
    )


def test_stale_session_rejects_work_until_heartbeat(
    client: TestClient, settings: ServerSettings
) -> None:
    session_id = register(client)
    old_heartbeat = (datetime.now(UTC) - timedelta(seconds=180)).isoformat()
    with open_database(settings.database, write=True) as connection:
        connection.execute(
            "UPDATE sessions SET heartbeat = ? WHERE id = ?",
            (old_heartbeat, session_id),
        )
    assert client.get("/listSessions").json()["sessions"][0]["status"] == "stale"
    assert (
        client.post(
            "/submitCommand", json={"sessionId": session_id, "type": "sync"}
        ).status_code
        == 409
    )
    client.post("/heartbeatSession", json={"sessionId": session_id})
    assert submit(client, session_id)


def test_restart_retains_sessions_and_results(settings: ServerSettings) -> None:
    headers = {"Authorization": "Bearer " + "a" * 48}
    with TestClient(create_app(settings), headers=headers) as first:
        session_id = register(first)
        command_id = submit(first, session_id)
        first.post(
            "/updateCommand",
            json={
                "sessionId": session_id,
                "commandId": command_id,
                "status": "failed",
                "response": {"stderr": "failure"},
            },
        )
    with TestClient(create_app(settings), headers=headers) as second:
        assert (
            second.get("/listSessions").json()["sessions"][0]["sessionId"] == session_id
        )
        result = second.get(
            "/getCommandStatus",
            params={"sessionId": session_id, "commandId": command_id},
        ).json()["command"]
        assert result["response"] == {"stderr": "failure"}


def test_validation_limits_and_reserved_contracts(
    client: TestClient, settings: ServerSettings
) -> None:
    assert client.get("/connect/" + "x" * 129).status_code == 422
    assert (
        client.post(
            "/registerSession", json={"projectPath": "", "unknown": True}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/registerSession", content=b"x" * (settings.max_body_bytes + 1)
        ).status_code
        == 413
    )
    assert client.post("/trackUsage", json={}).status_code == 501
    assert client.post("/syncState", json={}).status_code == 501
    assert client.get("/getCreditBalance").json()["billingEnabled"] is False


def test_cors_allows_only_configured_origins(client: TestClient) -> None:
    headers = {
        "Origin": "http://127.0.0.1:9876",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
    }
    allowed = client.options("/submitCommand", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    blocked = client.options(
        "/submitCommand", headers={**headers, "Origin": "https://pdd.dev"}
    )
    assert blocked.status_code == 400
