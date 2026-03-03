"""Initial schema — all tables for v0.2 including RBAC/audit placeholders.

Revision ID: 0001
Revises:
Create Date: 2026-03-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple | None = None
depends_on: str | tuple | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # orgs
    # ------------------------------------------------------------------
    op.create_table(
        "orgs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("plan", sa.String(50), nullable=False, server_default="oss"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # ------------------------------------------------------------------
    # teams
    # ------------------------------------------------------------------
    op.create_table(
        "teams",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "slug", name="uq_team_org_slug"),
    )
    op.create_index("ix_teams_org_id", "teams", ["org_id"])

    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("team_id", sa.String(36), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("team_id", "slug", name="uq_project_team_slug"),
    )
    op.create_index("ix_projects_team_id", "projects", ["team_id"])
    op.create_index("ix_projects_org_id", "projects", ["org_id"])

    # ------------------------------------------------------------------
    # prompts
    # ------------------------------------------------------------------
    op.create_table(
        "prompts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "path", name="uq_prompt_org_path"),
    )
    op.create_index("ix_prompts_org_id", "prompts", ["org_id"])
    op.create_index("ix_prompts_path", "prompts", ["path"])

    # ------------------------------------------------------------------
    # prompt_versions
    # ------------------------------------------------------------------
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prompt_id", sa.String(36), sa.ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_num", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_url", sa.String(1024), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("author_email", sa.String(255), nullable=True),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("environment", sa.String(50), nullable=False, server_default="development"),
        sa.Column("model_target", sa.String(255), nullable=True),
        sa.Column("parent_version_id", sa.String(36), sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("prompt_id", "version_num", name="uq_version_num"),
    )
    op.create_index("ix_pv_prompt_id", "prompt_versions", ["prompt_id"])
    op.create_index("ix_pv_sha256", "prompt_versions", ["sha256"])

    # ------------------------------------------------------------------
    # tags
    # ------------------------------------------------------------------
    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prompt_version_id", sa.String(36), sa.ForeignKey("prompt_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("prompt_version_id", "name", name="uq_tag_per_version"),
    )
    op.create_index("ix_tags_pv_id", "tags", ["prompt_version_id"])

    # ------------------------------------------------------------------
    # environments (Phase 3 CLI; schema here per spec §8 Scope Rule)
    # ------------------------------------------------------------------
    op.create_table(
        "environments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(50), nullable=False, server_default="custom"),
        sa.Column("config_json", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", "name", name="uq_env_org_name"),
    )

    # ------------------------------------------------------------------
    # RBAC (Phase 4 enforcement; schema here per spec §8 Scope Rule)
    # ------------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=False),
    )

    op.create_table(
        "role_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ra_user_id", "role_assignments", ["user_id"])
    op.create_index("ix_ra_scope_id", "role_assignments", ["scope_id"])

    op.create_table(
        "service_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("scopes_json", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # audit_events — immutable, append-only, llm-toolkit-schema format
    # ------------------------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(26), unique=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("actor_ip", sa.String(45), nullable=True),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("resource_version", sa.String(50), nullable=True),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("team_id", sa.String(36), nullable=True),
        sa.Column("payload_json", postgresql.JSONB, nullable=False),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("signature", sa.String(128), nullable=True),
        sa.Column("prev_event_id", sa.String(26), nullable=True),
    )
    op.create_index("ix_ae_event_id", "audit_events", ["event_id"])
    op.create_index("ix_ae_timestamp", "audit_events", ["timestamp"])
    op.create_index("ix_ae_event_type", "audit_events", ["event_type"])
    op.create_index("ix_ae_org_id", "audit_events", ["org_id"])
    op.create_index("ix_ae_resource_id", "audit_events", ["resource_id"])
    op.create_index("ix_ae_actor", "audit_events", ["actor_user_id"])

    # ------------------------------------------------------------------
    # Seed default RBAC roles (spec §4.3)
    # ------------------------------------------------------------------
    op.execute("""
        INSERT INTO roles (id, name, scope_type) VALUES
        (gen_random_uuid()::text, 'Viewer',    'org'),
        (gen_random_uuid()::text, 'Contributor','team'),
        (gen_random_uuid()::text, 'Reviewer',  'team'),
        (gen_random_uuid()::text, 'Deployer',  'project'),
        (gen_random_uuid()::text, 'Admin',     'team'),
        (gen_random_uuid()::text, 'OrgAdmin',  'org'),
        (gen_random_uuid()::text, 'Auditor',   'org')
    """)

    # Seed standard environments per org (added in trigger / app logic in v0.3)
    # Schema is ready; ENV seeding happens at org creation time.


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("service_accounts")
    op.drop_table("role_assignments")
    op.drop_table("roles")
    op.drop_table("environments")
    op.drop_table("tags")
    op.drop_table("prompt_versions")
    op.drop_table("prompts")
    op.drop_table("projects")
    op.drop_table("teams")
    op.drop_table("sessions")
    op.drop_table("users")
    op.drop_table("orgs")
