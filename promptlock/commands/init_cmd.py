"""promptlock init — initialise a new promptlock project."""

import click
from pathlib import Path
from rich.console import Console

from promptlock.local.store import STORE_DIR, init_store

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

    console.print(f"[green]Initialised promptlock project[/green] in [bold]{root}[/bold]")
    console.print(f"  Created [dim]{STORE_DIR}/[/dim]")
    console.print()
    console.print("Next steps:")
    console.print("  [dim]$[/dim] promptlock save <prompt-file> -m \"Initial version\"")
