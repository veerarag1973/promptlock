"""promptlock env — environment management commands (v0.3).

Commands::

    promptlock env list [--remote]
    promptlock env list --remote          # also fetches from registry
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from promptlock.local.config import load_config
from promptlock.local.store import find_root

console = Console()


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group("env")
def env():
    """Manage prompt environments (development / staging / production)."""


# ---------------------------------------------------------------------------
# env list
# ---------------------------------------------------------------------------

@env.command("list")
@click.option(
    "--remote",
    is_flag=True,
    default=False,
    help="Also fetch environments from the Cloud Registry.",
)
def env_list(remote: bool) -> None:
    """List all configured environments.

    Reads from \b``.promptlock.toml`` in the project root.
    Pass ``--remote`` to also show environments configured in the registry.
    """
    try:
        root = find_root()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    config = load_config(root)
    env_names = config.env_names()
    default = config.default_environment

    table = Table(
        title=":earth_americas: Local Environments",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Environment", style="bold", min_width=14)
    table.add_column("Model", min_width=24)
    table.add_column("Type", min_width=10)
    table.add_column("Default", justify="center", min_width=8)

    for name in env_names:
        env_cfg = config.environments.get(name)
        model = (env_cfg.model or "[dim]—[/dim]") if env_cfg else "[dim]—[/dim]"
        env_type = (env_cfg.type if env_cfg else "builtin")
        is_default = "[green]✓[/green]" if name == default else ""
        table.add_row(name, model, env_type, is_default)

    console.print(table)

    if remote:
        _list_remote_envs()


def _list_remote_envs() -> None:
    """Fetch environments from the Cloud Registry and print them."""
    try:
        from promptlock.auth import get_token, get_registry_url
        from promptlock.api.client import RegistryClient, RegistryClientError

        token = get_token()
        if not token:
            console.print(
                "\n[yellow]Not logged in \u2014 use `promptlock login` to view "
                "remote environments.[/yellow]"
            )
            return

        url = get_registry_url()
        client = RegistryClient(base_url=url, token=token)
        data = client.list_environments()
    except Exception as exc:
        console.print(f"\n[yellow]Could not reach registry: {exc}[/yellow]")
        return

    items = data.get("items", [])
    if not items:
        console.print("\n[dim]No remote environments found in the registry.[/dim]")
        return

    table = Table(
        title=":cloud: Registry Environments",
        header_style="bold green",
        show_lines=False,
    )
    table.add_column("Environment", style="bold", min_width=14)
    table.add_column("Type", min_width=10)
    table.add_column("ID", min_width=36)

    for item in items:
        table.add_row(
            item.get("name", "?"),
            item.get("type", "?"),
            item.get("id", "?"),
        )
    console.print(table)
