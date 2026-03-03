"""promptlock.events — Emit llm-toolkit-schema compliant events.

Every significant promptlock action emits a structured event to
``.promptlock/events.jsonl``.  The format is defined by the
``llm-toolkit-schema`` library; promptlock owns the ``llm.prompt.*``
namespace.

Events are written silently — if event emission fails for any reason
(e.g. schema unavailable, malformed data) the error is swallowed so that
the CLI continues to function normally.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import List, Optional

try:
    from llm_toolkit_schema import Event, EventType
    from llm_toolkit_schema.namespaces.prompt import (
        PromptRolledBackPayload,
        PromptSavedPayload,
    )
    from llm_toolkit_schema.namespaces.diff import DiffComparisonPayload

    _SCHEMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCHEMA_AVAILABLE = False

# source identifier: tool-name@semver as required by the schema envelope
_SOURCE = "promptlock@0.1.0"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _append_event(root: Path, event: "Event") -> None:
    """Append a single JSON event as a JSONL line to .promptlock/events.jsonl."""
    events_file = root / ".promptlock" / "events.jsonl"
    with events_file.open("a", encoding="utf-8") as fh:
        fh.write(event.to_json() + "\n")


# ---------------------------------------------------------------------------
# Public emitters — one per significant CLI action
# ---------------------------------------------------------------------------

def emit_prompt_saved(
    root: Path,
    prompt_id: str,
    version: str,
    template_hash: str,
    author: Optional[str] = None,
    tags: Optional[List[str]] = None,
    environment: str = "development",
) -> None:
    """Emit an ``llm.prompt.saved`` event.

    Parameters
    ----------
    root:           Absolute path to the project root (contains ``.promptlock/``).
    prompt_id:      Stable identifier for the prompt — typically the relative path.
    version:        Version label, e.g. ``"v1"`` or ``"v3"``.
    template_hash:  SHA-256 hex digest of the saved content.
    author:         Optional author / actor identifier.
    tags:           Optional list of tag strings.
    environment:    Target environment (default ``"development"``).
    """
    if not _SCHEMA_AVAILABLE:
        return
    try:
        payload = PromptSavedPayload(
            prompt_id=prompt_id,
            version=version,
            environment=environment,
            template_hash=template_hash,
            author=author,
            tags=list(tags) if tags else None,
        )
        event = Event(
            event_type=EventType.PROMPT_SAVED,
            source=_SOURCE,
            payload=payload.to_dict(),
            actor_id=author,
        )
        event.validate()
        _append_event(root, event)
    except Exception:  # noqa: BLE001 — never let event emission break the CLI
        pass


def emit_prompt_rolled_back(
    root: Path,
    prompt_id: str,
    from_version: str,
    to_version: str,
    rolled_back_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Emit an ``llm.prompt.rolled_back`` event.

    Parameters
    ----------
    root:            Absolute path to the project root.
    prompt_id:       Stable identifier for the prompt.
    from_version:    The version that was active before the rollback.
    to_version:      The version restored by the rollback.
    rolled_back_by:  Optional actor identifier.
    reason:          Optional human-readable reason.
    """
    if not _SCHEMA_AVAILABLE:
        return
    try:
        payload = PromptRolledBackPayload(
            prompt_id=prompt_id,
            from_version=from_version,
            to_version=to_version,
            reason=reason,
            rolled_back_by=rolled_back_by,
        )
        event = Event(
            event_type=EventType.PROMPT_ROLLED_BACK,
            source=_SOURCE,
            payload=payload.to_dict(),
            actor_id=rolled_back_by,
        )
        event.validate()
        _append_event(root, event)
    except Exception:  # noqa: BLE001
        pass


def emit_diff_compared(
    root: Path,
    source_id: str,
    target_id: str,
    source_text: str,
    target_text: str,
) -> None:
    """Emit an ``llm.diff.comparison.completed`` event.

    Parameters
    ----------
    root:         Absolute path to the project root.
    source_id:    SHA-256 of the source (left-hand) artefact.
    target_id:    SHA-256 of the target (right-hand) artefact.
    source_text:  Decoded text content of the source artefact.
    target_text:  Decoded text content of the target artefact.
    """
    if not _SCHEMA_AVAILABLE:
        return
    try:
        similarity = round(
            difflib.SequenceMatcher(None, source_text, target_text).ratio(), 4
        )
        payload = DiffComparisonPayload(
            source_id=source_id,
            target_id=target_id,
            diff_type="text/unified",
            similarity_score=similarity,
            source_text=source_text,
            target_text=target_text,
        )
        event = Event(
            event_type=EventType.DIFF_COMPARISON_COMPLETED,
            source=_SOURCE,
            payload=payload.to_dict(),
        )
        event.validate()
        _append_event(root, event)
    except Exception:  # noqa: BLE001
        pass
