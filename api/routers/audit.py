"""audit router — /v1/audit/* endpoints (spec §4.6, §4.5).

Requires the Auditor or Org Admin role (spec §4.3).

Endpoints::

    GET  /v1/audit            -- Query audit events with filters
    GET  /v1/audit/export     -- Full export (CSV / JSON); logs BULK_EXPORT event
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api import audit as audit_module
from api.dependencies import get_db
from api.models import AuditEvent, User
from api.rbac import require_roles
from api.schemas import AuditEventResponse, PaginatedAuditEvents

router = APIRouter(prefix="/v1/audit", tags=["audit"])


def _row_to_response(row: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=row.id,
        event_id=row.event_id,
        timestamp=row.timestamp,
        event_type=row.event_type,
        source=row.source,
        actor_user_id=row.actor_user_id,
        actor_email=row.actor_email,
        actor_ip=row.actor_ip,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        resource_version=row.resource_version,
        org_id=row.org_id,
        payload_json=row.payload_json,
        checksum=row.checksum,
        signature=row.signature,
        prev_event_id=row.prev_event_id,
    )


# ---------------------------------------------------------------------------
# GET /v1/audit
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedAuditEvents)
async def query_audit_log(
    actor_user_id: Optional[str] = Query(None, description="Filter by actor user ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    resource_id: Optional[str] = Query(None, description="Filter by resource ID"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    from_ts: Optional[datetime] = Query(None, description="Start of time range (ISO 8601)"),
    to_ts: Optional[datetime] = Query(None, description="End of time range (ISO 8601)"),
    cursor: Optional[str] = Query(None, description="Pagination cursor (last event ID)"),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_roles("Auditor", "Org Admin")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedAuditEvents:
    """Query the audit log with optional filters.

    Accessible to users with the ``Auditor`` or ``Org Admin`` role.
    Results are scoped to the caller's org and ordered by timestamp desc.
    """
    filters = [AuditEvent.org_id == current_user.org_id]

    if actor_user_id:
        filters.append(AuditEvent.actor_user_id == actor_user_id)
    if event_type:
        filters.append(AuditEvent.event_type == event_type)
    if resource_id:
        filters.append(AuditEvent.resource_id == resource_id)
    if resource_type:
        filters.append(AuditEvent.resource_type == resource_type)
    if from_ts:
        filters.append(AuditEvent.timestamp >= from_ts)
    if to_ts:
        filters.append(AuditEvent.timestamp <= to_ts)
    if cursor:
        filters.append(AuditEvent.id < cursor)

    q = (
        select(AuditEvent)
        .where(and_(*filters))
        .order_by(AuditEvent.timestamp.desc())
        .limit(limit + 1)
    )
    result = await db.execute(q)
    rows = list(result.scalars().all())

    next_cursor: Optional[str] = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = rows[-1].id

    return PaginatedAuditEvents(
        items=[_row_to_response(r) for r in rows],
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# GET /v1/audit/export
# ---------------------------------------------------------------------------


@router.get("/export")
async def export_audit_log(
    format: str = Query("json", pattern="^(json|csv)$"),
    from_ts: Optional[datetime] = Query(None),
    to_ts: Optional[datetime] = Query(None),
    current_user: User = Depends(require_roles("Auditor")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export the full audit log for the authenticated org.

    Requires the **Auditor** role.  Logs a ``x.promptlock.audit.exported``
    event (BULK_EXPORT) immediately after the query.

    Supports ``?format=json`` (default) and ``?format=csv``.
    """
    filters = [AuditEvent.org_id == current_user.org_id]
    if from_ts:
        filters.append(AuditEvent.timestamp >= from_ts)
    if to_ts:
        filters.append(AuditEvent.timestamp <= to_ts)

    q = (
        select(AuditEvent)
        .where(and_(*filters))
        .order_by(AuditEvent.timestamp.asc())
    )
    result = await db.execute(q)
    rows = list(result.scalars().all())

    # Emit BULK_EXPORT audit event
    await audit_module.emit(
        db,
        event_type="x.promptlock.audit.exported",
        payload={
            "format": format,
            "record_count": len(rows),
            "from_ts": from_ts.isoformat() if from_ts else None,
            "to_ts": to_ts.isoformat() if to_ts else None,
        },
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        org_id=current_user.org_id,
        resource_type="audit_log",
    )

    items = [_row_to_response(r) for r in rows]

    if format == "csv":
        output = io.StringIO()
        if items:
            fields = list(AuditEventResponse.model_fields.keys())
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            for item in items:
                row_dict = item.model_dump()
                # Flatten complex fields to string
                for k, v in row_dict.items():
                    if isinstance(v, (dict, list)):
                        row_dict[k] = json.dumps(v)
                writer.writerow(row_dict)
        output.seek(0)
        return StreamingResponse(
            iter([output.read()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=audit_export.csv",
            },
        )
    else:
        json_bytes = json.dumps(
            [item.model_dump(mode="json") for item in items],
            default=str,
        ).encode("utf-8")
        return StreamingResponse(
            iter([json_bytes]),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=audit_export.json",
            },
        )
