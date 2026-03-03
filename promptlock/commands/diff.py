"""promptlock diff — compare two versions of a prompt file."""

from __future__ import annotations

import difflib
import click
from pathlib import Path
from rich.console import Console
from rich.text import Text

from promptlock.local.store import (
    find_root,
    get_version,
    parse_version_ref,
    read_object,
    _normalize_prompt_path,
)
from promptlock.events import emit_diff_compared

console = Console()


def _render_unified_diff(old_text: str, new_text: str, old_label: str, new_label: str) -> None:
    """Print a unified diff with rich colour highlighting."""
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=old_label, tofile=new_label))

    if not diff:
        console.print("[green]No differences.[/green]")
        return

    for line in diff:
        line_stripped = line.rstrip("\n")
        if line_stripped.startswith("+++") or line_stripped.startswith("---"):
            console.print(Text(line_stripped, style="bold"))
        elif line_stripped.startswith("@@"):
            console.print(Text(line_stripped, style="cyan"))
        elif line_stripped.startswith("+"):
            console.print(Text(line_stripped, style="green"))
        elif line_stripped.startswith("-"):
            console.print(Text(line_stripped, style="red"))
        else:
            console.print(Text(line_stripped, style="dim"))


@click.command("diff")
@click.argument("file", type=click.Path(dir_okay=False))
@click.argument("version_a")
@click.argument("version_b")
def diff(file: str, version_a: str, version_b: str):
    """Show the diff between VERSION_A and VERSION_B of FILE.

    \b
    Example:
      promptlock diff prompts/summarize.txt v3 v4
      promptlock diff prompts/summarize.txt 1 2
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
        num_a = parse_version_ref(version_a)
        num_b = parse_version_ref(version_b)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    meta_a = get_version(root, prompt_path, num_a)
    meta_b = get_version(root, prompt_path, num_b)

    if meta_a is None:
        console.print(f"[red]Error:[/red] version v{num_a} not found for {prompt_path}.")
        raise SystemExit(1)
    if meta_b is None:
        console.print(f"[red]Error:[/red] version v{num_b} not found for {prompt_path}.")
        raise SystemExit(1)

    content_a = read_object(root, meta_a["sha256"]).decode("utf-8", errors="replace")
    content_b = read_object(root, meta_b["sha256"]).decode("utf-8", errors="replace")

    label_a = f"{prompt_path} (v{num_a}  by {meta_a.get('author','?')})"
    label_b = f"{prompt_path} (v{num_b}  by {meta_b.get('author','?')})"

    # Emit llm-toolkit-schema event
    emit_diff_compared(
        root=root,
        source_id=meta_a["sha256"],
        target_id=meta_b["sha256"],
        source_text=content_a,
        target_text=content_b,
    )

    console.rule(f"[bold]diff[/bold] {prompt_path}  v{num_a} → v{num_b}")
    _render_unified_diff(content_a, content_b, label_a, label_b)
