import secrets
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.session import get_db_session
from dependencies import get_actor, require_permission
from exceptions import PermissionDeniedError, PreconditionRequiredError
from schemas.common import PaginatedResponse
from schemas.rbac import (
    ActorResponse,
    GrantsResponse,
    PermissionResponse,
    RoleAssignmentCreate,
    RoleAssignmentResponse,
    RoleCreate,
    RolePermissionsReplace,
    RoleResponse,
)
from services.access_control import Actor
from services.auth_cache import auth_cache
from services.rbac_service import rbac_service

roles_router = APIRouter()
permissions_router = APIRouter()
role_assignments_router = APIRouter()
internal_router = APIRouter()


# ---------------------------------------------------------------------------
# Roles Endpoints
# ---------------------------------------------------------------------------

@roles_router.get(
    "",
    response_model=PaginatedResponse[RoleResponse],
    status_code=status.HTTP_200_OK,
    summary="List roles",
)
async def list_roles(
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    actor: Actor = Depends(require_permission("identity.role.read")),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[RoleResponse]:
    return await rbac_service.list_roles(
        session=db,
        organization_id=actor.organization_id,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


@roles_router.post(
    "",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role",
)
async def create_role(
    body: RoleCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_permission("identity.role.create")),
    db: AsyncSession = Depends(get_db_session),
) -> RoleResponse:
    role = await rbac_service.create_role(
        session=db,
        organization_id=actor.organization_id,
        data=body,
    )
    response.headers["Location"] = f"/api/identity/v1/roles/{role.id}"
    return role


@roles_router.put(
    "/{role_id}/permissions",
    response_model=RoleResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a role's permissions",
)
async def replace_role_permissions(
    role_id: uuid.UUID,
    body: RolePermissionsReplace,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    actor: Actor = Depends(require_permission("identity.role.update")),
    db: AsyncSession = Depends(get_db_session),
) -> RoleResponse:
    if not if_match:
        raise PreconditionRequiredError("If-Match header with ETag version is required to replace permissions")

    role = await rbac_service.replace_role_permissions(
        session=db,
        organization_id=actor.organization_id,
        role_id=role_id,
        data=body,
        if_match=if_match,
    )
    return role


# ---------------------------------------------------------------------------
# Permissions Endpoints
# ---------------------------------------------------------------------------

@permissions_router.get(
    "",
    response_model=PaginatedResponse[PermissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List the permission catalog",
)
async def list_permissions(
    service: Optional[str] = Query(None, description="Filter by owning service"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    actor: Actor = Depends(require_permission("identity.role.read")),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[PermissionResponse]:
    return await rbac_service.list_permissions(
        session=db,
        service=service,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


# ---------------------------------------------------------------------------
# Role Assignments Endpoints
# ---------------------------------------------------------------------------

@role_assignments_router.get(
    "",
    response_model=PaginatedResponse[RoleAssignmentResponse],
    status_code=status.HTTP_200_OK,
    summary="List role assignments",
)
async def list_role_assignments(
    user_id: Optional[uuid.UUID] = Query(None, description="Filter by user id"),
    scope_unit_id: Optional[uuid.UUID] = Query(None, description="Filter by scope unit id"),
    active: Optional[bool] = Query(None, description="Filter active assignments"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    actor: Actor = Depends(require_permission("identity.role_assignment.read")),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[RoleAssignmentResponse]:
    return await rbac_service.list_role_assignments(
        session=db,
        organization_id=actor.organization_id,
        user_id=user_id,
        scope_unit_id=scope_unit_id,
        active=active,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


@role_assignments_router.post(
    "",
    response_model=RoleAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a role within a scope",
)
async def create_role_assignment(
    body: RoleAssignmentCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_permission("identity.role_assignment.create")),
    db: AsyncSession = Depends(get_db_session),
) -> RoleAssignmentResponse:
    assignment = await rbac_service.create_role_assignment(session=db, actor=actor, data=body)
    response.headers["Location"] = f"/api/identity/v1/role-assignments/{assignment.id}"
    return assignment


@role_assignments_router.delete(
    "/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a role assignment",
)
async def revoke_role_assignment(
    assignment_id: uuid.UUID,
    reason: str = Query(..., description="Recorded in the audit trail"),
    actor: Actor = Depends(require_permission("identity.role_assignment.delete")),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    await rbac_service.revoke_role_assignment(
        session=db, actor=actor, assignment_id=assignment_id, reason=reason
    )


# ---------------------------------------------------------------------------
# Internal Grants Endpoint (Service-to-service)
# ---------------------------------------------------------------------------

@internal_router.get(
    "/authz/grants",
    response_model=GrantsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get effective grants for a user (internal)",
)
async def get_effective_grants(
    user_id: uuid.UUID = Query(..., description="User ID to compute grants for"),
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
    db: AsyncSession = Depends(get_db_session),
) -> GrantsResponse:
    _verify_internal_caller(x_fbos_internal_token)
    return await rbac_service.get_effective_grants(session=db, user_id=user_id)


@internal_router.get(
    "/authz/actor",
    response_model=ActorResponse,
    status_code=status.HTTP_200_OK,
    summary="Resolve the caller of another service (internal)",
)
async def resolve_actor(
    x_fbos_internal_token: Optional[str] = Header(None, alias="X-FBOS-Internal-Token"),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db_session),
) -> ActorResponse:
    """
    Other services forward the user's `Authorization` and `X-Organization-Id` headers here
    instead of trusting them: this runs the same checks as identity's own endpoints (token,
    revoked session, client lock, active user, organization within the client) and returns
    the organization the request acts in with the user's permission codes.
    """
    _verify_internal_caller(x_fbos_internal_token)
    own_records_only: list[str] = []
    if actor.is_superuser:
        permissions = await _permission_catalog(db)
    else:
        permissions = sorted({grant.permission for grant in actor.grants})
        # One grant beyond the user's own records (a unit or the whole company) lifts the limit.
        own_records_only = [code for code in permissions if all(g.self_only for g in actor.grants_for(code))]
    return ActorResponse(
        user_id=actor.user_id,
        organization_id=actor.organization_id,
        user_type=actor.user_type,
        name=actor.name,
        is_superuser=actor.is_superuser,
        permissions=permissions,
        own_records_only=own_records_only,
    )


async def _permission_catalog(db: AsyncSession) -> list[str]:
    """Every permission code (what a client admin holds); it only changes with a deploy."""
    epoch, cached = await auth_cache.permission_codes()
    if cached is not None:
        return cached
    codes = await rbac_service.list_permission_codes(session=db)
    await auth_cache.remember_permission_codes(epoch, codes)
    return codes


def _verify_internal_caller(token: Optional[str]) -> None:
    expected = settings.internal_service_token
    if not expected:
        if settings.app_env == "development":
            return
        raise PermissionDeniedError("internal", "Internal endpoints are disabled: INTERNAL_SERVICE_TOKEN is not set")
    if not token or not secrets.compare_digest(token, expected):
        raise PermissionDeniedError("internal", "A valid X-FBOS-Internal-Token is required")
