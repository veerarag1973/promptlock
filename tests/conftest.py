"""Root conftest — patches postgresql.JSONB → sa.JSON so that all ORM models
work with an in-memory SQLite database (aiosqlite) during tests.

This file is loaded by pytest before any test module, which means the patch
is in place before ``api.models`` is first imported.
"""

import os

# ── Point SQLAlchemy at an in-memory SQLite DB for API tests ────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUDIT_SIGNING_KEY", "audit-test-key")

# ── Patch JSONB → JSON so SQLite can store the column types ─────────────────
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

postgresql.JSONB = sa.JSON  # type: ignore[attr-defined]
