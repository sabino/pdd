"""Inspect self-hosted credentials without a hosted login or cache writes."""

import json
from unittest.mock import patch

import httpx
import pytest
from click.testing import CliRunner

from pdd.commands.auth import auth_group


@pytest.fixture(autouse=True)
def clear_configuration(monkeypatch):
    for name in (
        "PDD_CLOUD_URL",
        "PDD_CLOUD_TOKEN",
        "PDD_CLOUD_TOKEN_FILE",
        "PDD_JWT_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("PDD_CLOUD_URL", "https://server.example")
    monkeypatch.setenv("PDD_CLOUD_TOKEN", "server-token")


def test_status_is_local_without_configuration():
    with patch("pdd.commands.auth.httpx.get") as request:
        result = CliRunner().invoke(auth_group, ["status"])
    assert result.exit_code == 0
    assert "Local mode" in result.output
    request.assert_not_called()


def test_login_explains_configuration_without_opening_browser():
    with patch("webbrowser.open") as browser:
        result = CliRunner().invoke(auth_group, ["login"])
    assert result.exit_code == 1
    assert "PDD_CLOUD_TOKEN" in result.output
    browser.assert_not_called()


@pytest.mark.parametrize(
    "arguments", [["login"], ["login", "--browser"], ["status", "--verify"]]
)
def test_explicit_verification_uses_only_the_configured_server(configured, arguments):
    response = httpx.Response(
        200,
        json={"sessions": []},
        request=httpx.Request("GET", "https://server.example/listSessions"),
    )
    with (
        patch("pdd.commands.auth.httpx.get", return_value=response) as request,
        patch("webbrowser.open") as browser,
    ):
        result = CliRunner().invoke(auth_group, arguments)
    assert result.exit_code == 0, result.output
    request.assert_called_once_with(
        "https://server.example/listSessions",
        headers={"Authorization": "Bearer server-token"},
        timeout=10,
    )
    browser.assert_not_called()


def test_configured_status_does_not_contact_server(configured):
    with patch("pdd.commands.auth.httpx.get") as request:
        result = CliRunner().invoke(auth_group, ["status"])
    assert result.exit_code == 0
    assert "https://server.example" in result.output
    assert "server-token" not in result.output
    request.assert_not_called()


@pytest.mark.parametrize("status_code", [401, 503])
def test_verification_rejection_is_an_error(configured, status_code):
    response = httpx.Response(
        status_code, request=httpx.Request("GET", "https://server.example/listSessions")
    )
    with patch("pdd.commands.auth.httpx.get", return_value=response):
        result = CliRunner().invoke(auth_group, ["status", "--verify"])
    assert result.exit_code == 1
    assert "could not authenticate" in result.output


def test_verification_network_error_is_an_error(configured):
    with patch(
        "pdd.commands.auth.httpx.get", side_effect=httpx.ConnectError("unreachable")
    ):
        result = CliRunner().invoke(auth_group, ["login"])
    assert result.exit_code == 1


@pytest.mark.parametrize("arguments", [["logout"], ["clear-cache"]])
def test_credential_commands_leave_identity_caches_untouched(
    configured, arguments, tmp_path, monkeypatch
):
    cache = tmp_path / ".pdd/jwt_cache"
    cache.parent.mkdir()
    cache.write_text("legacy cache")
    monkeypatch.setattr("pdd.get_jwt_token.JWT_CACHE_FILE", cache)
    with patch("pdd.commands.auth.httpx.get") as request:
        result = CliRunner().invoke(auth_group, arguments)
    assert result.exit_code == 0
    assert "PDD_CLOUD_TOKEN" in result.output
    assert cache.read_text() == "legacy cache"
    request.assert_not_called()


@pytest.mark.parametrize("output_format", ["raw", "json"])
def test_token_export_is_explicit(configured, output_format):
    result = CliRunner().invoke(auth_group, ["token", "--format", output_format])
    assert result.exit_code == 0
    assert (
        json.loads(result.output)["token"]
        if output_format == "json"
        else result.output.strip()
    ) == "server-token"


def test_token_export_without_credentials_fails():
    result = CliRunner().invoke(auth_group, ["token"])
    assert result.exit_code == 1
