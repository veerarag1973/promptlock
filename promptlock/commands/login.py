"""promptlock login — authenticate against the Cloud Registry."""

from __future__ import annotations

import click
from rich.console import Console
from rich.prompt import Prompt

from promptlock.auth import (
    get_registry_url,
    require_token,
    save_credentials,
)
from promptlock.api.client import RegistryClient, RegistryClientError

console = Console()


@click.command("login")
@click.option("--email", "-e", default=None, help="Account email address.")
@click.option("--password", "-p", default=None, help="Account password (omit to be prompted securely).")
@click.option("--url", default=None, help="Registry URL (default: https://api.promptlock.io).")
@click.option("--register", is_flag=True, help="Create a new account instead of logging in.")
@click.option("--org", default=None, help="Organisation name (required when using --register).")
def login(email: str | None, password: str | None, url: str | None, register: bool, org: str | None):
    """Log in to the promptlock Cloud Registry.

    \b
    Examples:
      promptlock login
      promptlock login --email alice@acme.com
      promptlock login --register --org "Acme Corp"
      promptlock login --url http://localhost:8000      # local dev API
    """
    base_url = url or get_registry_url()

    # ------------------------------------------------------------------
    # Resolve credentials interactively if not supplied
    # ------------------------------------------------------------------
    if not email:
        email = Prompt.ask("[bold]Email[/bold]")
    if not password:
        password = Prompt.ask("[bold]Password[/bold]", password=True)

    client = RegistryClient(base_url=base_url)

    try:
        if register:
            if not org:
                org = Prompt.ask("[bold]Organisation name[/bold]")
            console.print(f"Creating account for [bold]{email}[/bold]…")
            client.register(email=email, password=password, org_name=org)
            console.print("[green]Account created.[/green] Logging in…")

        result = client.login(email=email, password=password)
    except RegistryClientError as e:
        console.print(f"[red]Login failed:[/red] {e.detail}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[red]Cannot reach registry:[/red] {e}")
        raise SystemExit(1)

    token = result.get("access_token")
    org_id = result.get("org_id", "")
    email_returned = result.get("email", email)

    if not token:
        console.print("[red]Error:[/red] No token received from registry.")
        raise SystemExit(1)

    save_credentials(
        token=token,
        email=email_returned,
        org_id=org_id,
        url=base_url if url else None,
    )

    console.print(
        f"[green]Logged in[/green] as [bold]{email_returned}[/bold] "
        f"(org: [dim]{org_id}[/dim])"
    )
    console.print(f"  Registry: [dim]{base_url}[/dim]")
