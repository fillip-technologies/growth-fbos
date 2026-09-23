from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_current_user
from exceptions import PreconditionRequiredError
from schemas.common import PaginatedResponse
from schemas.token import TokenPayload
from schemas.user import (
    UserDeactivateRequest,
    UserInviteRequest,
    UserResponse,
    UserUpdateRequest,
)
from services.user_service import user_service

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List users",
)
async def list_users(
    status: Optional[str] = Query(None, description="Filter by status (invited, active, suspended, deactivated)"),
    unit_id: Optional[uuid.UUID] = Query(None, description="Filter by home unit id"),
    role_code: Optional[str] = Query(None, description="Filter by role code"),
    q: Optional[str] = Query(None, description="Search by name, email or employee code"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[UserResponse]:
    return await user_service.list_users(
        session=db,
        organization_id=current_user.organization_id,
        status=status,
        unit_id=unit_id,
        role_code=role_code,
        q=q,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user",
)
async def invite_user(
    body: UserInviteRequest,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    return await user_service.invite_user(
        session=db,
        organization_id=current_user.organization_id,
        data=body,
        actor_id=current_user.user_id,
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a user",
)
async def get_user(
    user_id: uuid.UUID,
    response: Response,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    user = await user_service.get_user(
        session=db, user_id=user_id, organization_id=current_user.organization_id
    )
    response.headers["ETag"] = f'"{user.version}"'
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
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    if not if_match:
        raise PreconditionRequiredError("If-Match header with ETag version is required for updates")

    user = await user_service.update_user(
        session=db,
        user_id=user_id,
        organization_id=current_user.organization_id,
        data=body,
        if_match=if_match,
    )
    response.headers["ETag"] = f'"{user.version}"'
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
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    if not if_match:
        raise PreconditionRequiredError("If-Match header with ETag version is required to deactivate")

    user = await user_service.deactivate_user(
        session=db,
        user_id=user_id,
        organization_id=current_user.organization_id,
        data=body,
        if_match=if_match,
        actor_id=current_user.user_id,
    )
    response.headers["ETag"] = f'"{user.version}"'
    return user
