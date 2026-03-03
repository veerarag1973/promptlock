"""promptlock promote — promote a prompt version between environments (v0.3).

Usage::

    promptlock promote prompts/summarize.txt --from development --to staging
    promptlock promote prompts/summarize.txt --from development --to staging --version v3

In v0.3 promotions are **auto-approved** (no review gate).
In v0.5 this command will submit a promotion request that requires reviewer approval.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from promptlock.events import emit_prompt_promoted
from promptlock.local.store import find_root, get_head, get_version

console = Console()


@click.command("promote")
@click.argument("file", metavar="FILE", type=click.Path())
@click.option(
    "--from", "from_env",
    required=True,
    help="Source environment (e.g. development).",
)
@click.option(
    "--to", "to_env",
    required=True,
    help="Target environment (e.g. staging).",
)
@click.option(
    "--version",
    "version_ref",
    default=None,
    metavar="VERSION",
    help="Version to promote (e.g. v3). Defaults to the current HEAD.",
)
@click.option(
    "--url",
    default=None,
    envvar="PROMPTLOCK_URL",
    help="Registry URL override (or set PROMPTLOCK_URL).",
)
def promote(
    file: str,
    from_env: str,
    to_env: str,
    version_ref: Optional[str],
    url: Optional[str],
) -> None:
    """Promote FILE from one environment to another.

    \b
    Examples:
      promptlock promote prompts/summarize.txt --from development --to staging
      promptlock promote prompts/summarize.txt --from development --to staging --version v3
    """
    # --- Resolve project root -----------------------------------------------
    try:
        root = find_root()
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    # --- Resolve version number ---------------------------------------------
    if version_ref is None:
        head_num = get_head(root, file)
        if head_num is None:
            console.print(
                f"[red]{file}[/red] has no saved versions. "
                "Run `promptlock save` first."
            )
            raise SystemExit(1)
        version_num = head_num
    else:
        # Accept "v3", "V3", "3", "0003"
        clean = version_ref.lstrip("vV").lstrip("0") or "0"
        try:
            version_num = int(clean)
        except ValueError:
            console.print(f"[red]Invalid version: {version_ref!r}. Use 'v3' or '3'.[/red]")
            raise SystemExit(1)

    version_label = f"v{version_num}"

    # --- Read version metadata ----------------------------------------------
    meta = get_version(root, file, version_num)
    if meta is None:
        console.print(
            f"[red]Version {version_label} of {file} not found in local store.[/red]"
        )
        raise SystemExit(1)

    sha256: str = meta.get("sha256", "")
    prompt_id: str = meta.get("registry_prompt_id", file)

    # --- Validate environment names -----------------------------------------
    from promptlock.local.config import load_config
    config = load_config(root)
    all_envs = config.env_names()
    if from_env not in all_envs:
        console.print(
            f"[yellow]Warning: source environment '{from_env}' is not defined in "
            ".promptlock.toml.[/yellow]"
        )
    if to_env not in all_envs:
        console.print(
            f"[yellow]Warning: target environment '{to_env}' is not defined in "
            ".promptlock.toml.[/yellow]"
        )

    # --- Cloud promotion (optional — degrades gracefully) -------------------
    promotion_id: Optional[str] = None
    try:
        from promptlock.auth import get_token, get_registry_url
        from promptlock.api.client import RegistryClient, RegistryClientError

        token = get_token()
        if token:
            registry_url = url or get_registry_url()
            client = RegistryClient(base_url=registry_url, token=token)
            result = client.create_promotion(
                prompt_path=file,
                from_env=from_env,
                to_env=to_env,
                version_num=version_num,
                sha256=sha256,
            )
            promotion_id = result.get("id")
    except Exception as exc:
        console.print(f"[yellow]Registry promotion skipped ({exc}).[/yellow]")

    # --- Emit llm-toolkit-schema event --------------------------------------
    from promptlock.auth import get_email
    actor = get_email() or None
    emit_prompt_promoted(
        root=root,
        prompt_id=prompt_id,
        version=version_label,
        from_environment=from_env,
        to_environment=to_env,
        promoted_by=actor,
    )

    # --- Write local promotion log ------------------------------------------
    _log_promotion(
        root=root,
        file=file,
        version=version_label,
        from_env=from_env,
        to_env=to_env,
        actor=actor,
        promotion_id=promotion_id,
    )

    # --- Output --------------------------------------------------------------
    registry_suffix = f" [dim](registry: {promotion_id})[/dim]" if promotion_id else " [dim](local only \u2014 not logged in)[/dim]"
    console.print(
        f"[green]\u2713[/green] Promoted [bold]{file}[/bold] {version_label}  "
        f"[dim]{from_env}[/dim] \u2192 [cyan bold]{to_env}[/cyan bold]{registry_suffix}"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log_promotion(
    root: Path,
    file: str,
    version: str,
    from_env: str,
    to_env: str,
    actor: Optional[str],
    promotion_id: Optional[str],
) -> None:
    """Append one JSON line to ``.promptlock/promotions.jsonl``."""
    record = {
        "file": file,
        "version": version,
        "from_environment": from_env,
        "to_environment": to_env,
        "promoted_by": actor,
        "promotion_id": promotion_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "promoted",
    }
    log_file = root / ".promptlock" / "promotions.jsonl"
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
