"""Unit tests for promptlock/events.py — llm-toolkit-schema event emitters."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from promptlock.local.store import init_store


@pytest.fixture
def root(tmp_path: Path) -> Path:
    init_store(tmp_path)
    return tmp_path


def _read_events(root: Path) -> list[dict]:
    events_file = root / ".promptlock" / "events.jsonl"
    if not events_file.exists():
        return []
    lines = [l.strip() for l in events_file.read_text().splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


# ---------------------------------------------------------------------------
# emit_prompt_saved
# ---------------------------------------------------------------------------

class TestEmitPromptSaved:
    def test_emits_when_schema_available(self, root: Path):
        from promptlock.events import emit_prompt_saved
        emit_prompt_saved(
            root=root,
            prompt_id="prompts/foo.txt",
            version="v1",
            template_hash="abc123",
            author="alice",
            tags=["stable"],
            environment="development",
        )
        events = _read_events(root)
        assert len(events) == 1
        data = events[0]
        assert "prompt" in data.get("event_type", "").lower() or "source" in data

    def test_no_error_when_schema_unavailable(self, root: Path):
        with patch("promptlock.events._SCHEMA_AVAILABLE", False):
            from promptlock.events import emit_prompt_saved
            emit_prompt_saved(root=root, prompt_id="p", version="v1", template_hash="x")
        # No exception — no events written
        assert _read_events(root) == []

    def test_swallows_exceptions_silently(self, root: Path):
        """If emission raises for any reason, the CLI must not break."""
        with patch("promptlock.events._append_event", side_effect=RuntimeError("boom")):
            from promptlock.events import emit_prompt_saved
            emit_prompt_saved(root=root, prompt_id="p", version="v1", template_hash="x")


# ---------------------------------------------------------------------------
# emit_prompt_rolled_back
# ---------------------------------------------------------------------------

class TestEmitPromptRolledBack:
    def test_emits_event(self, root: Path):
        from promptlock.events import emit_prompt_rolled_back
        emit_prompt_rolled_back(
            root=root,
            prompt_id="prompts/foo.txt",
            from_version="v3",
            to_version="v1",
            rolled_back_by="bob",
            reason="regression",
        )
        events = _read_events(root)
        assert len(events) == 1

    def test_no_error_when_schema_unavailable(self, root: Path):
        with patch("promptlock.events._SCHEMA_AVAILABLE", False):
            from promptlock.events import emit_prompt_rolled_back
            emit_prompt_rolled_back(root=root, prompt_id="p", from_version="v2", to_version="v1")
        assert _read_events(root) == []


# ---------------------------------------------------------------------------
# emit_prompt_approved
# ---------------------------------------------------------------------------

class TestEmitPromptApproved:
    def test_emits_event(self, root: Path):
        from promptlock.events import emit_prompt_approved
        emit_prompt_approved(
            root=root,
            prompt_id="prompts/foo.txt",
            version="v2",
            approved_by="alice",
            approval_note="stable-tag",
        )
        events = _read_events(root)
        assert len(events) == 1

    def test_no_error_when_schema_unavailable(self, root: Path):
        with patch("promptlock.events._SCHEMA_AVAILABLE", False):
            from promptlock.events import emit_prompt_approved
            emit_prompt_approved(root=root, prompt_id="p", version="v1", approved_by="a")
        assert _read_events(root) == []


# ---------------------------------------------------------------------------
# emit_diff_compared
# ---------------------------------------------------------------------------

class TestEmitDiffCompared:
    def test_emits_event(self, root: Path):
        from promptlock.events import emit_diff_compared
        emit_diff_compared(
            root=root,
            source_id="sha_a",
            target_id="sha_b",
            source_text="hello world",
            target_text="hello there",
        )
        events = _read_events(root)
        assert len(events) == 1

    def test_no_error_when_schema_unavailable(self, root: Path):
        with patch("promptlock.events._SCHEMA_AVAILABLE", False):
            from promptlock.events import emit_diff_compared
            emit_diff_compared(root=root, source_id="a", target_id="b", source_text="", target_text="")
        assert _read_events(root) == []


# ---------------------------------------------------------------------------
# emit_prompt_promoted
# ---------------------------------------------------------------------------

class TestEmitPromptPromoted:
    def test_emits_event(self, root: Path):
        from promptlock.events import emit_prompt_promoted
        emit_prompt_promoted(
            root=root,
            prompt_id="prompts/foo.txt",
            version="v1",
            from_environment="development",
            to_environment="staging",
            promoted_by="alice",
        )
        events = _read_events(root)
        assert len(events) == 1

    def test_no_error_when_schema_unavailable(self, root: Path):
        with patch("promptlock.events._SCHEMA_AVAILABLE", False):
            from promptlock.events import emit_prompt_promoted
            emit_prompt_promoted(root=root, prompt_id="p", version="v1",
                                 from_environment="dev", to_environment="staging")
        assert _read_events(root) == []

    def test_swallows_exceptions_silently(self, root: Path):
        with patch("promptlock.events._append_event", side_effect=RuntimeError("storage error")):
            from promptlock.events import emit_prompt_promoted
            emit_prompt_promoted(root=root, prompt_id="p", version="v1",
                                 from_environment="dev", to_environment="staging")


# ---------------------------------------------------------------------------
# Multiple events accumulate in JSONL file
# ---------------------------------------------------------------------------

class TestEventAccumulation:
    def test_multiple_events_append(self, root: Path):
        from promptlock.events import emit_prompt_saved, emit_prompt_rolled_back
        emit_prompt_saved(root=root, prompt_id="p", version="v1", template_hash="a")
        emit_prompt_rolled_back(root=root, prompt_id="p", from_version="v2", to_version="v1")
        events = _read_events(root)
        assert len(events) == 2
