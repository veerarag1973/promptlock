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
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    timestamp: datetime
