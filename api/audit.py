"""api.audit — Server-side event emitter using llm-toolkit-schema.

All significant API actions write a tamper-evident, HMAC-signed event to
the ``audit_events`` table using the llm-toolkit-schema Event envelope.

The chain-signing model (each event's signature covers the previous
event's signature) ensures that any gap or modification is immediately
detectable — satisfying spec §4.5 Audit Log requirements.

``llm-toolkit-schema`` is a **mandatory** dependency (see pyproject.toml).
Custom promptlock event types use the ``x.promptlock.*`` namespace.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from llm_toolkit_schema import Event, EventType, sign
from llm_toolkit_schema.types import validate_custom

from api.config import settings

_API_SOURCE = f"promptlock-api@{settings.api_version}"

# Custom promptlock event types (x.promptlock namespace)
_CUSTOM_TYPES = [
    "x.promptlock.user.registered",
    "x.promptlock.user.login",
    "x.promptlock.user.logout",
    "x.promptlock.environment.created",
    "x.promptlock.role.assigned",
    "x.promptlock.role.revoked",
    "x.promptlock.audit.exported",
    "x.promptlock.access.denied",
]
for _ct in _CUSTOM_TYPES:
    validate_custom(_ct)


def _resolve_event_type(event_type: str) -> str:
    """Return the canonical event type string.

    Accepts either a built-in EventType enum value (``llm.*``) or a
    validated custom string (``x.promptlock.*``).  Falls back gracefully.
    """
    try:
        # Validate the custom namespace if it starts with x.
        if event_type.startswith("x."):
            validate_custom(event_type)
        else:
            EventType(event_type)  # raises ValueError if not a built-in
    except Exception:
        # Unknown types are stored as-is but won't break the audit chain.
        pass
    return event_type


async def _last_event_from_db(db_session: Any, org_id: Optional[str]) -> Optional[Event]:
    """Fetch the most recent audit event for chain-linking.

    Returns a reconstructed Event (unsigned) whose ``event_id`` will be
    used as ``prev_id`` in the chain.  Fetching from DB avoids stale
    in-process state across test runs and worker restarts.
    """
    try:
        from sqlalchemy import select, desc
        from api.models import AuditEvent

        q = select(AuditEvent).order_by(desc(AuditEvent.timestamp))
        if org_id:
            q = q.where(AuditEvent.org_id == org_id)
        q = q.limit(1)
        result = await db_session.execute(q)
        row = result.scalar_one_or_none()
        if row is None:
            return None

        # Reconstruct a minimal Event with just the ID for chain linking.
        prev = Event(
            event_type=row.event_type,
            source=row.source,
            payload=row.payload_json.get("payload", {}),
        )
        # Force the event_id to match the stored row so prev_id chains correctly.
        object.__setattr__(prev, "_event_id", row.event_id)
        if row.signature:
            object.__setattr__(prev, "_signature", row.signature)
        if row.checksum:
            object.__setattr__(prev, "_checksum", row.checksum)
        return prev
    except Exception:
        return None


async def emit(
    db_session: Any,  # AsyncSession — typed loosely to avoid hard import
    event_type: str,
    payload: dict,
    actor_user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    actor_ip: Optional[str] = None,
    org_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_version: Optional[str] = None,
) -> None:
    """Build, sign, and persist a single audit event.

    Failures are silently swallowed — the audit log must never prevent a
    business operation from completing.
    """
    try:
        from api.models import AuditEvent

        canonical_type = _resolve_event_type(event_type)

        event = Event(
            event_type=canonical_type,
            source=_API_SOURCE,
            payload=payload,
            actor_id=actor_user_id,
            org_id=org_id,
        )

        # Fetch the previous event from DB for chain-signing integrity.
        prev_event = await _last_event_from_db(db_session, org_id)

        signed = sign(
            event,
            org_secret=settings.audit_signing_key,
            prev_event=prev_event,
        )

        # Parse the event timestamp
        ts_raw = signed.timestamp
        if isinstance(ts_raw, str):
            ts_raw = ts_raw.rstrip("Z").replace("+00:00", "")
            try:
                ts = datetime.fromisoformat(ts_raw + "+00:00")
            except ValueError:
                ts = datetime.now(timezone.utc)
        else:
            ts = ts_raw if isinstance(ts_raw, datetime) else datetime.now(timezone.utc)

        row = AuditEvent(
            event_id=signed.event_id,
            timestamp=ts,
            event_type=canonical_type,
            source=_API_SOURCE,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            actor_ip=actor_ip,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource_version,
            org_id=org_id,
            payload_json=json.loads(signed.to_json()),
            checksum=signed.checksum,
            signature=signed.signature,
            prev_event_id=signed.prev_id,
        )
        db_session.add(row)
        await db_session.flush()

    except Exception:  # noqa: BLE001
        pass
