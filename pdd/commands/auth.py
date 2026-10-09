"""Inspect bearer-token configuration for a self-hosted PDD server."""

from __future__ import annotations

import json

import click
import httpx

from pdd.core.cloud import CloudConfig


@click.group("auth")
def auth_group() -> None:
    """Manage self-hosted server authentication."""


@auth_group.command("login")
@click.option(
    "--browser/--no-browser",
    default=False,
    help="Accepted for CLI compatibility; no browser login is required",
)
def login(browser: bool) -> None:
    """Check configured credentials without a separate account login."""
    if not CloudConfig.is_server_configured():
        raise click.ClickException(
            "Set PDD_CLOUD_URL and PDD_CLOUD_TOKEN or PDD_CLOUD_TOKEN_FILE"
        )
    verify_connection()
    click.echo("Authenticated with the configured self-hosted server.")


def verify_connection() -> None:
    try:
        response = httpx.get(
            CloudConfig.get_endpoint_url("listSessions"),
            headers={"Authorization": f"Bearer {CloudConfig.get_jwt_token()}"},
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        raise click.ClickException(
            "The configured server could not authenticate this token"
        ) from None


@auth_group.command("status")
@click.option(
    "--verify", is_flag=True, help="Check the token with the configured server"
)
def status(verify: bool) -> None:
    """Show configuration; contact the server only with --verify."""
    if not CloudConfig.is_server_configured():
        click.echo("Local mode. No self-hosted server credentials configured.")
        return
    if verify:
        verify_connection()
    click.echo(f"Self-hosted server: {CloudConfig.get_base_url()}")
    click.echo("Bearer token configured.")


@auth_group.command("logout")
def logout_cmd() -> None:
    """Explain how to clear process-external configuration."""
    click.echo(
        "Unset PDD_CLOUD_TOKEN and PDD_CLOUD_TOKEN_FILE, then restart pdd connect. Revoke tokens in the server configuration."
    )


@auth_group.command("token")
@click.option(
    "--format", "output_format", type=click.Choice(["raw", "json"]), default="raw"
)
def token_cmd(output_format: str) -> None:
    """Print the configured token for an explicitly requested export."""
    token = CloudConfig.get_jwt_token()
    if not token:
        raise click.ClickException("No self-hosted server credentials configured")
    click.echo(json.dumps({"token": token}) if output_format == "json" else token)


@auth_group.command("clear-cache")
def clear_cache() -> None:
    """Retain the legacy command without touching unrelated identity caches."""
    click.echo(
        "Self-hosted authentication has no token cache. Update PDD_CLOUD_TOKEN or PDD_CLOUD_TOKEN_FILE."
    )
