"""API routers for environments and promotions (v0.3).

Endpoints::

    GET   /v1/environments              -- list org environments
    POST  /v1/environments              -- create a new environment
    POST  /v1/promotions                -- submit a promotion (auto-approved in v0.3)
    GET   /v1/promotions                -- list promotions (filterable by prompt_path)
    PATCH /v1/promotions/{id}           -- update status (used in v0.5 approval workflow)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api import audit
from api.dependencies import get_current_user, get_db
from api.models import Environment, Prompt, PromptEnvironmentActive, PromotionRequest, User
from api.schemas import (
    CreateEnvironmentRequest,
    CreatePromotionRequest,
    EnvironmentResponse,
    PaginatedEnvironments,
    PaginatedPromotions,
    PromotionResponse,
    UpdatePromotionRequest,
)

router = APIRouter(prefix="/v1", tags=["environments", "promotions"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _env_to_response(env: Environment) -> EnvironmentResponse:
    return EnvironmentResponse(
        id=env.id,
        org_id=env.org_id,
        name=env.name,
        type=env.type,
        config_json=env.config_json,
        created_at=env.created_at,
    )


def _promotion_to_response(p: PromotionRequest) -> PromotionResponse:
    return PromotionResponse(
        id=p.id,
        prompt_id=p.prompt_id,
        prompt_path=p.prompt_path,
        from_environment=p.from_environment,
        to_environment=p.to_environment,
        version_num=p.version_num,
        sha256=p.sha256,
        requested_by=p.requested_by,
        status=p.status,
        comment=p.comment,
        created_at=p.created_at,
        resolved_at=p.resolved_at,
    )


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------

@router.get("/environments", response_model=PaginatedEnvironments)
async def list_environments(
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all environments for the current user's org.

    Environments are seeded at org creation time (development / staging /
    production) and can be extended via POST /v1/environments.
    """
    q = select(Environment).where(Environment.org_id == current_user.org_id)
    if cursor:
        q = q.where(Environment.id > cursor)
    q = q.order_by(Environment.created_at).limit(limit + 1)
    result = await db.execute(q)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = page[-1].id if has_more else None

    return PaginatedEnvironments(
        items=[_env_to_response(e) for e in page],
        next_cursor=next_cursor,
        total=None,
    )


