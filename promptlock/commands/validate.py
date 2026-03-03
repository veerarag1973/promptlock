"""promptlock validate — Check local prompts against the registry (v0.5).

Usage::

    promptlock validate --env staging
    promptlock validate --env production --url https://api.promptlock.io

For every prompt tracked in ``.promptlock/``, the command queries
``GET /v1/environments/{env}/active`` and compares the local HEAD SHA-256
against the registry's currently active SHA-256.

Exit codes:
  0 — all prompts match (or no prompts tracked)
  1 — one or more discrepancies found, or not logged in
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from promptlock.local.store import find_root, get_index, get_head, get_version
from promptlock.auth import get_token, get_registry_url
from promptlock.api.client import RegistryClient, RegistryClientError

console = Console()


@click.command("validate")
@click.option(
    "--env",
    "environment",
    required=True,
    help="Target environment to validate against (e.g. staging, production).",
)
@click.option(
    "--url",
    default=None,
    help="Registry base URL (overrides stored setting).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
    help="Output format.",
)
def validate(environment: str, url: Optional[str], fmt: str) -> None:
    """Validate local prompt HEADs against the registry for an environment.

    Exits with code 1 if any prompt is missing from the registry or if the
    local SHA-256 does not match the active version.
    """
    # --- Resolve project root ------------------------------------------------
    try:
        root = find_root()
    except FileNotFoundError:
        console.print(
            "[red]Not in a promptlock project. Run `promptlock init` first.[/red]"
        )
        raise SystemExit(1)

    # --- Auth ----------------------------------------------------------------
    token = get_token()
    if not token:
        console.print(
            "[red]Not logged in. Run `promptlock login` first.[/red]"
        )
        raise SystemExit(1)

    registry_url = url or get_registry_url()
    client = RegistryClient(base_url=registry_url, token=token)

    # --- Local index ---------------------------------------------------------
    index = get_index(root)
    if not index:
        console.print(
            "[yellow]No prompts tracked locally. Run `promptlock save` first.[/yellow]"
        )
        raise SystemExit(0)

    # --- Fetch active versions from registry ---------------------------------
    try:
        response = client.get_active_versions(environment)
        active_items = response.get("items", [])
    except RegistryClientError as exc:
        console.print(
            f"[red]Registry error ({exc.status_code}): {exc.detail}[/red]"
        )
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Could not reach registry: {exc}[/red]")
        raise SystemExit(1)

    # Build lookup: prompt_path → {version_num, sha256}
    registry_lookup: dict[str, dict] = {
        item["prompt_path"]: item for item in active_items
    }

    # --- Compare -------------------------------------------------------------
    results: list[dict] = []
    all_valid = True

    for prompt_path in sorted(index.keys()):
        local_head = get_head(root, prompt_path)
        local_meta = get_version(root, prompt_path, local_head) if local_head else None
        local_sha = local_meta.get("sha256", "") if local_meta else ""
        local_version = f"v{local_head}" if local_head else "-"

        registry_entry = registry_lookup.get(prompt_path)
        if registry_entry is None:
            status = "missing"
            registry_version = "-"
            registry_sha = "-"
            all_valid = False
        else:
            registry_version = f"v{registry_entry['version_num']}"
            registry_sha = registry_entry.get("sha256", "")
            if local_sha and registry_sha and local_sha == registry_sha:
                status = "ok"
            else:
                status = "mismatch"
                all_valid = False

        results.append(
            {
                "prompt_path": prompt_path,
                "local_version": local_version,
                "local_sha": local_sha[:12] if local_sha else "-",
                "registry_version": registry_version,
                "registry_sha": registry_sha[:12] if registry_sha not in ("-", "") else "-",
                "status": status,
            }
        )

    # --- Output --------------------------------------------------------------
    if fmt == "json":
        import json
        print(json.dumps(results, indent=2))
        raise SystemExit(0 if all_valid else 1)
    else:
        table = Table(
            title=f"Validate — environment: {environment!r}",
            show_header=True,
            header_style="bold",
        )
        table.add_column("Prompt Path", style="cyan")
        table.add_column("Local", style="dim")
        table.add_column("Registry", style="dim")
        table.add_column("Status", justify="center")

        for r in results:
            status_cell = {
                "ok": "[green]✔ ok[/green]",
                "mismatch": "[yellow]≠ mismatch[/yellow]",
                "missing": "[red]✗ missing[/red]",
            }.get(r["status"], r["status"])

            table.add_row(
                r["prompt_path"],
                f"{r['local_version']} ({r['local_sha']}…)",
                f"{r['registry_version']} ({r['registry_sha']}…)",
                status_cell,
            )

        console.print(table)

    if not all_valid:
        console.print(
            f"\n[red]Validation failed:[/red] one or more prompts are not in sync "
            f"with environment [bold]{environment!r}[/bold]."
        )
        raise SystemExit(1)

    console.print(
        f"\n[green]All {len(results)} prompt(s) are valid for environment "
        f"[bold]{environment!r}[/bold].[/green]"
    )
