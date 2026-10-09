"""Keep service checks off the network and out of operator credentials."""

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pdd.cloud_server.app import create_app
from pdd.cloud_server.config import ServerSettings


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_connection(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network access is blocked for service tests")

    monkeypatch.setattr(socket.socket, "connect", reject_connection)


@pytest.fixture
def settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        database=tmp_path / "server.sqlite3",
        tokens=(("owner", "a" * 48), ("other", "b" * 48)),
    )


@pytest.fixture
def client(settings: ServerSettings) -> Iterator[TestClient]:
    with TestClient(
        create_app(settings), headers={"Authorization": "Bearer " + "a" * 48}
    ) as client:
        yield client
