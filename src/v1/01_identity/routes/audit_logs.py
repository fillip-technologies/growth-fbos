from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import require_permission
from schemas.audit_log import AuditLogResponse
from schemas.common import PaginatedResponse
from services.access_control import Actor
from services.audit_service import PERM_AUDIT_READ, audit_service

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[AuditLogResponse],
    status_code=status.HTTP_200_OK,
    summary="List security audit log entries",
    description=(
        "Sign-ins, failed attempts, MFA checks, token refreshes, sign-outs and locks in this "
        "organization, newest first. A grant scoped to a unit shows only entries about users "
        "placed in that unit or below it."
    ),
)
async def list_audit_logs(
    user_id: Optional[uuid.UUID] = Query(None, description="Only entries about this user"),
    event_type: Optional[str] = Query(None, description="e.g. identity.session.login_failed.v1"),
    exclude_event_type: Optional[list[str]] = Query(
        None, description="Leave out these event types (repeatable), e.g. identity.session.refreshed.v1"
    ),
    status: Optional[str] = Query(None, description="success, failed, revoked or locked"),
    created_after: Optional[datetime] = Query(None, description="ISO 8601, inclusive"),
    created_before: Optional[datetime] = Query(None, description="ISO 8601, exclusive"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    actor: Actor = Depends(require_permission(PERM_AUDIT_READ)),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[AuditLogResponse]:
    return await audit_service.list_logs(
        session=db,
        actor=actor,
        user_id=user_id,
        event_type=event_type,
        exclude_event_types=exclude_event_type,
        status=status,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        cursor=cursor,
    )
