"""promptlock rollback — reactivate a previous version of a prompt file."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console

from promptlock.local.store import (
    find_root,
    get_current_author,
    get_head,
    get_index,
    get_version,
    parse_version_ref,
    set_head,
    set_index,
    short_sha,
    _normalize_prompt_path,
)
from promptlock.events import emit_prompt_rolled_back

console = Console()


@click.command("rollback")
@click.argument("file", type=click.Path(dir_okay=False))
@click.argument("version")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt.")
def rollback(file: str, version: str, yes: bool):
    """Rollback FILE to a previous VERSION.

    Updates HEAD and the index; does not delete any history.

    \b
    Example:
      promptlock rollback prompts/summarize.txt v3
    """
    try:
        root = find_root()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    file_path = Path(file).resolve() if Path(file).is_absolute() else (root / file).resolve()
    try:
        prompt_path = _normalize_prompt_path(str(file_path.relative_to(root)))
    except ValueError:
        prompt_path = _normalize_prompt_path(file)

    try:
        version_num = parse_version_ref(version)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    meta = get_version(root, prompt_path, version_num)
    if meta is None:
        console.print(
            f"[red]Error:[/red] version v{version_num} not found for {prompt_path}."
        )
        raise SystemExit(1)

    if not yes:
        console.print(
            f"Roll back [bold]{prompt_path}[/bold] to "
            f"[yellow]v{version_num}[/yellow] ({short_sha(meta['sha256'])}) "
            f"— \"{meta.get('message', '')}\"?"
        )
        click.confirm("Continue?", abort=True)

    from_version_num = get_head(root, prompt_path)
    set_head(root, prompt_path, version_num)

    index = get_index(root)
    index[prompt_path] = meta["sha256"]
    set_index(root, index)

    # Emit llm-toolkit-schema event
    actor = get_current_author()
    emit_prompt_rolled_back(
        root=root,
        prompt_id=prompt_path,
        from_version=f"v{from_version_num}" if from_version_num else "v?",
        to_version=f"v{version_num}",
        rolled_back_by=actor,
    )

    console.print(
        f"[green]Rolled back[/green] [bold]{prompt_path}[/bold] → "
        f"[yellow]v{version_num}[/yellow] {short_sha(meta['sha256'])}"
    )
    console.print(
        "[dim]History is preserved. Previous HEAD is still accessible.[/dim]"
    )
