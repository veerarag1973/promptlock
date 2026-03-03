"""roles router — /v1/orgs/{org_id}/roles (spec §4.6, §4.3).

Endpoints::

    GET    /v1/orgs/{org_id}/roles                    -- list role assignments
    POST   /v1/orgs/{org_id}/roles                    -- assign a role
    DELETE /v1/orgs/{org_id}/roles/{assignment_id}    -- revoke a role
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import audit as audit_module
from api.dependencies import get_db
from api.models import Role, RoleAssignment, User
from api.rbac import assign_role, require_roles, revoke_role
from api.schemas import AssignRoleRequest, RoleAssignmentResponse

router = APIRouter(prefix="/v1/orgs", tags=["roles"])


def _assignment_to_response(a: RoleAssignment, role_name: str) -> RoleAssignmentResponse:
    return RoleAssignmentResponse(
        id=a.id,
        user_id=a.user_id,
        role_name=role_name,
        scope_id=a.scope_id,
        scope_type=a.scope_type,
        created_by=a.created_by,
        created_at=a.created_at,
    )


# ---------------------------------------------------------------------------
# GET /v1/orgs/{org_id}/roles
# ---------------------------------------------------------------------------


@router.get("/{org_id}/roles", response_model=list[RoleAssignmentResponse])
async def list_role_assignments(
    org_id: str,
    current_user: User = Depends(require_roles("Admin", "Org Admin")),
    db: AsyncSession = Depends(get_db),
) -> list[RoleAssignmentResponse]:
    """List all role assignments scoped to *org_id*.

    Requires the **Admin** or **Org Admin** role.  Callers can only see
    assignments within their own org.
    """
    if current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this org's roles is not permitted.",
        )

    result = await db.execute(
        select(RoleAssignment, Role.name)
        .join(Role, Role.id == RoleAssignment.role_id)
        .where(RoleAssignment.scope_id == org_id)
        .order_by(RoleAssignment.created_at)
    )
    rows = result.all()
    return [_assignment_to_response(a, name) for a, name in rows]


# ---------------------------------------------------------------------------
# POST /v1/orgs/{org_id}/roles
# ---------------------------------------------------------------------------


@router.post(
    "/{org_id}/roles",
    response_model=RoleAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_role_assignment(
    org_id: str,
    body: AssignRoleRequest,
    request: Request,
    current_user: User = Depends(require_roles("Admin", "Org Admin")),
    db: AsyncSession = Depends(get_db),
) -> RoleAssignmentResponse:
    """Assign a role to a user at the given scope.

    Requires the **Admin** or **Org Admin** role.  Idempotent — returns
    the existing assignment if one already exists.
    """
    if current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this org's roles is not permitted.",
        )

    # Validate role name
    result = await db.execute(select(Role).where(Role.name == body.role_name))
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown role: '{body.role_name}'.",
        )

    assignment = await assign_role(
        user_id=body.user_id,
        role_name=body.role_name,
        scope_id=body.scope_id,
        scope_type=body.scope_type,
        db=db,
        created_by=current_user.id,
    )

    await audit_module.emit(
        db,
        event_type="x.promptlock.role.assigned",
        payload={
            "target_user_id": body.user_id,
            "role_name": body.role_name,
            "scope_id": body.scope_id,
            "scope_type": body.scope_type,
        },
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=current_user.org_id,
        resource_type="role_assignment",
        resource_id=assignment.id,
    )

    return _assignment_to_response(assignment, body.role_name)


# ---------------------------------------------------------------------------
# DELETE /v1/orgs/{org_id}/roles/{assignment_id}
# ---------------------------------------------------------------------------


@router.delete("/{org_id}/roles/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role_assignment(
    org_id: str,
    assignment_id: str,
    request: Request,
    current_user: User = Depends(require_roles("Admin", "Org Admin")),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a role assignment.

    Requires the **Admin** or **Org Admin** role.
    """
    if current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to this org's roles is not permitted.",
        )

    removed = await revoke_role(assignment_id, db)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role assignment not found.",
        )

    await audit_module.emit(
        db,
        event_type="x.promptlock.role.revoked",
        payload={"assignment_id": assignment_id},
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        actor_ip=request.client.host if request.client else None,
        org_id=current_user.org_id,
        resource_type="role_assignment",
        resource_id=assignment_id,
    )
