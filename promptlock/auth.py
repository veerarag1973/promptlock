"""promptlock.auth — JWT token storage for the Cloud Registry.

Tokens are stored at ``~/.promptlock/config`` (TOML format) so they
persist across terminal sessions and are never written inside a project
directory.

File layout::

    [registry]
    url = "https://api.promptlock.io"   # or http://localhost:8000
    token = "<JWT access token>"
    email = "user@example.com"
    org_id = "org_acme"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config file location
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path.home() / ".promptlock"
_CONFIG_FILE = _CONFIG_DIR / "config"


def _read_config() -> dict:
    """Parse ~/.promptlock/config as a minimal TOML-like key=value file."""
    if not _CONFIG_FILE.exists():
        return {}
    data: dict = {}
    section: Optional[str] = None
    for line in _CONFIG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            data.setdefault(section, {})
        elif "=" in line and section:
            key, _, val = line.partition("=")
            data[section][key.strip()] = val.strip().strip('"')
    return data


def _write_config(data: dict) -> None:
    """Write a minimal TOML-like config to ~/.promptlock/config."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.chmod(0o600) if _CONFIG_FILE.exists() else None
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
    text = "\n".join(lines)
    _CONFIG_FILE.write_text(text, encoding="utf-8")
    try:
        _CONFIG_FILE.chmod(0o600)  # restrict to owner on Unix
    except Exception:
        pass  # Windows doesn't support chmod the same way


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

DEFAULT_REGISTRY_URL = os.environ.get(
    "PROMPTLOCK_REGISTRY_URL", "https://api.promptlock.io"
)


def get_registry_url() -> str:
    """Return the configured registry URL (or the default)."""
    cfg = _read_config()
    return cfg.get("registry", {}).get("url", DEFAULT_REGISTRY_URL)


def get_token() -> Optional[str]:
    """Return the stored JWT access token, or ``None`` if not logged in."""
    cfg = _read_config()
    return cfg.get("registry", {}).get("token") or None


def get_email() -> Optional[str]:
    """Return the stored user email, or ``None``."""
    cfg = _read_config()
    return cfg.get("registry", {}).get("email") or None


def get_org_id() -> Optional[str]:
    """Return the stored org_id, or ``None``."""
    cfg = _read_config()
    return cfg.get("registry", {}).get("org_id") or None


def save_credentials(
    token: str,
    email: str,
    org_id: str,
    url: Optional[str] = None,
) -> None:
    """Persist JWT credentials to ``~/.promptlock/config``."""
    cfg = _read_config()
    cfg.setdefault("registry", {})
    cfg["registry"]["url"] = url or DEFAULT_REGISTRY_URL
    cfg["registry"]["token"] = token
    cfg["registry"]["email"] = email
    cfg["registry"]["org_id"] = org_id
    _write_config(cfg)


def clear_credentials() -> None:
    """Remove stored token / email / org_id (keeps URL intact)."""
    cfg = _read_config()
    if "registry" in cfg:
        for field in ("token", "email", "org_id"):
            cfg["registry"].pop(field, None)
    _write_config(cfg)


def require_token() -> str:
    """Return the stored token or raise ``SystemExit`` if not logged in."""
    tok = get_token()
    if not tok:
        from rich.console import Console

        Console().print(
            "[red]Not logged in.[/red] Run [bold]promptlock login[/bold] first."
        )
        raise SystemExit(1)
    return tok
