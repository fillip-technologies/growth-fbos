from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_client_ip, get_user_agent, require_permission
from exceptions import PreconditionRequiredError
from schemas.common import PaginatedResponse
from schemas.session import SessionResponse
from schemas.user import (
    InvitationResponse,
    TeamRef,
    UserDeactivateRequest,
    UserInviteRequest,
    UserPermissionsReplace,
    UserPermissionsResponse,
    UserResponse,
    UserStatus,
    UserUpdateRequest,
    UserVerticalsResponse,
)
from services.access_control import Actor
from services.org_unit_vertical_service import org_unit_vertical_service
from services.session_service import PERM_SESSION_READ, PERM_SESSION_REVOKE, session_service
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
    team_id: Optional[uuid.UUID] = Query(
        None, description="People in this team: those who work in it and its extra members"
    ),
    role_code: Optional[str] = Query(None, description="Users given this role preset"),
    q: Optional[str] = Query(None, max_length=255, description="Search by name, email or employee code"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    actor: Actor = Depends(require_permission(PERM_READ)),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[UserResponse]:
    return await user_service.list_users(
        session=db, actor=actor, status=status, unit_id=unit_id, team_id=team_id, role_code=role_code,
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


@router.get(
    "/{user_id}/verticals",
    response_model=UserVerticalsResponse,
    status_code=status.HTTP_200_OK,
    summary="The verticals a user operates in, inherited from their home unit",
)
async def get_user_verticals(
    user_id: uuid.UUID,
    actor: Actor = Depends(require_permission(PERM_READ)),
    db: AsyncSession = Depends(get_db_session),
) -> UserVerticalsResponse:
    user = await user_service.load_user_for(db, actor, user_id, PERM_READ)
    if not user.home_unit_id:
        return UserVerticalsResponse(
            user_id=user.id,
            home_unit_id=None,
            own=[],
            effective=[],
            inherited_from=None,
        )
    unit_res = await org_unit_vertical_service.get_unit_verticals(
        session=db, organization_id=actor.organization_id, unit_id=user.home_unit_id
    )
    return UserVerticalsResponse(
        user_id=user.id,
        home_unit_id=user.home_unit_id,
        own=[v.model_dump() for v in unit_res.own],
        effective=[v.model_dump() for v in unit_res.effective],
        inherited_from=unit_res.inherited_from.model_dump() if unit_res.inherited_from else None,
    )



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


@router.put(
    "/{user_id}/teams/{team_id}",
    response_model=TeamRef,
    status_code=status.HTTP_200_OK,
    summary="Add a user to a team",
    description=(
        "Makes the user an extra member of a team; where they work doesn't change. Answers 201 when "
        "they were added and 200 when they already were a member, so it is safe to repeat. Needs "
        "update rights over the user and inside the team."
    ),
)
async def join_team(
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    response: Response,
    actor: Actor = Depends(require_permission(PERM_UPDATE)),
    db: AsyncSession = Depends(get_db_session),
) -> TeamRef:
    team, added = await user_service.join_team(session=db, actor=actor, user_id=user_id, team_id=team_id)
    if added:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"/api/identity/v1/users/{user_id}/teams/{team_id}"
    return team


@router.delete(
    "/{user_id}/teams/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a user from a team",
    description=(
        "Ends the user's extra membership of a team. Removing someone who isn't a member changes "
        "nothing. To take someone out of the team they work in, move them or clear their place."
    ),
)
async def leave_team(
    user_id: uuid.UUID,
    team_id: uuid.UUID,
    actor: Actor = Depends(require_permission(PERM_UPDATE)),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    await user_service.leave_team(session=db, actor=actor, user_id=user_id, team_id=team_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


@router.get(
    "/{user_id}/sessions",
    response_model=PaginatedResponse[SessionResponse],
    status_code=status.HTTP_200_OK,
    summary="List where a user is signed in",
    description="The user's live sessions (browsers and devices), most recently used first.",
)
async def list_user_sessions(
    user_id: uuid.UUID,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    actor: Actor = Depends(require_permission(PERM_SESSION_READ)),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[SessionResponse]:
    user = await user_service.load_user_for(db, actor, user_id, PERM_SESSION_READ)
    return await session_service.list_sessions(db, user.id, current_id=None, limit=limit, cursor=cursor)


@router.delete(
    "/{user_id}/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign a user out of one session",
    description="Ends that sign-in at once. Use /auth/sessions for your own sessions.",
)
async def revoke_user_session(
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_permission(PERM_SESSION_REVOKE)),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    user = await user_service.load_user_for(
        db, actor, user_id, PERM_SESSION_REVOKE, manage_action="manage the sessions of"
    )
    await session_service.revoke_session(
        db, user, session_id, revoked_by=actor.user_id,
        client_ip=get_client_ip(request), user_agent=get_user_agent(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{user_id}/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign a user out everywhere",
    description="Ends all of the user's sign-ins at once. Use /auth/sessions for your own sessions.",
)
async def revoke_user_sessions(
    user_id: uuid.UUID,
    request: Request,
    actor: Actor = Depends(require_permission(PERM_SESSION_REVOKE)),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    user = await user_service.load_user_for(
        db, actor, user_id, PERM_SESSION_REVOKE, manage_action="manage the sessions of"
    )
    await session_service.revoke_sessions(
        db, user, revoked_by=actor.user_id,
        client_ip=get_client_ip(request), user_agent=get_user_agent(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
