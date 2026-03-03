"""Add prompt_environment_active and promotion_requests tables (v0.3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple | None = None
depends_on: str | tuple | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # prompt_environment_active
    # Tracks the currently active version of a prompt per environment.
    # There is at most one row per (prompt_id, environment) pair.
    # ------------------------------------------------------------------
    op.create_table(
        "prompt_environment_active",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "prompt_id",
            sa.String(36),
            sa.ForeignKey("prompts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(100), nullable=False),
        sa.Column(
            "prompt_version_id",
            sa.String(36),
            sa.ForeignKey("prompt_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_num", sa.Integer, nullable=False),
        sa.Column("activated_by", sa.String(36), nullable=True),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("prompt_id", "environment", name="uq_active_per_env"),
    )
    op.create_index("ix_pea_prompt_id", "prompt_environment_active", ["prompt_id"])
    op.create_index("ix_pea_environment", "prompt_environment_active", ["environment"])

    # ------------------------------------------------------------------
    # promotion_requests
    # Full promotion history — one row per promote action.
    # In v0.3 status is always "promoted".
    # In v0.5 status gains "pending" / "approved" / "rejected" with
    # reviewer FK columns.
    # ------------------------------------------------------------------
    op.create_table(
        "promotion_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "prompt_id",
            sa.String(36),
            sa.ForeignKey("prompts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("prompt_path", sa.String(1024), nullable=False),
        sa.Column("from_environment", sa.String(100), nullable=False),
        sa.Column("to_environment", sa.String(100), nullable=False),
        sa.Column("version_num", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("requested_by", sa.String(36), nullable=True),
        # status: promoted (v0.3) | pending | approved | rejected (v0.5+)
        sa.Column("status", sa.String(50), nullable=False, server_default="promoted"),
        sa.Column("comment", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pr_prompt_id", "promotion_requests", ["prompt_id"])
    op.create_index("ix_pr_org_id", "promotion_requests", ["org_id"])
    op.create_index("ix_pr_created_at", "promotion_requests", ["created_at"])
    op.create_index("ix_pr_status", "promotion_requests", ["status"])


def downgrade() -> None:
    op.drop_table("promotion_requests")
    op.drop_table("prompt_environment_active")
