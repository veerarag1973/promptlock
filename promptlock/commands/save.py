"""promptlock save — save a new version of a prompt file."""

from __future__ import annotations

import click
from datetime import datetime, timezone
from pathlib import Path
from rich.console import Console

from promptlock.local.store import (
    find_root,
    get_head,
    get_index,
    get_current_author,
    hash_bytes,
    next_version_num,
    read_object,
    set_head,
    set_index,
    short_sha,
    write_object,
    write_version,
    _normalize_prompt_path,
)
from promptlock.events import emit_prompt_saved

console = Console()


@click.command("save")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("-m", "--message", required=True, help="Commit message describing this change.")
@click.option("--author", default=None, help="Override author name (default: current OS user).")
def save(file: str, message: str, author: str | None):
    """Save a new version of FILE to the local store.

    \b
    Example:
      promptlock save prompts/summarize.txt -m "Tighten instruction, reduce hallucinations"
    """
    try:
        root = find_root()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    file_path = Path(file).resolve()
    try:
        prompt_path = _normalize_prompt_path(str(file_path.relative_to(root)))
    except ValueError:
        console.print(
            f"[red]Error:[/red] {file} is outside the project root {root}."
        )
        raise SystemExit(1)

    content_bytes = file_path.read_bytes()
    sha = hash_bytes(content_bytes)

    # Check if content is identical to HEAD
    head_num = get_head(root, prompt_path)
    if head_num is not None:
        from promptlock.local.store import get_version
        head_meta = get_version(root, prompt_path, head_num)
        if head_meta and head_meta.get("sha256") == sha:
            console.print(
                f"[yellow]Nothing to save:[/yellow] {prompt_path} content identical to v{head_num}."
            )
            raise SystemExit(0)

    # Store the content object
    write_object(root, content_bytes)

    # Build version metadata
    version_num = next_version_num(root, prompt_path)
    actor = author or get_current_author()
    metadata = {
        "version_num": version_num,
        "sha256": sha,
        "prompt_path": prompt_path,
        "author": actor,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tags": [],
        "parent_version": head_num,
    }

    write_version(root, prompt_path, metadata)
    set_head(root, prompt_path, version_num)

    # Update index
    index = get_index(root)
    index[prompt_path] = sha
    set_index(root, index)

    # Emit llm-toolkit-schema event
    emit_prompt_saved(
        root=root,
        prompt_id=prompt_path,
        version=f"v{version_num}",
        template_hash=sha,
        author=actor,
        tags=metadata["tags"] or None,
    )

    console.print(
        f"[green]Saved[/green] [bold]{prompt_path}[/bold] "
        f"[dim]v{version_num}[/dim] {short_sha(sha)} — {message}"
    )
