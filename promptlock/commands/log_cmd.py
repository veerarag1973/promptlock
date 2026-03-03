"""promptlock log — view version history for a prompt file."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box

from promptlock.local.store import (
    find_root,
    get_all_versions,
    get_head,
    short_sha,
    _normalize_prompt_path,
)

console = Console()


def _fmt_timestamp(ts: str) -> str:
    """Return a human-friendly timestamp."""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


@click.command("log")
@click.argument("file", type=click.Path(dir_okay=False))
@click.option("-n", "--limit", default=0, help="Show only the last N versions (0 = all).")
def log(file: str, limit: int):
    """Show version history for FILE.

    \b
    Example:
      promptlock log prompts/summarize.txt
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

    versions = get_all_versions(root, prompt_path)
    if not versions:
        console.print(f"[yellow]No versions found for[/yellow] {prompt_path}.")
        raise SystemExit(0)

    head_num = get_head(root, prompt_path)

    if limit > 0:
        versions = versions[-limit:]

    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title=f"Version history — {prompt_path}",
        title_style="bold",
    )
    table.add_column("Ver", style="bold yellow", justify="right", width=12)
    table.add_column("SHA", style="dim", width=14)
    table.add_column("Author", width=16)
    table.add_column("Date", width=16)
    table.add_column("Tags", width=14)
    table.add_column("Message")

    for v in reversed(versions):
        vnum = v.get("version_num", "?")
        sha_short = short_sha(v.get("sha256", ""))
        author = v.get("author", "")
        ts = _fmt_timestamp(v.get("timestamp", ""))
        tags = ", ".join(v.get("tags", []))
        msg = v.get("message", "")
        is_head = vnum == head_num
        ver_str = f"v{vnum}" + (" [HEAD]" if is_head else "")
        row_style = "bold" if is_head else ""
        table.add_row(ver_str, sha_short, author, ts, tags, msg, style=row_style)

    console.print(table)
