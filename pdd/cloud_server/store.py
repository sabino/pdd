"""Persist relay state and examples with owner-scoped SQLite transactions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from pdd.cloud_server.models import (
    CommandRequest,
    CommandUpdate,
    ExampleSubmission,
    RegisterSession,
)

JsonObject = dict[str, JsonValue]
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class StoreError(Exception):
    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.status_code = status_code


def encode_json(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode_object(value: str) -> JsonObject:
    return cast(JsonObject, json.loads(value))


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def open_database(
    database: Path, *, write: bool = False
) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        if write:
            connection.execute("BEGIN IMMEDIATE")
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database: Path) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    # Create the file privately before SQLite opens it; existing permissions belong to the operator.
    database.touch(mode=0o600, exist_ok=True)
    with open_database(database) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_key TEXT,
                request_body TEXT NOT NULL, project_path TEXT NOT NULL, name TEXT NOT NULL,
                metadata TEXT NOT NULL, cloud_url TEXT NOT NULL, created_at TEXT NOT NULL,
                heartbeat TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0,
                UNIQUE(owner, request_key)
            );
            CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                request_key TEXT, request_body TEXT NOT NULL, type TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL, response TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(session_id, request_key)
            );
            CREATE INDEX IF NOT EXISTS commands_pending ON commands(session_id, status, created_at);
            CREATE TABLE IF NOT EXISTS examples (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, shared INTEGER NOT NULL,
                payload TEXT NOT NULL, language TEXT NOT NULL, command TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS example_search USING fts5(
                example_id UNINDEXED, search_input, title, language
            );
        """)


def require_session(
    connection: sqlite3.Connection, owner: str, session_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM sessions WHERE id = ? AND owner = ?", (session_id, owner)
    ).fetchone()
    if row is None:
        raise StoreError("Session not found")
    return cast(sqlite3.Row, row)


def format_session(row: sqlite3.Row, timeout: int) -> JsonObject:
    heartbeat = datetime.fromisoformat(row["heartbeat"])
    active = (datetime.now(UTC) - heartbeat).total_seconds() < timeout
    return {
        "sessionId": row["id"],
        "cloudUrl": row["cloud_url"],
        "projectName": row["name"],
        "projectPath": row["project_path"],
        "metadata": decode_object(row["metadata"]),
        "createdAt": row["created_at"],
        "lastHeartbeat": row["heartbeat"],
        "status": "closed" if row["closed"] else "active" if active else "stale",
    }


def register_session(
    database: Path,
    owner: str,
    request: RegisterSession,
    public_url: str,
    request_key: str | None,
) -> JsonObject:
    body = encode_json(request.model_dump(mode="json", by_alias=True))
    with open_database(database, write=True) as connection:
        if request_key:
            existing = connection.execute(
                "SELECT * FROM sessions WHERE owner = ? AND request_key = ?",
                (owner, request_key),
            ).fetchone()
            if existing is not None:
                if existing["request_body"] != body:
                    raise StoreError(
                        "Idempotency key reused with a different registration", 409
                    )
                return {"sessionId": existing["id"], "cloudUrl": existing["cloud_url"]}
        session_id = uuid.uuid4().hex
        cloud_url = f"{public_url.rstrip('/')}/connect/{session_id}"
        created_at = utc_now()
        name = (
            request.session_name
            or request.project_path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        )
        connection.execute(
            "INSERT INTO sessions (id, owner, request_key, request_body, project_path, name, metadata, cloud_url, created_at, heartbeat) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                owner,
                request_key,
                body,
                request.project_path,
                name,
                encode_json(request.metadata),
                cloud_url,
                created_at,
                created_at,
            ),
        )
        return {"sessionId": session_id, "cloudUrl": cloud_url}


def list_sessions(database: Path, owner: str, timeout: int) -> list[JsonObject]:
    with open_database(database) as connection:
        rows = connection.execute(
            "SELECT * FROM sessions WHERE owner = ? AND closed = 0 ORDER BY created_at DESC",
            (owner,),
        ).fetchall()
    return [format_session(row, timeout) for row in rows]


def save_heartbeat(database: Path, owner: str, session_id: str) -> None:
    with open_database(database, write=True) as connection:
        row = require_session(connection, owner, session_id)
        if row["closed"]:
            raise StoreError("Session not found")
        connection.execute(
            "UPDATE sessions SET heartbeat = ? WHERE id = ?", (utc_now(), session_id)
        )


def close_session(database: Path, owner: str, session_id: str) -> None:
    with open_database(database, write=True) as connection:
        require_session(connection, owner, session_id)
        connection.execute("UPDATE sessions SET closed = 1 WHERE id = ?", (session_id,))
        connection.execute(
            "UPDATE commands SET status = 'cancelled', updated_at = ? WHERE session_id = ? AND status IN ('pending', 'processing')",
            (utc_now(), session_id),
        )


def format_command(row: sqlite3.Row) -> JsonObject:
    return {
        "commandId": row["id"],
        "type": row["type"],
        "payload": decode_object(row["payload"]),
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "response": decode_object(row["response"]) if row["response"] else None,
    }


