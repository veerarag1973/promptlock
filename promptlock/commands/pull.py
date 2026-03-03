"""promptlock pull — fetch the latest registry state to the local store."""

from __future__ import annotations

import click
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from promptlock.auth import get_registry_url, require_token
from promptlock.api.client import RegistryClient, RegistryClientError
from promptlock.local.store import (
    find_root,
    get_head,
    get_index,
    set_head,
    set_index,
    write_object,
    write_version,
)

console = Console()


@click.command("pull")
@click.argument("file", type=click.Path(dir_okay=False), required=False)
@click.option("--env", "-e", default="development",
              help="Source environment to pull from (default: development).")
@click.option("--all", "pull_all", is_flag=True,
              help="Pull all tracked prompts from the registry.")
@click.option("--url", default=None, help="Override registry URL.")
def pull(file: str | None, env: str, pull_all: bool, url: str | None):
    """Pull the latest prompt version(s) from the Cloud Registry.

    Downloads all versions not present in the local store and updates
    HEAD to the latest registry version.  Never overwrites local files
    on disk — use ``promptlock rollback`` to activate a pulled version.

    \b
    Examples:
      promptlock pull prompts/summarize.txt
      promptlock pull prompts/summarize.txt --env staging
      promptlock pull --all
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
    # Resolve target prompt paths
    # ------------------------------------------------------------------
    if pull_all:
        try:
            all_prompts_result = client.list_prompts(limit=200)
            prompts = all_prompts_result.get("items", [])
        except RegistryClientError as e:
            console.print(f"[red]Registry error:[/red] {e.detail}")
            raise SystemExit(1)
    else:
        if not file:
            console.print("[red]Error:[/red] Provide a FILE or use --all.")
            raise SystemExit(1)
        prompt_path_str = str(Path(file).as_posix())
        try:
            prompt_record = client.get_prompt_by_path(prompt_path_str)
            if prompt_record is None:
                console.print(
                    f"[red]Error:[/red] {file} not found in registry. "
                    "Push it first with [bold]promptlock push[/bold]."
                )
                raise SystemExit(1)
            prompts = [prompt_record]
        except RegistryClientError as e:
            console.print(f"[red]Registry error:[/red] {e.detail}")
            raise SystemExit(1)

    fetched = 0
    already_current = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        for prompt_record in prompts:
            prompt_path = prompt_record.get("path", "")
            prompt_id = prompt_record.get("id", "")
            task = progress.add_task(f"Pulling {prompt_path}…", total=None)

            try:
                versions_result = client.list_versions(prompt_id=prompt_id, limit=500)
                remote_versions = versions_result.get("items", [])
            except RegistryClientError as e:
                progress.remove_task(task)
                console.print(f"[red]Error pulling {prompt_path}:[/red] {e.detail}")
                continue

            index = get_index(root)
            new_versions_count = 0

            for v in remote_versions:
                sha = v.get("sha256", "")
                version_num = int(v.get("version_num", 0))
                if not sha or not version_num:
                    continue

                # Write blob (idempotent — write_object checks existence)
                content_b64 = v.get("content_base64")
                if content_b64:
                    import base64
                    content = base64.b64decode(content_b64)
                    write_object(root, content)

                # Write version metadata
                meta = {
                    "version_num": version_num,
                    "sha256": sha,
                    "prompt_path": prompt_path,
                    "author": v.get("author", "remote"),
                    "message": v.get("message", ""),
                    "timestamp": v.get("created_at", ""),
                    "tags": v.get("tags", []),
                    "parent_version": v.get("parent_version_id"),
                }
                write_version(root, prompt_path, meta)
                new_versions_count += 1

            # Update HEAD to the highest version number
            if remote_versions:
                max_v = max(remote_versions, key=lambda r: int(r.get("version_num", 0)))
                latest_sha = max_v.get("sha256", "")
                latest_num = int(max_v.get("version_num", 0))
                set_head(root, prompt_path, latest_num)
                if latest_sha:
                    index[prompt_path] = latest_sha
                    set_index(root, index)

            progress.remove_task(task)

            if new_versions_count:
                console.print(
                    f"[green]Pulled[/green] [bold]{prompt_path}[/bold] "
                    f"[dim]({new_versions_count} version(s) from {env})[/dim]"
                )
                fetched += new_versions_count
            else:
                console.print(
                    f"[dim]{prompt_path} — already up to date.[/dim]"
                )
                already_current += 1

    console.print(
        f"\n[bold]Done.[/bold] {fetched} version(s) pulled, "
        f"{already_current} prompt(s) already current."
    )
