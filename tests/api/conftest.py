"""API test fixtures — in-memory SQLite, overridden get_db, AsyncClient."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

# Root conftest.py has already set DATABASE_URL, JWT_SECRET, AUDIT_SIGNING_KEY
# and patched postgresql.JSONB → sa.JSON before we import any api modules.

from api.main import app
from api.database import Base
from api.dependencies import get_db

# ---------------------------------------------------------------------------
# Single shared in-memory SQLite engine for ALL API tests
# Using StaticPool so every connection uses the same in-process database.
# ---------------------------------------------------------------------------

TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = async_sessionmaker(
    TEST_ENGINE,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Create tables once per test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
async def create_tables():
    """Create all ORM tables once for the session."""
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
async def clear_tables():
    """Truncate all rows between tests so each test starts with a clean DB."""
    yield
    async with TEST_ENGINE.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


# ---------------------------------------------------------------------------
# Per-test DB session + dependency override
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    """Provide a fresh async DB session per test."""
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession):
    """Return an AsyncClient wired to the FastAPI app with the test DB."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c
    app.dependency_overrides.clear()
