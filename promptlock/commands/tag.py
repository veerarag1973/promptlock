"""promptlock tag — attach a named tag to a specific version."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console

from promptlock.local.store import (
    find_root,
    get_version,
    parse_version_ref,
    write_version,
    _normalize_prompt_path,
)

console = Console()


@click.command("tag")
@click.argument("file", type=click.Path(dir_okay=False))
@click.argument("version")
@click.option("--name", "-n", required=True, help="Tag name to attach (e.g. stable-2026-02).")
def tag(file: str, version: str, name: str):
    """Attach a tag NAME to a specific VERSION of FILE.

    \b
    Example:
      promptlock tag prompts/summarize.txt v4 --name stable-2026-02
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

    tags: list = meta.get("tags", [])
    if name in tags:
        console.print(
            f"[yellow]Tag '{name}' already exists[/yellow] on "
            f"{prompt_path} v{version_num}."
        )
        raise SystemExit(0)

    tags.append(name)
    meta["tags"] = tags
    write_version(root, prompt_path, meta)

    console.print(
        f"[green]Tagged[/green] [bold]{prompt_path}[/bold] "
        f"v{version_num} → [bold cyan]{name}[/bold cyan]"
    )
