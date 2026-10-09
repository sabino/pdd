import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pdd.cloud_server.config import ServerSettings, load_settings


@pytest.mark.parametrize(
    "tokens",
    [(), (("owner", "short"),), (("owner", "a" * 48), ("other", "a" * 48))],
)
def test_server_rejects_missing_or_ambiguous_credentials(
    tmp_path: Path, tokens
) -> None:
    with pytest.raises(ValueError):
        ServerSettings(database=tmp_path / "state.sqlite3", tokens=tokens)


def test_invalid_token_file_does_not_echo_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_file = tmp_path / "tokens.json"
    token_file.write_text(json.dumps({"owner": ["secret-token"]}))
    monkeypatch.setenv("PDD_SERVER_TOKENS_FILE", str(token_file))
    with pytest.raises(ValueError, match="map owner names to token strings") as error:
        load_settings()
    assert "secret-token" not in str(error.value)


@pytest.mark.parametrize("field_name", ["args", "options"])
@pytest.mark.parametrize("value", [None, [], "bad", 10])
def test_command_payload_requires_object_fields(
    client: TestClient, field_name: str, value
) -> None:
    session_id = client.post("/registerSession", json={"projectPath": "/demo"}).json()[
        "sessionId"
    ]
    response = client.post(
        "/submitCommand",
        json={"sessionId": session_id, "type": "sync", "payload": {field_name: value}},
    )
    assert response.status_code == 422
    assert client.get("/getCommands", params={"sessionId": session_id}).json() == {
        "commands": []
    }