def submit_command(
    database: Path,
    owner: str,
    request: CommandRequest,
    timeout: int,
    request_key: str | None,
) -> JsonObject:
    body = encode_json(request.model_dump(mode="json", by_alias=True))
    with open_database(database, write=True) as connection:
        session = require_session(connection, owner, request.session_id)
        if request_key:
            existing = connection.execute(
                "SELECT * FROM commands WHERE session_id = ? AND request_key = ?",
                (request.session_id, request_key),
            ).fetchone()
            if existing is not None:
                if existing["request_body"] != body:
                    raise StoreError(
                        "Idempotency key reused with a different command", 409
                    )
                return {"commandId": existing["id"], "status": existing["status"]}
        if format_session(session, timeout)["status"] != "active":
            raise StoreError("Session is not active", 409)
        command_id = uuid.uuid4().hex
        created_at = utc_now()
        connection.execute(
            "INSERT INTO commands (id, session_id, request_key, request_body, type, payload, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                command_id,
                request.session_id,
                request_key,
                body,
                request.type,
                encode_json(request.payload),
                created_at,
                created_at,
            ),
        )
        return {"commandId": command_id, "status": "pending"}


def get_commands(database: Path, owner: str, session_id: str) -> list[JsonObject]:
    with open_database(database) as connection:
        session = require_session(connection, owner, session_id)
        if session["closed"]:
            return []
        rows = connection.execute(
            "SELECT * FROM commands WHERE session_id = ? AND status = 'pending' ORDER BY created_at LIMIT 100",
            (session_id,),
        ).fetchall()
    return [format_command(row) for row in rows]


def require_command(
    connection: sqlite3.Connection, owner: str, session_id: str, command_id: str
) -> sqlite3.Row:
    require_session(connection, owner, session_id)
    row = connection.execute(
        "SELECT * FROM commands WHERE id = ? AND session_id = ?",
        (command_id, session_id),
    ).fetchone()
    if row is None:
        raise StoreError("Command not found")
    return cast(sqlite3.Row, row)


def get_command(
    database: Path, owner: str, session_id: str, command_id: str
) -> JsonObject:
    with open_database(database) as connection:
        return format_command(
            require_command(connection, owner, session_id, command_id)
        )


def update_command(database: Path, owner: str, request: CommandUpdate) -> JsonObject:
    with open_database(database, write=True) as connection:
        row = require_command(connection, owner, request.session_id, request.command_id)
        if row["status"] == "cancelled":
            return format_command(row)
        response = (
            encode_json(request.response)
            if request.response is not None
            else row["response"]
        )
        if row["status"] in TERMINAL_STATUSES:
            if row["status"] == request.status and row["response"] == response:
                return format_command(row)
            raise StoreError("A finished command cannot change status or result", 409)
        connection.execute(
            "UPDATE commands SET status = ?, response = ?, updated_at = ? WHERE id = ?",
            (request.status, response, utc_now(), request.command_id),
        )
        return format_command(
            require_command(connection, owner, request.session_id, request.command_id)
        )


def submit_example(database: Path, owner: str, request: ExampleSubmission) -> str:
    payload = request.model_dump(mode="json", by_alias=True)
    body = encode_json(payload)
    example_id = hashlib.sha256(f"{owner}\n{body}".encode()).hexdigest()
    language = str(request.metadata.get("language", ""))
    with open_database(database, write=True) as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO examples (id, owner, shared, payload, language, command, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                example_id,
                owner,
                request.metadata.get("isPublic") is True,
                body,
                language,
                request.command,
                utc_now(),
            ),
        )
        if cursor.rowcount:
            connection.execute(
                "INSERT INTO example_search (example_id, search_input, title, language) VALUES (?, ?, ?, ?)",
                (
                    example_id,
                    request.search_input,
                    str(request.metadata.get("title", "")),
                    language,
                ),
            )
    return example_id


def search_examples(
    database: Path, owner: str, query: str, language: str | None, limit: int
) -> list[JsonObject]:
    words = list(dict.fromkeys(re.findall(r"\w{2,}", query.lower())))[:64]
    if not words or limit == 0:
        return []
    match = " OR ".join(f'"{word}"' for word in words)
    with open_database(database) as connection:
        rows = connection.execute(
            "SELECT examples.* FROM example_search JOIN examples ON examples.id = example_search.example_id WHERE example_search MATCH ? AND (examples.owner = ? OR examples.shared = 1) AND (? IS NULL OR examples.language = ?) ORDER BY bm25(example_search), examples.id LIMIT ?",
            (match, owner, language, language, limit),
        ).fetchall()
    return [{"id": row["id"], **decode_object(row["payload"])} for row in rows]


def list_examples(
    database: Path, owner: str, limit: int, offset: int
) -> list[JsonObject]:
    with open_database(database) as connection:
        rows = connection.execute(
            "SELECT * FROM examples WHERE owner = ? OR shared = 1 ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
            (owner, limit, offset),
        ).fetchall()
    return [{"id": row["id"], **decode_object(row["payload"])} for row in rows]
