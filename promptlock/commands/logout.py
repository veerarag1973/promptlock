"""promptlock logout — revoke token and clear local credentials."""

from __future__ import annotations

import click
from rich.console import Console

from promptlock.auth import clear_credentials, get_registry_url, get_token
from promptlock.api.client import RegistryClient, RegistryClientError

console = Console()


@click.command("logout")
def logout():
    """Log out from the promptlock Cloud Registry.

    Revokes the active token server-side (if reachable) and removes
    the stored credentials from ``~/.promptlock/config``.

    \b
    Example:
      promptlock logout
    """
    token = get_token()
    if not token:
        console.print("[yellow]Not logged in.[/yellow] Nothing to do.")
        raise SystemExit(0)

    # Best-effort server-side revocation — don't fail if the API is down.
    try:
        client = RegistryClient(base_url=get_registry_url(), token=token)
        client.logout()
    except Exception:
        pass  # Offline or token already expired — clear locally anyway.

    clear_credentials()
    console.print("[green]Logged out.[/green] Credentials cleared from ~/.promptlock/config")
