"""Approval-workflow endpoints (v0.5) — spec §4.4.

Endpoints::

    POST /v1/promotions/{id}/reviews  -- Reviewer submits approve / reject
    POST /v1/promotions/{id}/execute  -- Deployer executes an approved promotion
    POST /v1/promotions/{id}/bypass   -- Org Admin bypasses all review gates

Separation-of-duties rules enforced here:
  • A Reviewer cannot review their own promotion request.
  • A Deployer cannot execute a promotion they reviewed.
  • Bypass requires Org Admin and emits a high-severity audit event.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import audit
from api.dependencies import get_current_user, get_db
from api.models import (
    Prompt,
    PromotionRequest,
    PromotionReview,
    PromptEnvironmentActive,
    PromptVersion,
    User,
)
from api.rbac import require_roles
from api.schemas import (
    BypassApprovalRequest,
    ExecutePromotionRequest,
    PromotionResponse,
    PromotionReviewRequest,
    PromotionReviewResponse,
)

router = APIRouter(prefix="/v1/promotions", tags=["approvals"])


# ---------------------------------------------------------------------------
# Helper — shared upsert (mirrors environments._upsert_active)
# ---------------------------------------------------------------------------

async def _upsert_active(
    db: AsyncSession,
    prompt_id: str,
    environment: str,
    version_num: int,
    activated_by: Optional[str],
) -> None:
    """Upsert the prompt_environment_active row for (prompt_id, environment)."""
    v_result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.version_num == version_num,
        )
    )
    pv = v_result.scalar_one_or_none()
    if pv is None:
        return  # version not yet in registry — skip silently

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


def _promo_to_response(p: PromotionRequest) -> PromotionResponse:
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
        required_approvals=p.required_approvals,
        created_at=p.created_at,
        resolved_at=p.resolved_at,
    )


async def _get_promo_for_org(
    promotion_id: str, org_id: str, db: AsyncSession
) -> PromotionRequest:
    result = await db.execute(
        select(PromotionRequest).where(
            PromotionRequest.id == promotion_id,
            PromotionRequest.org_id == org_id,
        )
    )
    promo = result.scalar_one_or_none()
    if promo is None:
        raise HTTPException(status_code=404, detail="Promotion request not found.")
    return promo


# ---------------------------------------------------------------------------
# POST /v1/promotions/{id}/reviews
# ---------------------------------------------------------------------------


@router.post(
    "/{promotion_id}/reviews",
    response_model=PromotionReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_review(
    promotion_id: str,
    body: PromotionReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("Reviewer", "Org Admin")),
) -> PromotionReviewResponse:
    """Submit an approve or reject decision for a pending promotion request.

    Rules enforced:
    - The reviewer cannot be the same user who submitted the promotion.
    - A reviewer can only submit one decision per promotion.
    - If approved reviews reach ``required_approvals``, the status advances to
      ``"approved"``.
    - Any rejection immediately sets the status to ``"rejected"``.
    """
    promo = await _get_promo_for_org(promotion_id, current_user.org_id, db)

    if promo.status not in ("pending",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot review a promotion with status '{promo.status}'.",
        )

    # Separation of duties: reviewer ≠ requester
    if promo.requested_by == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot review your own promotion request.",
        )

    # Prevent duplicate review by the same reviewer
    dup_result = await db.execute(
        select(PromotionReview).where(
            PromotionReview.promotion_request_id == promotion_id,
            PromotionReview.reviewer_id == current_user.id,
        )
    )
    if dup_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this promotion request.",
        )

    review = PromotionReview(
        id=str(uuid.uuid4()),
        promotion_request_id=promotion_id,
        reviewer_id=current_user.id,
        reviewer_email=current_user.email,
        decision=body.decision,
        comment=body.comment,
    )
    db.add(review)
    await db.flush()

    # Update promotion status based on decision
    if body.decision == "rejected":
        promo.status = "rejected"
        promo.resolved_at = datetime.now(timezone.utc)
        promo.comment = body.comment
        event_type = "llm.prompt.rejected"
    else:
        # Count total approved reviews (including this one)
        count_result = await db.execute(
            select(PromotionReview).where(
                PromotionReview.promotion_request_id == promotion_id,
                PromotionReview.decision == "approved",
            )
        )
        approved_count = len(count_result.scalars().all())
        if approved_count >= promo.required_approvals:
            promo.status = "approved"
            promo.resolved_at = datetime.now(timezone.utc)
        event_type = "llm.prompt.approved"

    await audit.emit(
        db,
        event_type=event_type,
        payload={
            "promotion_id": promotion_id,
            "prompt_path": promo.prompt_path,
            "decision": body.decision,
            "comment": body.comment,
            "approvals_so_far": (
                len((await db.execute(
                    select(PromotionReview).where(
                        PromotionReview.promotion_request_id == promotion_id,
                        PromotionReview.decision == "approved",
                    )
                )).scalars().all())
                if body.decision == "approved" else 0
            ),
        },
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=current_user.org_id,
        resource_type="promotion",
        resource_id=promotion_id,
    )

    await db.commit()
    await db.refresh(review)
    return PromotionReviewResponse(
        id=review.id,
        promotion_request_id=review.promotion_request_id,
        reviewer_id=review.reviewer_id,
        reviewer_email=review.reviewer_email,
        decision=review.decision,
        comment=review.comment,
        created_at=review.created_at,
    )


# ---------------------------------------------------------------------------
# POST /v1/promotions/{id}/execute
# ---------------------------------------------------------------------------


@router.post(
    "/{promotion_id}/execute",
    response_model=PromotionResponse,
)
async def execute_promotion(
    promotion_id: str,
    body: ExecutePromotionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("Deployer", "Org Admin")),
) -> PromotionResponse:
    """Execute an approved promotion — actually activates the prompt version.

    Rules enforced:
    - Promotion must be in ``"approved"`` status.
    - Executor must not have submitted a review for this promotion.
    """
    promo = await _get_promo_for_org(promotion_id, current_user.org_id, db)

    if promo.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot execute a promotion with status '{promo.status}'. "
                   "The promotion must be approved by a Reviewer first.",
        )

    # Separation of duties: executor must not be any reviewer
    reviewer_result = await db.execute(
        select(PromotionReview).where(
            PromotionReview.promotion_request_id == promotion_id,
            PromotionReview.reviewer_id == current_user.id,
        )
    )
    if reviewer_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot execute a promotion that you reviewed.",
        )

    # Activate the prompt version in the target environment
    if promo.prompt_id:
        await _upsert_active(
            db=db,
            prompt_id=promo.prompt_id,
            environment=promo.to_environment,
            version_num=promo.version_num,
            activated_by=current_user.id,
        )

    promo.status = "promoted"
    promo.resolved_at = datetime.now(timezone.utc)
    if body.comment:
        promo.comment = body.comment

    await audit.emit(
        db,
        event_type="llm.prompt.promoted",
        payload={
            "promotion_id": promotion_id,
            "prompt_path": promo.prompt_path,
            "from_environment": promo.from_environment,
            "to_environment": promo.to_environment,
            "version_num": promo.version_num,
            "sha256": promo.sha256,
            "executor": current_user.id,
        },
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=current_user.org_id,
        resource_type="prompt",
        resource_id=promo.prompt_id,
        resource_version=str(promo.version_num),
    )

    await db.commit()
    await db.refresh(promo)
    return _promo_to_response(promo)


# ---------------------------------------------------------------------------
# POST /v1/promotions/{id}/bypass
# ---------------------------------------------------------------------------


@router.post(
    "/{promotion_id}/bypass",
    response_model=PromotionResponse,
)
async def bypass_approval(
    promotion_id: str,
    body: BypassApprovalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("Org Admin")),
) -> PromotionResponse:
    """Bypass all review gates and immediately promote (Org Admin only).

    Emits a **high-severity** ``x.promptlock.approval.bypassed`` audit event
    that cannot be suppressed.  Use only in emergencies or CI/CD pipelines
    where the Org Admin has explicitly authorised the bypass.
    """
    promo = await _get_promo_for_org(promotion_id, current_user.org_id, db)

    if promo.status in ("promoted", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot bypass a promotion with status '{promo.status}'.",
        )

    # Activate immediately, skipping review
    if promo.prompt_id:
        await _upsert_active(
            db=db,
            prompt_id=promo.prompt_id,
            environment=promo.to_environment,
            version_num=promo.version_num,
            activated_by=current_user.id,
        )

    promo.status = "promoted"
    promo.resolved_at = datetime.now(timezone.utc)
    promo.comment = f"[BYPASSED] {body.reason}"

    # High-severity audit event — mandatory, not swallowed
    await audit.emit(
        db,
        event_type="x.promptlock.approval.bypassed",
        payload={
            "promotion_id": promotion_id,
            "prompt_path": promo.prompt_path,
            "from_environment": promo.from_environment,
            "to_environment": promo.to_environment,
            "version_num": promo.version_num,
            "bypassed_by": current_user.id,
            "reason": body.reason,
            "severity": "high",
        },
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=current_user.org_id,
        resource_type="promotion",
        resource_id=promotion_id,
    )

    await db.commit()
    await db.refresh(promo)
    return _promo_to_response(promo)
