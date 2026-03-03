"""promptlock push — sync local prompt versions to the Cloud Registry."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from promptlock.auth import get_registry_url, require_token
from promptlock.api.client import RegistryClient, RegistryClientError
from promptlock.local.store import (
    find_root,
    get_all_versions,
    get_current_author,
    get_index,
    read_object,
    _normalize_prompt_path,
)
from promptlock.events import emit_prompt_saved

console = Console()


@click.command("push")
@click.argument("file", type=click.Path(dir_okay=False), required=False)
@click.option("--env", "-e", default="development",
              help="Target environment: development / staging / production (default: development).")
@click.option("--all", "push_all", is_flag=True,
              help="Push every tracked prompt in the project. Ignores FILE argument.")
@click.option("--url", default=None, help="Override registry URL.")
def push(file: str | None, env: str, push_all: bool, url: str | None):
    """Push prompt version(s) to the Cloud Registry.

    \b
    Examples:
      promptlock push prompts/summarize.txt
      promptlock push prompts/summarize.txt --env staging
      promptlock push --all                          # push every tracked prompt
    """
    token = require_token()

    try:
        root = find_root()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    base_url = url or get_registry_url()
    client = RegistryClient(base_url=base_url, token=token)

    # ------------------------------------------------------------------
    # Determine which prompts to push
    # ------------------------------------------------------------------
    if push_all:
        index = get_index(root)
        prompt_paths = list(index.keys())
        if not prompt_paths:
            console.print("[yellow]No tracked prompts found.[/yellow] Run promptlock save first.")
            raise SystemExit(0)
    else:
        if not file:
            console.print("[red]Error:[/red] Provide a FILE or use --all.")
            raise SystemExit(1)
        abs_path = Path(file).resolve() if Path(file).is_absolute() else (root / file).resolve()
        try:
            prompt_paths = [_normalize_prompt_path(str(abs_path.relative_to(root)))]
        except ValueError:
            console.print(f"[red]Error:[/red] {file} is outside the project root {root}.")
            raise SystemExit(1)

    actor = get_current_author()
    pushed = 0
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        for prompt_path in prompt_paths:
            task = progress.add_task(f"Pushing {prompt_path}…", total=None)
            versions = get_all_versions(root, prompt_path)
            if not versions:
                progress.remove_task(task)
                console.print(f"[yellow]No versions for[/yellow] {prompt_path} — skipping.")
                skipped += 1
                continue

            # ------------------------------------------------------------------
            # Ensure the prompt resource exists in the registry
            # ------------------------------------------------------------------
            try:
                prompt_record = client.get_prompt_by_path(prompt_path)
                if prompt_record is None:
                    prompt_record = client.create_prompt(
                        name=Path(prompt_path).stem,
                        path=prompt_path,
                        description="",
                    )
                prompt_id = prompt_record["id"]
            except RegistryClientError as e:
                progress.remove_task(task)
                console.print(f"[red]Registry error for {prompt_path}:[/red] {e.detail}")
                skipped += 1
                continue

            # ------------------------------------------------------------------
            # Push each local version (idempotent: server deduplicates by SHA-256)
            # ------------------------------------------------------------------
            for v in versions:
                try:
                    content = read_object(root, v["sha256"])
                    client.push_version(
                        prompt_id=prompt_id,
                        sha256=v["sha256"],
                        version_num=v["version_num"],
                        message=v.get("message", ""),
                        author=v.get("author", actor),
                        environment=env,
                        content=content,
                        tags=v.get("tags"),
                    )
                    # Emit standardised event for each pushed version
                    emit_prompt_saved(
                        root=root,
                        prompt_id=prompt_path,
                        version=f"v{v['version_num']}",
                        template_hash=v["sha256"],
                        author=v.get("author", actor),
                        tags=v.get("tags") or None,
                        environment=env,
                    )
                    pushed += 1
                except RegistryClientError as e:
                    if e.status_code == 409:
                        # Already exists on the server — not an error.
                        pass
                    else:
                        console.print(
                            f"[red]Error pushing {prompt_path} v{v['version_num']}:[/red] {e.detail}"
                        )

            progress.remove_task(task)
            console.print(
                f"[green]Pushed[/green] [bold]{prompt_path}[/bold] "
                f"[dim]({len(versions)} version(s) → {env})[/dim]"
            )

    console.print(
        f"\n[bold]Done.[/bold] {pushed} version(s) pushed, {skipped} prompt(s) skipped."
    )
