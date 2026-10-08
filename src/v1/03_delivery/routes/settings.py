import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response

import permissions
from dependencies import DatabaseSession, OrgId, People, UserId, require_any_permission, require_permission
from schemas.settings import AssignablePeopleResponse, DeliverySettingsResponse, DeliverySettingsUpdate
import services.assignees as assignees
import services.settings as service

router = APIRouter(tags=["settings"])

CAN_MANAGE = Depends(require_permission(permissions.TEMPLATE_MANAGE))
# Task managers assign and create tasks; handover takers name who in their team picks the work up.
CAN_ASSIGN = Depends(require_any_permission(permissions.TASK_WRITE, permissions.HANDOVER_WRITE))


@router.get("/settings", response_model=DeliverySettingsResponse, dependencies=[CAN_MANAGE])
async def get_settings(session: DatabaseSession, org_id: OrgId, response: Response) -> DeliverySettingsResponse:
    """The organization's delivery settings; each is off until the organization turns it on."""
    settings = await service.get_settings(session, org_id)
    response.headers["ETag"] = f'"{settings.version}"'
    return settings


@router.patch("/settings", response_model=DeliverySettingsResponse, dependencies=[CAN_MANAGE])
async def update_settings(
    payload: DeliverySettingsUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> DeliverySettingsResponse:
    """Change the organization's delivery settings (If-Match: their version, 0 before the first change)."""
    settings = await service.update_settings(session, org_id, user_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{settings.version}"'
    return settings


@router.get("/assignable-people", response_model=AssignablePeopleResponse, dependencies=[CAN_ASSIGN])
async def list_assignable_people(
    session: DatabaseSession,
    org_id: OrgId,
    people: People,
    unit_id: Optional[uuid.UUID] = Query(None, description="The task's team: its people come first, or alone when the organization assigns only within the team"),
) -> AssignablePeopleResponse:
    """Who a task of this team may be given to, by name: for the assign, create and handover forms."""
    return await assignees.assignable_people(session, people, org_id, unit_id)
