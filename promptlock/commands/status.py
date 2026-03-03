"""promptlock status — show which tracked prompt files have changed."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box

from promptlock.local.store import (
    find_root,
    get_index,
    hash_file,
    store_path,
)

console = Console()


@click.command("status")
def status():
    """Show the status of tracked prompt files.

    Compares the current content of each tracked file against the last saved
    version and reports whether it is clean, modified, or missing.

    \b
    Example:
      promptlock status
    """
    try:
        root = find_root()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    index = get_index(root)

    if not index:
        console.print("[dim]No prompts tracked yet. Run `promptlock save <file> -m \"...\"` first.[/dim]")
        raise SystemExit(0)

    modified = []
    missing = []
    clean = []

    for prompt_path, stored_sha in sorted(index.items()):
        abs_path = root / prompt_path
        if not abs_path.exists():
            missing.append(prompt_path)
        else:
            current_sha = hash_file(abs_path)
            if current_sha != stored_sha:
                modified.append(prompt_path)
            else:
                clean.append(prompt_path)

    has_changes = bool(modified or missing)

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        title=f"[bold]promptlock status[/bold]  ({root})",
        title_style="",
    )
    table.add_column("Status", width=12)
    table.add_column("File")

    for p in modified:
        table.add_row("[bold yellow]modified[/bold yellow]", p)
    for p in missing:
        table.add_row("[bold red]deleted[/bold red]", p)
    for p in clean:
        table.add_row("[green]clean[/green]", p)

    console.print(table)

    if has_changes:
        console.print(
            "\n[dim]Run[/dim] promptlock save <file> -m \"your message\" "
            "[dim]to save changes.[/dim]"
        )
    else:
        console.print("[green]All tracked prompts are up to date.[/green]")
