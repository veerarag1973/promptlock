"""api.audit — Server-side event emitter using llm-toolkit-schema.

All significant API actions write a tamper-evident, HMAC-signed event to
the ``audit_events`` table using the llm-toolkit-schema Event envelope.

The chain-signing model (each event's signature covers the previous
event's signature) ensures that any gap or modification is immediately
detectable — satisfying spec §4.5 Audit Log requirements.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from api.config import settings

try:
    from llm_toolkit_schema import Event, EventType
    from llm_toolkit_schema.signing import sign_event

    _SCHEMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCHEMA_AVAILABLE = False

_API_SOURCE = f"promptlock-api@{settings.api_version}"

# In-process last-event-id cache for audit chain linking.
# In production this should be fetched from DB; fine for v0.2 dev.
_last_event_id: Optional[str] = None


def _build_event(
    event_type: str,
    payload: dict,
    actor_id: Optional[str],
    org_id: Optional[str],
) -> Optional["Event"]:
    if not _SCHEMA_AVAILABLE:
        return None
    try:
        et = EventType(event_type)
        return Event(
            event_type=et,
            source=_API_SOURCE,
            payload=payload,
            actor_id=actor_id,
            org_id=org_id,
        )
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
    global _last_event_id

    if not _SCHEMA_AVAILABLE:
        return

    try:
        from api.models import AuditEvent

        event = _build_event(event_type, payload, actor_user_id, org_id)
        if event is None:
            return

        # Chain-sign: each event's HMAC covers the previous event's signature.
        signed = sign_event(
            event,
            org_secret=settings.audit_signing_key,
            prev_id=_last_event_id,
        )
        _last_event_id = signed.event_id

        # Parse the event timestamp
        ts_raw = signed.timestamp
        if isinstance(ts_raw, str):
            ts_raw = ts_raw.rstrip("Z").replace("+00:00", "")
            try:
                ts = datetime.fromisoformat(ts_raw + "+00:00")
            except ValueError:
                ts = datetime.now(timezone.utc)
        else:
            ts = ts_raw

        row = AuditEvent(
            event_id=signed.event_id,
            timestamp=ts,
            event_type=event_type,
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
        await db_session.flush()  # persist within current transaction

    except Exception:  # noqa: BLE001
        pass