@router.post("/environments", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
async def create_environment(
    req: CreateEnvironmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a custom environment.

    Returns 409 if an environment with the same name already exists for the org.
    """
    # Idempotency check
    existing = await db.execute(
        select(Environment).where(
            Environment.org_id == current_user.org_id,
            Environment.name == req.name,
        )
    )
    existing_env = existing.scalar_one_or_none()
    if existing_env:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Environment '{req.name}' already exists.",
        )

    env = Environment(
        id=str(uuid.uuid4()),
        org_id=current_user.org_id,
        name=req.name,
        type=req.type,
        config_json=req.config_json,
    )
    db.add(env)
    await db.flush()

    await audit.emit(
        db,
        event_type="x.promptlock.environment.created",
        payload={"name": req.name, "type": req.type},
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        org_id=current_user.org_id,
        resource_type="environment",
        resource_id=env.id,
    )

    await db.commit()
    await db.refresh(env)
    return _env_to_response(env)


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------

@router.post("/promotions", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    req: CreatePromotionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a promotion request.

    In v0.3 promotions are **auto-approved** — the status is set to
    ``promoted`` immediately.  In v0.5 this endpoint will create a
    ``pending`` request that requires reviewer approval before promotion
    takes effect.

    Also upserts the ``prompt_environment_active`` row so that this version
    is tracked as the active one for the target environment.
    """
    actor_ip = request.client.host if request.client else None

    # Resolve optional prompt FK
    prompt_id: Optional[str] = None
    result = await db.execute(
        select(Prompt).where(
            Prompt.org_id == current_user.org_id,
            Prompt.path == req.prompt_path,
        )
    )
    prompt = result.scalar_one_or_none()
    if prompt:
        prompt_id = prompt.id

    promo = PromotionRequest(
        id=str(uuid.uuid4()),
        prompt_id=prompt_id,
        org_id=current_user.org_id,
        prompt_path=req.prompt_path,
        from_environment=req.from_environment,
        to_environment=req.to_environment,
        version_num=req.version_num,
        sha256=req.sha256,
        requested_by=current_user.id,
        # v0.3: auto-approve; v0.5 will change this to "pending"
        status="promoted",
        resolved_at=datetime.now(timezone.utc),
    )
    db.add(promo)
    await db.flush()

    # Upsert prompt_environment_active if we have a known prompt
    if prompt_id:
        await _upsert_active(
            db=db,
            prompt_id=prompt_id,
            environment=req.to_environment,
            version_num=req.version_num,
            activated_by=current_user.id,
        )

    await audit.emit(
        db,
        event_type="llm.prompt.promoted",
        payload={
            "prompt_path": req.prompt_path,
            "from_environment": req.from_environment,
            "to_environment": req.to_environment,
            "version_num": req.version_num,
            "sha256": req.sha256,
        },
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=actor_ip,
        org_id=current_user.org_id,
        resource_type="prompt",
        resource_id=prompt_id,
        resource_version=str(req.version_num),
    )

    await db.commit()
    await db.refresh(promo)
    return _promotion_to_response(promo)


@router.get("/promotions", response_model=PaginatedPromotions)
async def list_promotions(
    prompt_path: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List promotion history for the current org, optionally filtered by prompt path."""
    q = select(PromotionRequest).where(PromotionRequest.org_id == current_user.org_id)
    if prompt_path:
        q = q.where(PromotionRequest.prompt_path == prompt_path)
    if cursor:
        q = q.where(PromotionRequest.id > cursor)
    q = q.order_by(PromotionRequest.created_at.desc()).limit(limit + 1)

    result = await db.execute(q)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = page[-1].id if has_more else None

    return PaginatedPromotions(
        items=[_promotion_to_response(p) for p in page],
        next_cursor=next_cursor,
        total=None,
    )


@router.patch("/promotions/{promotion_id}", response_model=PromotionResponse)
async def update_promotion(
    promotion_id: str,
    req: UpdatePromotionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve or reject a promotion request.

    In v0.3 this endpoint is a no-op stub (all promotions are already
    ``promoted``).  In v0.5 this becomes the reviewer approval / rejection
    action with separation-of-duties enforcement.
    """
    result = await db.execute(
        select(PromotionRequest).where(
            PromotionRequest.id == promotion_id,
            PromotionRequest.org_id == current_user.org_id,
        )
    )
    promo = result.scalar_one_or_none()
    if promo is None:
        raise HTTPException(status_code=404, detail="Promotion not found.")

    promo.status = req.status
    promo.comment = req.comment
    promo.resolved_at = datetime.now(timezone.utc)

    # Map promotion decision to the correct built-in llm-toolkit-schema event type.
    _DECISION_EVENT = {
        "approved": "llm.prompt.approved",
        "rejected": "llm.prompt.rejected",
    }
    decision_event_type = _DECISION_EVENT.get(req.status, "x.promptlock.promotion.updated")

    await audit.emit(
        db,
        event_type=decision_event_type,
        payload={"comment": req.comment, "promotion_id": promotion_id, "status": req.status},
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        org_id=current_user.org_id,
        resource_type="promotion",
        resource_id=promotion_id,
    )

    await db.commit()
    await db.refresh(promo)
    return _promotion_to_response(promo)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _upsert_active(
    db: AsyncSession,
    prompt_id: str,
    environment: str,
    version_num: int,
    activated_by: Optional[str],
) -> None:
    """Upsert the prompt_environment_active row for (prompt_id, environment)."""
    from api.models import PromptVersion
    # Resolve version UUID
    v_result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.version_num == version_num,
        )
    )
    pv = v_result.scalar_one_or_none()
    if pv is None:
        # Version not in registry yet — skip the upsert
        return

    existing = await db.execute(
        select(PromptEnvironmentActive).where(
            PromptEnvironmentActive.prompt_id == prompt_id,
            PromptEnvironmentActive.environment == environment,
        )
    )
    row = existing.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row:
        row.prompt_version_id = pv.id
        row.version_num = version_num
        row.activated_by = activated_by
        row.activated_at = now
    else:
        db.add(
            PromptEnvironmentActive(
                id=str(uuid.uuid4()),
                prompt_id=prompt_id,
                environment=environment,
                prompt_version_id=pv.id,
                version_num=version_num,
                activated_by=activated_by,
                activated_at=now,
            )
        )
