"""prompts router — /v1/prompts/* endpoints."""

from __future__ import annotations

import base64
import io
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api import audit
from api.config import settings
from api.dependencies import get_current_user, get_db
from api.models import Prompt, PromptVersion, Tag, User
from api.schemas import (
    CreatePromptRequest,
    PaginatedPrompts,
    PaginatedVersions,
    PromptResponse,
    VersionResponse,
)

router = APIRouter(prefix="/v1/prompts", tags=["prompts"])


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )


def _s3_key(sha256: str) -> str:
    """Content-addressed S3 key — same deduplication model as the local store."""
    return f"objects/{sha256[:2]}/{sha256[2:]}"


def _prompt_response(p: Prompt) -> PromptResponse:
    return PromptResponse(
        id=p.id,
        org_id=p.org_id,
        project_id=p.project_id,
        name=p.name,
        path=p.path,
        description=p.description,
        created_at=p.created_at,
    )


def _version_response(v: PromptVersion, include_content: bool = False) -> VersionResponse:
    content_b64 = None
    if include_content:
        try:
            s3 = _s3_client()
            obj = s3.get_object(Bucket=settings.s3_bucket, Key=v.content_url)
            content_b64 = base64.b64encode(obj["Body"].read()).decode()
        except Exception:
            pass

    return VersionResponse(
        id=v.id,
        prompt_id=v.prompt_id,
        version_num=v.version_num,
        sha256=v.sha256,
        author_email=v.author_email,
        message=v.message,
        environment=v.environment,
        tags=[t.name for t in (v.tags or [])],
        created_at=v.created_at,
        content_base64=content_b64,
    )


# ---------------------------------------------------------------------------
# POST /v1/prompts
# ---------------------------------------------------------------------------


