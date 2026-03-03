"""Unit tests for promptlock/local/store.py — the core local storage layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from promptlock.local.store import (
    _normalize_prompt_path,
    find_root,
    get_all_versions,
    get_current_author,
    get_head,
    get_index,
    get_version,
    hash_bytes,
    hash_file,
    init_store,
    next_version_num,
    parse_version_ref,
    read_object,
    set_head,
    set_index,
    short_sha,
    store_path,
    write_object,
    write_version,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Return an initialised promptlock project root."""
    init_store(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

class TestNormalizePromptPath:
    def test_posix_path_unchanged(self):
        assert _normalize_prompt_path("prompts/summarize.txt") == "prompts/summarize.txt"

    def test_leading_slash_stripped(self):
        assert _normalize_prompt_path("/prompts/summarize.txt") == "prompts/summarize.txt"

    def test_windows_backslash_converted(self):
        result = _normalize_prompt_path("prompts\\summarize.txt")
        assert result == "prompts/summarize.txt"

    def test_simple_filename(self):
        assert _normalize_prompt_path("chat.txt") == "chat.txt"


class TestStorePath:
    def test_returns_dotpromptlock_subdir(self, tmp_path: Path):
        assert store_path(tmp_path) == tmp_path / ".promptlock"


# ---------------------------------------------------------------------------
# find_root
# ---------------------------------------------------------------------------

class TestFindRoot:
    def test_finds_root_in_current_dir(self, project_root: Path):
        assert find_root(project_root) == project_root

    def test_finds_root_from_subdir(self, project_root: Path):
        sub = project_root / "prompts" / "nested"
        sub.mkdir(parents=True)
        assert find_root(sub) == project_root

    def test_raises_when_no_root(self, tmp_path: Path, monkeypatch):
        # Patch STORE_DIR to a unique sentinel so stale .promptlock dirs in
        # pytest's temp hierarchy don't satisfy the find_root walk.
        import promptlock.local.store as _store_mod
        monkeypatch.setattr(_store_mod, "STORE_DIR", ".__promptlock_sentinel_12345__")
        with pytest.raises(FileNotFoundError, match="Not a promptlock project"):
            find_root(tmp_path)


# ---------------------------------------------------------------------------
# init_store
# ---------------------------------------------------------------------------

class TestInitStore:
    def test_creates_directory_structure(self, tmp_path: Path):
        init_store(tmp_path)
        store = tmp_path / ".promptlock"
        assert store.is_dir()
        assert (store / "objects").is_dir()
        assert (store / "versions").is_dir()
        assert (store / "config").exists()
        assert (store / "index").exists()

    def test_idempotent_second_call(self, project_root: Path):
        init_store(project_root)  # should not raise
        assert (project_root / ".promptlock").is_dir()

    def test_config_is_valid_json(self, project_root: Path):
        config = json.loads((project_root / ".promptlock" / "config").read_text())
        assert "version" in config
        assert "created_at" in config

    def test_index_is_empty_dict(self, project_root: Path):
        index = json.loads((project_root / ".promptlock" / "index").read_text())
        assert index == {}


# ---------------------------------------------------------------------------
# Content-addressed object store
# ---------------------------------------------------------------------------

class TestHashBytes:
    def test_sha256_of_known_value(self):
        # echo -n "hello" | sha256sum
        assert hash_bytes(b"hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_empty_bytes(self):
        result = hash_bytes(b"")
        assert len(result) == 64


class TestHashFile:
    def test_matches_hash_bytes(self, tmp_path: Path):
        f = tmp_path / "x.txt"
        f.write_bytes(b"test content")
        assert hash_file(f) == hash_bytes(b"test content")


class TestWriteReadObject:
    def test_write_creates_content_addressed_file(self, project_root: Path):
        sha = write_object(project_root, b"hello world")
        obj_path = project_root / ".promptlock" / "objects" / sha[:2] / sha[2:]
        assert obj_path.exists()
        assert obj_path.read_bytes() == b"hello world"

    def test_read_returns_original(self, project_root: Path):
        content = b"some prompt text"
        sha = write_object(project_root, content)
        assert read_object(project_root, sha) == content

    def test_write_idempotent(self, project_root: Path):
        sha1 = write_object(project_root, b"dup")
        sha2 = write_object(project_root, b"dup")
        assert sha1 == sha2

    def test_read_missing_raises(self, project_root: Path):
        with pytest.raises(FileNotFoundError):
            read_object(project_root, "a" * 64)


# ---------------------------------------------------------------------------
# Version metadata
# ---------------------------------------------------------------------------

class TestVersionMetadata:
    def test_write_and_read_version(self, project_root: Path):
        meta = {
            "version_num": 1,
            "sha256": "abc123",
            "prompt_path": "prompts/foo.txt",
            "author": "alice",
            "message": "initial",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "tags": [],
            "parent_version": None,
        }
        write_version(project_root, "prompts/foo.txt", meta)
        result = get_version(project_root, "prompts/foo.txt", 1)
        assert result is not None
        assert result["sha256"] == "abc123"
        assert result["author"] == "alice"

    def test_get_version_missing_returns_none(self, project_root: Path):
        assert get_version(project_root, "prompts/foo.txt", 99) is None

    def test_get_all_versions_sorted(self, project_root: Path):
        for i in [3, 1, 2]:
            write_version(project_root, "p.txt", {
                "version_num": i, "sha256": f"sha{i}", "prompt_path": "p.txt",
                "author": "a", "message": "", "timestamp": "", "tags": [], "parent_version": None,
            })
        versions = get_all_versions(project_root, "p.txt")
        assert [v["version_num"] for v in versions] == [1, 2, 3]

    def test_get_all_versions_empty(self, project_root: Path):
        assert get_all_versions(project_root, "missing.txt") == []

    def test_next_version_num_first(self, project_root: Path):
        assert next_version_num(project_root, "new.txt") == 1

    def test_next_version_num_increments(self, project_root: Path):
        for i in [1, 2]:
            write_version(project_root, "seq.txt", {
                "version_num": i, "sha256": "x", "prompt_path": "seq.txt",
                "author": "a", "message": "", "timestamp": "", "tags": [], "parent_version": None,
            })
        assert next_version_num(project_root, "seq.txt") == 3


# ---------------------------------------------------------------------------
# HEAD pointer
# ---------------------------------------------------------------------------

class TestHead:
    def test_get_head_none_when_no_versions(self, project_root: Path):
        assert get_head(project_root, "foo.txt") is None

    def test_set_and_get_head(self, project_root: Path):
        set_head(project_root, "foo.txt", 5)
        assert get_head(project_root, "foo.txt") == 5

    def test_head_overwrite(self, project_root: Path):
        set_head(project_root, "foo.txt", 1)
        set_head(project_root, "foo.txt", 3)
        assert get_head(project_root, "foo.txt") == 3


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

class TestIndex:
    def test_get_index_empty(self, project_root: Path):
        assert get_index(project_root) == {}

    def test_set_and_get_index(self, project_root: Path):
        set_index(project_root, {"prompts/foo.txt": "abc123"})
        assert get_index(project_root) == {"prompts/foo.txt": "abc123"}

    def test_get_index_no_file(self, tmp_path: Path):
        # Without init_store, index file doesn't exist
        assert get_index(tmp_path) == {}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

class TestParseVersionRef:
    def test_v3(self):
        assert parse_version_ref("v3") == 3

    def test_V3_uppercase(self):
        assert parse_version_ref("V3") == 3

    def test_plain_int(self):
        assert parse_version_ref("3") == 3

    def test_zero_padded(self):
        assert parse_version_ref("0003") == 3

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid version reference"):
            parse_version_ref("abc")

    def test_zero(self):
        assert parse_version_ref("0") == 0


class TestShortSha:
    def test_returns_12_chars(self):
        sha = "a" * 64
        assert short_sha(sha) == "a" * 12


class TestGetCurrentAuthor:
    def test_returns_string(self):
        result = get_current_author()
        assert isinstance(result, str)
        assert len(result) > 0
