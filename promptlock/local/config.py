"""promptlock.local.config — ``.promptlock.toml`` project configuration parser.

The configuration file is **optional** — if absent, sensible defaults apply.
All reads are graceful: missing keys return documented defaults rather than
raising exceptions.

Example ``.promptlock.toml``::

    [project]
    name = "my-project"
    remote = "https://api.promptlock.io"

    [environments]
    default = "development"

    [environments.development]
    model = "claude-3-5-sonnet"

    [environments.staging]
    model = "claude-3-5-sonnet"

    [environments.production]
    model = "claude-3-opus"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# TOML reader (handles Python 3.10's lack of tomllib)
# ---------------------------------------------------------------------------

def _load_toml_text(path: Path) -> dict:
    """Load a TOML file using whatever library is available."""
    # Python 3.11+ standard library
    try:
        import tomllib
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except ImportError:
        pass
    # tomli back-port (optional install)
    try:
        import tomli  # type: ignore[import]
        with path.open("rb") as fh:
            return tomli.load(fh)
    except ImportError:
        pass
    # toml library (already a promptlock dependency on Python <=3.10)
    try:
        import toml  # type: ignore[import]
        with path.open("r", encoding="utf-8") as fh:
            return toml.load(fh)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

CONFIG_FILENAME = ".promptlock.toml"

_BUILTIN_ENVS = ("development", "staging", "production", "archived")


@dataclass
class EnvironmentConfig:
    """Per-environment configuration block."""
    name: str
    model: Optional[str] = None
    type: str = "custom"
    extra: Dict[str, object] = field(default_factory=dict)

    def is_builtin(self) -> bool:
        return self.name in _BUILTIN_ENVS


@dataclass
class ProjectConfig:
    """Parsed contents of ``.promptlock.toml``."""
    name: Optional[str] = None
    remote: Optional[str] = None
    default_environment: str = "development"
    environments: Dict[str, EnvironmentConfig] = field(default_factory=dict)

    def env_names(self) -> List[str]:
        """Return all configured environment names, falling back to builtins."""
        return list(self.environments.keys()) if self.environments else list(_BUILTIN_ENVS[:3])

    def get_env(self, name: str) -> Optional[EnvironmentConfig]:
        """Return the config for *name*, or a bare ``EnvironmentConfig`` if not found."""
        if name in self.environments:
            return self.environments[name]
        if name in _BUILTIN_ENVS:
            return EnvironmentConfig(name=name, type="builtin")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _default_config() -> ProjectConfig:
    """Return a default :class:`ProjectConfig` with builtin environments."""
    return ProjectConfig(
        name=None,
        remote=None,
        default_environment="development",
        environments={
            name: EnvironmentConfig(name=name, type="builtin")
            for name in _BUILTIN_ENVS[:3]
        },
    )


def load_config(root: Path) -> ProjectConfig:
    """Parse ``<root>/.promptlock.toml`` and return a :class:`ProjectConfig`.

    Returns a default ``ProjectConfig`` if the file does not exist or cannot
    be parsed — callers never need to handle exceptions from this function.

    Parameters
    ----------
    root:
        The project root directory (the directory containing ``.promptlock/``).
    """
    config_path = root / CONFIG_FILENAME
    if not config_path.exists():
        return _default_config()

    try:
        raw = _load_toml_text(config_path)
    except Exception:
        return _default_config()

    project_section: dict = raw.get("project", {})
    envs_section: dict = raw.get("environments", {})

    # ``default`` is a scalar key inside [environments], not a sub-table.
    default_env: str = "development"
    if isinstance(envs_section, dict):
        default_env = envs_section.pop("default", "development")

    envs: Dict[str, EnvironmentConfig] = {}
    for env_name, cfg in (envs_section or {}).items():
        if not isinstance(cfg, dict):
            continue
        envs[env_name] = EnvironmentConfig(
            name=env_name,
            model=cfg.get("model"),
            type=cfg.get("type", "builtin" if env_name in _BUILTIN_ENVS else "custom"),
            extra={k: v for k, v in cfg.items() if k not in ("model", "type")},
        )

    return ProjectConfig(
        name=project_section.get("name"),
        remote=project_section.get("remote"),
        default_environment=default_env if default_env in envs or default_env in _BUILTIN_ENVS else "development",
        environments=envs,
    )


def write_default_config(root: Path) -> Path:
    """Write a starter ``.promptlock.toml`` if one does not already exist.

    Called by ``promptlock init`` to give users a ready-to-edit config.
    Returns the path of the (possibly newly created) config file.
    """
    config_path = root / CONFIG_FILENAME
    if config_path.exists():
        return config_path

    content = """\
# promptlock project configuration
# See https://promptlock.io/docs/configuration for full reference.

[project]
# name = "my-project"
# remote = "https://api.promptlock.io"

[environments]
default = "development"

[environments.development]
model = "claude-3-5-sonnet"

[environments.staging]
model = "claude-3-5-sonnet"

[environments.production]
model = "claude-3-opus"
"""
    config_path.write_text(content, encoding="utf-8")
    return config_path
