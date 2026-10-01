from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import require_permission
from exceptions import PreconditionRequiredError
from schemas.calendar import (
    CalendarCreate,
    CalendarResponse,
    HolidayBatch,
)
from schemas.common import PaginatedResponse
from services.access_control import Actor
from services.calendar_service import calendar_service

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[CalendarResponse],
    status_code=status.HTTP_200_OK,
    summary="List working calendars",
)
async def list_calendars(
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    actor: Actor = Depends(require_permission("identity.calendar.read")),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[CalendarResponse]:
    return await calendar_service.list_calendars(
        session=db,
        organization_id=actor.organization_id,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


@router.post(
    "",
    response_model=CalendarResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a working calendar",
)
async def create_calendar(
    body: CalendarCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_permission("identity.calendar.create")),
    db: AsyncSession = Depends(get_db_session),
) -> CalendarResponse:
    calendar = await calendar_service.create_calendar(
        session=db,
        organization_id=actor.organization_id,
        data=body,
    )
    response.headers["Location"] = f"/api/identity/v1/calendars/{calendar.id}"
    return calendar


@router.put(
    "/{calendar_id}/holidays",
    response_model=CalendarResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a calendar's holiday list",
)
async def replace_holidays(
    calendar_id: uuid.UUID,
    body: HolidayBatch,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    actor: Actor = Depends(require_permission("identity.calendar.update")),
    db: AsyncSession = Depends(get_db_session),
) -> CalendarResponse:
    if not if_match:
        raise PreconditionRequiredError("If-Match header with ETag version is required to replace holidays")

    return await calendar_service.replace_holidays(
        session=db,
        organization_id=actor.organization_id,
        calendar_id=calendar_id,
        data=body,
        if_match=if_match,
    )
