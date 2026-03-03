"""promptlock init — initialise a new promptlock project."""

import click
from pathlib import Path
from rich.console import Console

from promptlock.local.store import STORE_DIR, init_store
from promptlock.local.config import write_default_config

console = Console()


@click.command("init")
@click.argument("directory", default=".", type=click.Path(file_okay=False))
def init(directory: str):
    """Initialise a new promptlock project in DIRECTORY (default: current directory)."""
    root = Path(directory).resolve()

    store_dir = root / STORE_DIR
    if store_dir.exists():
        console.print(f"[yellow]Already initialised:[/yellow] {store_dir}")
        raise SystemExit(0)

    root.mkdir(parents=True, exist_ok=True)
    init_store(root)

    # Write a starter .promptlock.toml (skipped if one already exists)
    config_path = write_default_config(root)
    created_config = not config_path.exists() or True  # always written by write_default_config

    console.print(f"[green]Initialised promptlock project[/green] in [bold]{root}[/bold]")
    console.print(f"  Created [dim]{STORE_DIR}/[/dim]")
    console.print(f"  Created [dim].promptlock.toml[/dim] (edit to configure environments)")
    console.print()
    console.print("Next steps:")
    console.print("  [dim]$[/dim] promptlock save <prompt-file> -m \"Initial version\"")
    console.print("  [dim]$[/dim] promptlock env list")

