"""Check explicit server configuration and local execution boundaries."""

import pytest

from pdd.core.cloud import (
    CLOUD_CONNECT_TIMEOUT,
    DEFAULT_CLOUD_TIMEOUT,
    CloudConfig,
    get_cloud_request_timeout,
    get_cloud_timeout,
)
from pdd.core.execution import server_execution


@pytest.fixture(autouse=True)
def clear_configuration(monkeypatch):
    for name in (
        "PDD_CLOUD_URL",
        "PDD_CLOUD_TOKEN",
        "PDD_CLOUD_TOKEN_FILE",
        "PDD_JWT_TOKEN",
        "PDD_FORCE_LOCAL",
        "PDD_CLOUD_TIMEOUT",
        "K_SERVICE",
        "FUNCTIONS_EMULATOR",
        "PDD_ENV",
    ):
        monkeypatch.delenv(name, raising=False)


def test_unconfigured_clients_stay_local(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_FIREBASE_API_KEY", "old-key")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "old-client")
    monkeypatch.setenv("PDD_JWT_TOKEN", "old-token")
    assert CloudConfig.get_base_url() == ""
    assert CloudConfig.get_jwt_token() is None
    assert not CloudConfig.is_cloud_enabled()
    with pytest.raises(ValueError, match="PDD_CLOUD_URL"):
        CloudConfig.get_endpoint_url("generateCode")


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:9877", "https://server.example/api/"]
)
def test_server_urls_use_one_explicit_base(monkeypatch, url):
    monkeypatch.setenv("PDD_CLOUD_URL", url)
    monkeypatch.setenv("PDD_CLOUD_TOKEN", "server-token")
    assert CloudConfig.is_cloud_enabled()
    for endpoint in ("generateCode", "submitCommand", "submitExample", "extension"):
        assert (
            CloudConfig.get_endpoint_url(endpoint) == url.rstrip("/") + "/" + endpoint
        )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://server",
        "https://user:secret@server",
        "https://server?q=1",
        "https://server#fragment",
        "invalid",
    ],
)
def test_invalid_base_urls_fail_before_sending_tokens(monkeypatch, url):
    monkeypatch.setenv("PDD_CLOUD_URL", url)
    with pytest.raises(ValueError):
        CloudConfig.get_base_url()


def test_token_priority_and_file_rotation(monkeypatch, tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n")
    monkeypatch.setenv("PDD_CLOUD_URL", "https://server.example")
    monkeypatch.setenv("PDD_CLOUD_TOKEN", " env-token ")
    monkeypatch.setenv("PDD_CLOUD_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("PDD_JWT_TOKEN", "legacy-token")
    assert CloudConfig.get_jwt_token() == "env-token"
    monkeypatch.delenv("PDD_CLOUD_TOKEN")
    assert CloudConfig.get_jwt_token() == "file-token"
    token_file.write_text("rotated-token")
    assert CloudConfig.get_jwt_token() == "rotated-token"
    monkeypatch.delenv("PDD_CLOUD_TOKEN_FILE")
    assert CloudConfig.get_jwt_token() == "legacy-token"


@pytest.mark.parametrize(
    "control", ["PDD_FORCE_LOCAL", "K_SERVICE", "FUNCTIONS_EMULATOR"]
)
def test_local_and_server_execution_cannot_recurse(monkeypatch, control):
    monkeypatch.setenv("PDD_CLOUD_URL", "https://server.example")
    monkeypatch.setenv("PDD_CLOUD_TOKEN", "server-token")
    monkeypatch.setenv(control, "1")
    assert CloudConfig.is_server_configured()
    assert not CloudConfig.is_cloud_enabled()


def test_request_context_is_restored(monkeypatch):
    monkeypatch.setenv("PDD_CLOUD_URL", "https://server.example")
    monkeypatch.setenv("PDD_CLOUD_TOKEN", "server-token")
    with server_execution():
        assert not CloudConfig.is_cloud_enabled()
    assert CloudConfig.is_cloud_enabled()


@pytest.mark.parametrize(
    ("configured", "expected"), [(False, "local"), (True, "self-hosted")]
)
def test_environment_defaults_do_not_select_vendor_production(
    monkeypatch, configured, expected
):
    if configured:
        monkeypatch.setenv("PDD_CLOUD_URL", "https://server.example")
    CloudConfig.ensure_default_env()
    import os

    assert os.environ["PDD_ENV"] == expected
    monkeypatch.setenv("PDD_ENV", "operator-choice")
    CloudConfig.ensure_default_env()
    assert os.environ["PDD_ENV"] == "operator-choice"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("137", 137),
        ("", DEFAULT_CLOUD_TIMEOUT),
        ("bad", DEFAULT_CLOUD_TIMEOUT),
        ("1.5", DEFAULT_CLOUD_TIMEOUT),
        ("0", DEFAULT_CLOUD_TIMEOUT),
        ("-1", DEFAULT_CLOUD_TIMEOUT),
    ],
)
def test_timeouts_bound_requests(monkeypatch, value, expected):
    monkeypatch.setenv("PDD_CLOUD_TIMEOUT", value)
    assert get_cloud_timeout() == expected
    assert get_cloud_request_timeout() == (CLOUD_CONNECT_TIMEOUT, expected)
