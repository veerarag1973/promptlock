"""Local .promptlock/ store operations — the core I/O layer for v0.1."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

STORE_DIR = ".promptlock"


# ---------------------------------------------------------------------------
# Root discovery
# ---------------------------------------------------------------------------

def find_root(start: Path | None = None) -> Path:
    """Walk up the directory tree to find the directory containing .promptlock/.

    Raises FileNotFoundError if no .promptlock/ is found.
    """
    current = Path(start or Path.cwd()).resolve()
    while True:
        if (current / STORE_DIR).is_dir():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                "Not a promptlock project (no .promptlock/ found). "
                "Run `promptlock init` first."
            )
        current = parent


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def store_path(root: Path) -> Path:
    return root / STORE_DIR


def _normalize_prompt_path(prompt_path: str) -> str:
    """Return a consistent POSIX relative path string, e.g. 'prompts/summarize.txt'."""
    return Path(prompt_path).as_posix().strip("/")


def _version_dir(root: Path, prompt_path: str) -> Path:
    norm = _normalize_prompt_path(prompt_path)
    return store_path(root) / "versions" / norm


# ---------------------------------------------------------------------------
# Store initialisation
# ---------------------------------------------------------------------------

def init_store(root: Path) -> None:
    """Create the .promptlock/ directory structure inside root."""
    sp = store_path(root)
    sp.mkdir(parents=True, exist_ok=True)
    (sp / "objects").mkdir(exist_ok=True)
    (sp / "versions").mkdir(exist_ok=True)

    config_file = sp / "config"
    if not config_file.exists():
        config = {
            "version": "0.1.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

    index_file = sp / "index"
    if not index_file.exists():
        index_file.write_text("{}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Content-addressed object store
# ---------------------------------------------------------------------------

def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())


def write_object(root: Path, content_bytes: bytes) -> str:
    """Store content bytes by SHA-256. Returns the hex digest. Idempotent."""
    sha = hash_bytes(content_bytes)
    obj_dir = store_path(root) / "objects" / sha[:2]
    obj_dir.mkdir(parents=True, exist_ok=True)
    obj_file = obj_dir / sha[2:]
    if not obj_file.exists():
        obj_file.write_bytes(content_bytes)
    return sha


def read_object(root: Path, sha256: str) -> bytes:
    """Read content bytes for the given SHA-256 digest."""
    obj_file = store_path(root) / "objects" / sha256[:2] / sha256[2:]
    if not obj_file.exists():
        raise FileNotFoundError(f"Object {sha256[:12]}... not found in store.")
    return obj_file.read_bytes()


# ---------------------------------------------------------------------------
# Version metadata
# ---------------------------------------------------------------------------

def get_all_versions(root: Path, prompt_path: str) -> list[dict]:
    """Return all version metadata dicts, sorted by version_num ascending."""
    vdir = _version_dir(root, prompt_path)
    if not vdir.exists():
        return []
    versions = []
    for f in sorted(vdir.glob("*.json")):
        try:
            versions.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    versions.sort(key=lambda v: v.get("version_num", 0))
    return versions


def get_version(root: Path, prompt_path: str, version_num: int) -> dict | None:
    vfile = _version_dir(root, prompt_path) / f"{version_num:04d}.json"
    if not vfile.exists():
        return None
    return json.loads(vfile.read_text(encoding="utf-8"))


def write_version(root: Path, prompt_path: str, metadata: dict) -> None:
    vdir = _version_dir(root, prompt_path)
    vdir.mkdir(parents=True, exist_ok=True)
    vnum = metadata["version_num"]
    vfile = vdir / f"{vnum:04d}.json"
    vfile.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def next_version_num(root: Path, prompt_path: str) -> int:
    versions = get_all_versions(root, prompt_path)
    if not versions:
        return 1
    return max(v["version_num"] for v in versions) + 1


# ---------------------------------------------------------------------------
# HEAD pointer
# ---------------------------------------------------------------------------

def get_head(root: Path, prompt_path: str) -> int | None:
    """Return the current HEAD version number, or None if no versions exist."""
    head_file = _version_dir(root, prompt_path) / "HEAD"
    if not head_file.exists():
        return None
    try:
        return int(head_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def set_head(root: Path, prompt_path: str, version_num: int) -> None:
    head_file = _version_dir(root, prompt_path) / "HEAD"
    head_file.parent.mkdir(parents=True, exist_ok=True)
    head_file.write_text(str(version_num), encoding="utf-8")


# ---------------------------------------------------------------------------
# Index  (maps prompt_path -> active sha256)
# ---------------------------------------------------------------------------

def get_index(root: Path) -> dict:
    index_file = store_path(root) / "index"
    if not index_file.exists():
        return {}
    try:
        return json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_index(root: Path, index: dict) -> None:
    index_file = store_path(root) / "index"
    index_file.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def get_current_author() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def parse_version_ref(version_ref: str) -> int:
    """Parse 'v3', 'V3', '3', '0003' into an integer."""
    s = version_ref.lstrip("vV")
    s = s.lstrip("0") or "0"
    try:
        return int(s)
    except ValueError:
        raise ValueError(f"Invalid version reference: {version_ref!r}. Use 'v3' or '3'.")


def short_sha(sha256: str) -> str:
    return sha256[:12]