@router.post("", response_model=PromptResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt(
    body: CreatePromptRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PromptResponse:
    """Create a prompt resource in the registry.

    Idempotent — returns the existing record if ``path`` already exists
    for this org (status 200, not 201).
    """
    existing = await db.execute(
        select(Prompt).where(
            Prompt.org_id == current_user.org_id,
            Prompt.path == body.path,
        )
    )
    existing_prompt = existing.scalar_one_or_none()
    if existing_prompt:
        # Return existing — clients call create_prompt before push
        return _prompt_response(existing_prompt)

    prompt = Prompt(
        org_id=current_user.org_id,
        name=body.name,
        path=body.path,
        description=body.description,
    )
    db.add(prompt)
    await db.flush()

    await audit.emit(
        db,
        event_type="llm.prompt.saved",
        payload={"action": "prompt.created", "path": body.path, "prompt_id": prompt.id},
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=current_user.org_id,
        resource_type="prompt",
        resource_id=prompt.id,
    )

    return _prompt_response(prompt)


# ---------------------------------------------------------------------------
# GET /v1/prompts
# ---------------------------------------------------------------------------


@router.get("", response_model=PaginatedPrompts)
async def list_prompts(
    cursor: Optional[str] = None,
    limit: int = 50,
    path: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedPrompts:
    """List prompts for the authenticated org (cursor-paginated)."""
    query = select(Prompt).where(Prompt.org_id == current_user.org_id)
    if path:
        query = query.where(Prompt.path == path)
    if cursor:
        query = query.where(Prompt.id > cursor)
    query = query.order_by(Prompt.id).limit(limit + 1)

    result = await db.execute(query)
    prompts = result.scalars().all()

    next_cursor = None
    if len(prompts) > limit:
        prompts = list(prompts[:limit])
        next_cursor = prompts[-1].id

    return PaginatedPrompts(
        items=[_prompt_response(p) for p in prompts],
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# POST /v1/prompts/{prompt_id}/versions
# ---------------------------------------------------------------------------


@router.post("/{prompt_id}/versions", response_model=VersionResponse, status_code=status.HTTP_201_CREATED)
async def push_version(
    prompt_id: str,
    request: Request,
    content: UploadFile = File(...),
    sha256: str = Form(...),
    version_num: int = Form(...),
    message: str = Form(default=""),
    author: str = Form(default=""),
    environment: str = Form(default="development"),
    tags: str = Form(default=""),  # comma-separated
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VersionResponse:
    """Push a new version blob to the registry.

    Idempotent: if a version with the same ``sha256`` already exists for
    this prompt, returns the existing record (HTTP 200) instead of
    creating a duplicate.
    """
    # Verify prompt belongs to this org
    prompt_result = await db.execute(
        select(Prompt).where(
            Prompt.id == prompt_id,
            Prompt.org_id == current_user.org_id,
        )
    )
    prompt = prompt_result.scalar_one_or_none()
    if prompt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found.")

    # Idempotency check — deduplicate by SHA-256 within this prompt
    existing_v = await db.execute(
        select(PromptVersion)
        .options(selectinload(PromptVersion.tags))
        .where(
            PromptVersion.prompt_id == prompt_id,
            PromptVersion.sha256 == sha256,
        )
    )
    existing_version = existing_v.scalar_one_or_none()
    if existing_version:
        return _version_response(existing_version)

    # Upload content to S3 / MinIO
    content_bytes = await content.read()
    s3_key = _s3_key(sha256)
    try:
        s3 = _s3_client()
        s3.put_object(
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=content_bytes,
            ContentType="text/plain; charset=utf-8",
        )
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Object storage unavailable: {e}",
        )

    # Persist version record
    tag_names = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    version = PromptVersion(
        prompt_id=prompt_id,
        version_num=version_num,
        sha256=sha256,
        content_url=s3_key,
        author_id=current_user.id,
        author_email=author or current_user.email,
        message=message,
        environment=environment,
    )
    db.add(version)
    await db.flush()

    for tag_name in tag_names:
        db.add(Tag(prompt_version_id=version.id, name=tag_name))

    # Emit llm-toolkit-schema audit event
    await audit.emit(
        db,
        event_type="llm.prompt.saved",
        payload={
            "prompt_id": prompt.path,
            "version": f"v{version_num}",
            "environment": environment,
            "template_hash": sha256,
            "author": author or current_user.email,
        },
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=current_user.org_id,
        resource_type="prompt_version",
        resource_id=version.id,
        resource_version=f"v{version_num}",
    )

    version_with_tags = await db.execute(
        select(PromptVersion)
        .options(selectinload(PromptVersion.tags))
        .where(PromptVersion.id == version.id)
    )
    return _version_response(version_with_tags.scalar_one())


# ---------------------------------------------------------------------------
# GET /v1/prompts/{prompt_id}/versions
# ---------------------------------------------------------------------------


@router.get("/{prompt_id}/versions", response_model=PaginatedVersions)
async def list_versions(
    prompt_id: str,
    cursor: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedVersions:
    """List all versions of a prompt (cursor-paginated)."""
    # Verify ownership
    prompt_result = await db.execute(
        select(Prompt).where(
            Prompt.id == prompt_id,
            Prompt.org_id == current_user.org_id,
        )
    )
    if prompt_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found.")

    query = (
        select(PromptVersion)
        .options(selectinload(PromptVersion.tags))
        .where(PromptVersion.prompt_id == prompt_id)
    )
    if cursor:
        query = query.where(PromptVersion.id > cursor)
    query = query.order_by(PromptVersion.version_num).limit(limit + 1)

    result = await db.execute(query)
    versions = result.scalars().all()

    next_cursor = None
    if len(versions) > limit:
        versions = list(versions[:limit])
        next_cursor = versions[-1].id

    return PaginatedVersions(
        items=[_version_response(v, include_content=True) for v in versions],
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# GET /v1/prompts/{prompt_id}/versions/{version}
# ---------------------------------------------------------------------------


@router.get("/{prompt_id}/versions/{version}", response_model=VersionResponse)
async def get_version(
    prompt_id: str,
    version: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VersionResponse:
    """Fetch a specific version by number or 'latest'."""
    # Verify ownership
    prompt_result = await db.execute(
        select(Prompt).where(
            Prompt.id == prompt_id,
            Prompt.org_id == current_user.org_id,
        )
    )
    if prompt_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found.")

    query = (
        select(PromptVersion)
        .options(selectinload(PromptVersion.tags))
        .where(PromptVersion.prompt_id == prompt_id)
    )
    if version == "latest":
        query = query.order_by(PromptVersion.version_num.desc()).limit(1)
    else:
        try:
            v_num = int(version.lstrip("v"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Version must be a number or 'latest'.")
        query = query.where(PromptVersion.version_num == v_num)

    result = await db.execute(query)
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    return _version_response(v, include_content=True)
