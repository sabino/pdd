"""Load operator-controlled settings without a hosted identity service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError


@dataclass(frozen=True)
class ServerSettings:
    database: Path
    tokens: tuple[tuple[str, str], ...] = field(repr=False)
    public_url: str = "http://127.0.0.1:9877"
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:9876",
        "http://localhost:9876",
    )
    session_timeout: int = 120
    example_limit: int = 3
    max_body_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if not self.tokens or any(
            not user or len(token) < 32 for user, token in self.tokens
        ):
            raise ValueError(
                "Configure unique user names and bearer tokens of at least 32 characters"
            )
        if len({user for user, _ in self.tokens}) != len(self.tokens):
            raise ValueError("User names must be unique")
        if len({token for _, token in self.tokens}) != len(self.tokens):
            raise ValueError("Bearer tokens must be unique")
        url = urlsplit(self.public_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.query
            or url.fragment
            or url.username
        ):
            raise ValueError(
                "public_url must be an HTTP(S) base URL without credentials, query, or fragment"
            )
        if (
            self.session_timeout < 30
            or not 0 <= self.example_limit <= 10
            or self.max_body_bytes < 1024
        ):
            raise ValueError(
                "Invalid session timeout, example limit, or request size limit"
            )


def load_settings() -> ServerSettings:
    """Read tokens from an operator file or PDD_SERVER_TOKEN."""
    token_file = os.environ.get("PDD_SERVER_TOKENS_FILE")
    if token_file:
        token_data = json.loads(
            Path(token_file).expanduser().read_text(encoding="utf-8")
        )
        try:
            tokens = tuple(
                TypeAdapter(dict[str, str])
                .validate_python(token_data, strict=True)
                .items()
            )
        except ValidationError:
            raise ValueError(
                "Token file must map owner names to token strings"
            ) from None
    else:
        tokens = (("owner", os.environ.get("PDD_SERVER_TOKEN", "")),)
    return ServerSettings(
        database=Path(
            os.environ.get("PDD_SERVER_DATABASE", "~/.pdd/cloud_server.sqlite3")
        ).expanduser(),
        tokens=tokens,
        public_url=os.environ.get(
            "PDD_SERVER_PUBLIC_URL", "http://127.0.0.1:9877"
        ).rstrip("/"),
        allowed_origins=tuple(
            origin.strip()
            for origin in os.environ.get(
                "PDD_SERVER_ALLOWED_ORIGINS",
                "http://127.0.0.1:9876,http://localhost:9876",
            ).split(",")
            if origin.strip()
        ),
        session_timeout=int(os.environ.get("PDD_SERVER_SESSION_TIMEOUT", "120")),
        example_limit=int(os.environ.get("PDD_SERVER_EXAMPLE_LIMIT", "3")),
    )
