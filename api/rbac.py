"""api.rbac — Role-Based Access Control for the promptlock API.

Seven roles scoped at org / team / project level (spec §4.3):

    Viewer       — Read prompt content and history only.
    Contributor  — Save new versions in non-production environments.
    Reviewer     — Approve/reject promotion requests; cannot self-approve.
    Deployer     — Promote approved versions to environments.
    Admin        — Manage team members, roles, project settings.
    Org Admin    — Manage SSO, billing, org-wide policies; full read access.
    Auditor      — Read-only access to all audit logs across the org.

Enforcement rules (spec §4.3):
  - Roles are additive and assigned at the most specific scope.
  - Separation of duties: no user can both create AND approve a version.
  - Org Admin role implicitly has all permissions at the org scope.
  - The first user who creates an org automatically becomes Org Admin.
"""

from __future__ import annotations

from typing import Sequence

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_db
from api.models import Role, RoleAssignment, User

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

ROLE_NAMES: list[str] = [
    "Viewer",
    "Contributor",
    "Reviewer",
    "Deployer",
    "Admin",
    "Org Admin",
    "Auditor",
]

# Hierarchical permissions per role
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Viewer": {"read:prompts", "read:environments"},
    "Contributor": {"read:prompts", "read:environments", "write:prompts", "write:environments"},
    "Reviewer": {"read:prompts", "read:environments", "review:promotions"},
    "Deployer": {"read:prompts", "read:environments", "promote:prompts"},
    "Admin": {
        "read:prompts", "read:environments", "write:prompts", "write:environments",
        "review:promotions", "promote:prompts", "manage:members", "assign:roles",
    },
    "Org Admin": {"*"},  # wildcard — all permissions
    "Auditor": {"read:audit", "export:audit"},
}

# Roles that carry the wildcard permission (all-access)
_SUPERROLES = {"Org Admin"}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def seed_roles(db: AsyncSession) -> None:
    """Ensure all seven role rows exist in the DB.

    Called once at application startup.  Idempotent — safe to call on
    every restart.
    """
    existing = await db.execute(select(Role.name))
    existing_names = {row[0] for row in existing.fetchall()}

    for role_name in ROLE_NAMES:
        if role_name not in existing_names:
            scope = "org" if role_name in ("Org Admin", "Auditor") else "team"
            db.add(Role(name=role_name, scope_type=scope))

    await db.commit()


async def get_role_id(role_name: str, db: AsyncSession) -> str:
    """Return the PK of the named role.  Raises ValueError if not found."""
    result = await db.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()
    if role is None:
        raise ValueError(f"Role '{role_name}' not found in DB. Run seed_roles first.")
    return role.id


async def assign_role(
    user_id: str,
    role_name: str,
    scope_id: str,
    scope_type: str,
    db: AsyncSession,
    created_by: str | None = None,
) -> RoleAssignment:
    """Assign a role to a user at a given scope.

    Idempotent — returns the existing assignment if one already exists.
    """
    role_id = await get_role_id(role_name, db)

    existing = await db.execute(
        select(RoleAssignment).where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.role_id == role_id,
            RoleAssignment.scope_id == scope_id,
        )
    )
    existing_assignment = existing.scalar_one_or_none()
    if existing_assignment:
        return existing_assignment

    assignment = RoleAssignment(
        user_id=user_id,
        role_id=role_id,
        scope_id=scope_id,
        scope_type=scope_type,
        created_by=created_by,
    )
    db.add(assignment)
    await db.flush()
    return assignment


async def revoke_role(assignment_id: str, db: AsyncSession) -> bool:
    """Delete a role assignment.  Returns True if it existed."""
    result = await db.execute(
        select(RoleAssignment).where(RoleAssignment.id == assignment_id)
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        return False
    await db.delete(assignment)
    await db.flush()
    return True


async def get_user_role_names(
    user_id: str,
    db: AsyncSession,
) -> set[str]:
    """Return the set of all role names assigned to *user_id* at any scope."""
    result = await db.execute(
        select(Role.name)
        .join(RoleAssignment, RoleAssignment.role_id == Role.id)
        .where(RoleAssignment.user_id == user_id)
    )
    return {row[0] for row in result.fetchall()}


async def user_has_any_role(
    user: User,
    allowed_roles: Sequence[str],
    db: AsyncSession,
) -> bool:
    """Return True if *user* holds at least one of the *allowed_roles*."""
    role_names = await get_user_role_names(user.id, db)
    # Org Admin bypasses all role checks
    if role_names & _SUPERROLES:
        return True
    return bool(role_names & set(allowed_roles))


# ---------------------------------------------------------------------------
# FastAPI dependency factories
# ---------------------------------------------------------------------------


def require_roles(*allowed_roles: str):
    """FastAPI dependency that enforces role membership.

    Usage::

        @router.post("/something")
        async def my_endpoint(
            current_user: User = Depends(require_roles("Admin", "Org Admin")),
        ):
            ...
    """

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not await user_has_any_role(current_user, allowed_roles, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions. Required role(s): "
                    f"{', '.join(allowed_roles)}."
                ),
            )
        return current_user

    return _check
