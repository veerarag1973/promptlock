"""Pydantic v2 request/response schemas for the promptlock API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    org_name: str = Field(min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    org_id: str
    email: str


class MeResponse(BaseModel):
    id: str
    email: str
    org_id: str
    is_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


class CreatePromptRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1024)
    description: str = Field(default="", max_length=4096)


class PromptResponse(BaseModel):
    id: str
    org_id: str
    project_id: Optional[str] = None
    name: str
    path: str
    description: str
    created_at: datetime


class PaginatedPrompts(BaseModel):
    items: List[PromptResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None


# ---------------------------------------------------------------------------
# Prompt Versions
# ---------------------------------------------------------------------------


class VersionResponse(BaseModel):
    id: str
    prompt_id: str
    version_num: int
    sha256: str
    author_email: Optional[str] = None
    message: str
    environment: str
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    # Content is returned as base64 on pull so CLI can reconstruct blobs
    content_base64: Optional[str] = None


class PaginatedVersions(BaseModel):
    items: List[VersionResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None


# ---------------------------------------------------------------------------
# Environments (v0.3)
# ---------------------------------------------------------------------------


class CreateEnvironmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(default="custom", max_length=50)
    config_json: dict = Field(default_factory=dict)


class EnvironmentResponse(BaseModel):
    id: str
    org_id: str
    name: str
    type: str
    config_json: dict
    created_at: datetime


class PaginatedEnvironments(BaseModel):
    items: List[EnvironmentResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None


# ---------------------------------------------------------------------------
# Promotions (v0.3)
# ---------------------------------------------------------------------------


class CreatePromotionRequest(BaseModel):
    prompt_path: str = Field(min_length=1, max_length=1024)
    from_environment: str = Field(min_length=1, max_length=100)
    to_environment: str = Field(min_length=1, max_length=100)
    version_num: int = Field(ge=1)
    sha256: str = Field(default="", max_length=64)


class UpdatePromotionRequest(BaseModel):
    status: str = Field(pattern="^(approved|rejected)$")
    comment: str = Field(default="", max_length=4096)


class PromotionResponse(BaseModel):
    id: str
    prompt_id: Optional[str] = None
    prompt_path: str
    from_environment: str
    to_environment: str
    version_num: int
    sha256: str
    requested_by: Optional[str] = None
    status: str
    comment: str
    created_at: datetime
    resolved_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# RBAC (v0.4)
# ---------------------------------------------------------------------------


class AssignRoleRequest(BaseModel):
    user_id: str
    role_name: str = Field(min_length=1, max_length=100)
    scope_id: str = Field(min_length=1, max_length=36)
    scope_type: str = Field(default="org", pattern="^(org|team|project)$")


class RoleAssignmentResponse(BaseModel):
    id: str
    user_id: str
    role_name: str
    scope_id: str
    scope_type: str
    created_by: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Audit Log (v0.4)
# ---------------------------------------------------------------------------


class AuditEventResponse(BaseModel):
    id: str
    event_id: str
    timestamp: datetime
    event_type: str
    source: str
    actor_user_id: Optional[str] = None
    actor_email: Optional[str] = None
    actor_ip: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    resource_version: Optional[str] = None
    org_id: Optional[str] = None
    payload_json: Any
    checksum: Optional[str] = None
    signature: Optional[str] = None
    prev_event_id: Optional[str] = None


class PaginatedAuditEvents(BaseModel):
    items: List[AuditEventResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None


class PaginatedPromotions(BaseModel):
    items: List[PromotionResponse]
    next_cursor: Optional[str] = None
    total: Optional[int] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: datetime
