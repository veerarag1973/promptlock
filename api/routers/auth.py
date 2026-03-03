"""auth router — /v1/auth/* endpoints."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import audit
from api.config import settings
from api.dependencies import get_current_user, get_db
from api.models import Org, Session, User
from api.schemas import LoginRequest, MeResponse, RegisterRequest, TokenResponse

router = APIRouter(prefix="/v1/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _make_token(user_id: str, org_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    return jwt.encode(
        {"sub": user_id, "org": org_id, "exp": expire},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:100]


# ---------------------------------------------------------------------------
# POST /v1/auth/register
# ---------------------------------------------------------------------------


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Create a new organisation and user account."""
    # Check for existing email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    org = Org(name=body.org_name, slug=_slug(body.org_name))
    db.add(org)
    await db.flush()  # get org.id

    user = User(
        org_id=org.id,
        email=body.email,
        password_hash=_hash_password(body.password),
    )
    db.add(user)
    await db.flush()

    token = _make_token(user.id, org.id)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = Session(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.jwt_expire_minutes),
    )
    db.add(session)

    # Emit audit event
    await audit.emit(
        db,
        event_type="llm.prompt.saved",  # closest available; use x.* in future phases
        payload={"action": "user.registered", "email": body.email, "org_id": org.id},
        actor_user_id=user.id,
        actor_email=body.email,
        actor_ip=request.client.host if request.client else None,
        org_id=org.id,
        resource_type="user",
        resource_id=user.id,
    )

    return TokenResponse(
        access_token=token,
        org_id=org.id,
        email=user.email,
    )


# ---------------------------------------------------------------------------
# POST /v1/auth/login
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and return a JWT access token."""
    result = await db.execute(select(User).where(User.email == body.email))
    user: User | None = result.scalar_one_or_none()

    if user is None or not _verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    token = _make_token(user.id, user.org_id)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = Session(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.jwt_expire_minutes),
    )
    db.add(session)

    await audit.emit(
        db,
        event_type="llm.prompt.saved",
        payload={"action": "user.login", "email": body.email},
        actor_user_id=user.id,
        actor_email=user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=user.org_id,
        resource_type="user",
        resource_id=user.id,
    )

    return TokenResponse(
        access_token=token,
        org_id=user.org_id,
        email=user.email,
    )


# ---------------------------------------------------------------------------
# POST /v1/auth/logout
# ---------------------------------------------------------------------------


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke the current session token."""
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await db.execute(
            select(Session).where(
                Session.user_id == current_user.id,
                Session.token_hash == token_hash,
            )
        )
        session = result.scalar_one_or_none()
        if session:
            session.revoked = True


# ---------------------------------------------------------------------------
# GET /v1/auth/me
# ---------------------------------------------------------------------------


@router.get("/me", response_model=MeResponse)
async def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    """Return the authenticated user's profile."""
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        org_id=current_user.org_id,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
