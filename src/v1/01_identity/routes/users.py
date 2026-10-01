from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import require_permission
from exceptions import PreconditionRequiredError
from schemas.common import PaginatedResponse
from schemas.user import (
    InvitationResponse,
    UserDeactivateRequest,
    UserInviteRequest,
    UserPermissionsReplace,
    UserPermissionsResponse,
    UserResponse,
    UserStatus,
    UserUpdateRequest,
)
from services.access_control import Actor
from services.user_service import (
    PERM_ACCESS_MANAGE,
    PERM_ACCESS_READ,
    PERM_CREATE,
    PERM_DEACTIVATE,
    PERM_READ,
    PERM_UPDATE,
    user_service,
)

router = APIRouter()


def _require_if_match(if_match: Optional[str], action: str) -> str:
    if not if_match:
        raise PreconditionRequiredError(f"If-Match header with the user's ETag is required to {action}")
    return if_match


def _etag(user: UserResponse) -> str:
    return f'"{user.version}"'


@router.get(
    "",
    response_model=PaginatedResponse[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List users",
)
async def list_users(
    status: Optional[UserStatus] = Query(None, description="Filter by status"),
    unit_id: Optional[uuid.UUID] = Query(None, description="Members of this unit (including sub-units)"),
    role_code: Optional[str] = Query(None, description="Users given this role preset"),
    q: Optional[str] = Query(None, max_length=255, description="Search by name, email or employee code"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    actor: Actor = Depends(require_permission(PERM_READ)),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[UserResponse]:
    return await user_service.list_users(
        session=db, actor=actor, status=status, unit_id=unit_id, role_code=role_code,
        q=q, limit=limit, cursor=cursor,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user",
)
async def invite_user(
    body: UserInviteRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_permission(PERM_CREATE)),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    user = await user_service.invite_user(session=db, actor=actor, data=body)
    response.headers["Location"] = f"/api/identity/v1/users/{user.id}"
    response.headers["ETag"] = _etag(user)
    return user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a user",
)
async def get_user(
    user_id: uuid.UUID,
    response: Response,
    actor: Actor = Depends(require_permission(PERM_READ)),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    user = await user_service.get_user(session=db, actor=actor, user_id=user_id)
    response.headers["ETag"] = _etag(user)
    return user


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a user",
)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    actor: Actor = Depends(require_permission(PERM_UPDATE)),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    user = await user_service.update_user(
        session=db, actor=actor, user_id=user_id, data=body,
        if_match=_require_if_match(if_match, "update it"),
    )
    response.headers["ETag"] = _etag(user)
    return user


@router.post(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate a user",
)
async def deactivate_user(
    user_id: uuid.UUID,
    body: UserDeactivateRequest,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    actor: Actor = Depends(require_permission(PERM_DEACTIVATE)),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    user = await user_service.deactivate_user(
        session=db, actor=actor, user_id=user_id, data=body,
        if_match=_require_if_match(if_match, "deactivate it"),
    )
    response.headers["ETag"] = _etag(user)
    return user


@router.post(
    "/{user_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Resend the invitation",
    description="Issues a new 72-hour activation link and emails it. The previous link stops working.",
)
async def resend_invitation(
    user_id: uuid.UUID,
    actor: Actor = Depends(require_permission(PERM_CREATE)),
    db: AsyncSession = Depends(get_db_session),
) -> InvitationResponse:
    return await user_service.resend_invitation(session=db, actor=actor, user_id=user_id)


@router.get(
    "/{user_id}/permissions",
    response_model=UserPermissionsResponse,
    status_code=status.HTTP_200_OK,
    summary="List a user's permissions",
)
async def get_user_permissions(
    user_id: uuid.UUID,
    actor: Actor = Depends(require_permission(PERM_ACCESS_READ)),
    db: AsyncSession = Depends(get_db_session),
) -> UserPermissionsResponse:
    return await user_service.get_permissions(session=db, actor=actor, user_id=user_id)


@router.put(
    "/{user_id}/permissions",
    response_model=UserPermissionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a user's permissions",
    description=(
        "Sets the user's complete permission set. Role presets in `role_assignments` expand into "
        "permissions. You can only grant or remove access you hold yourself, at least as broadly."
    ),
)
async def replace_user_permissions(
    user_id: uuid.UUID,
    body: UserPermissionsReplace,
    actor: Actor = Depends(require_permission(PERM_ACCESS_MANAGE)),
    db: AsyncSession = Depends(get_db_session),
) -> UserPermissionsResponse:
    return await user_service.replace_permissions(session=db, actor=actor, user_id=user_id, data=body)
