import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response

import permissions
from dependencies import DatabaseSession, OrgId, People, UserId, require_any_permission, require_permission
from schemas.assignment_policies import AssignmentPoliciesResponse, AssignmentPolicyResponse, AssignmentPolicyUpdate
from schemas.settings import AssignablePeopleResponse, DeliverySettingsResponse, DeliverySettingsUpdate
import services.assignees as assignees
import services.assignment_policies as assignment_policies
import services.settings as service

router = APIRouter(tags=["settings"])

CAN_MANAGE = Depends(require_permission(permissions.TEMPLATE_MANAGE))
# The task forms say how the team hands out work left in its queue.
CAN_READ_TASKS = Depends(require_permission(permissions.TASK_READ))
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


@router.get("/assignment-policies", response_model=AssignmentPoliciesResponse, dependencies=[CAN_READ_TASKS])
async def list_assignment_policies(session: DatabaseSession, org_id: OrgId) -> AssignmentPoliciesResponse:
    """How each team hands out new work; a team not listed leaves it in its queue."""
    return await assignment_policies.list_policies(session, org_id)


@router.put("/assignment-policies/{unit_id}", response_model=AssignmentPolicyResponse, dependencies=[CAN_MANAGE])
async def set_assignment_policy(
    unit_id: uuid.UUID,
    payload: AssignmentPolicyUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> AssignmentPolicyResponse:
    """Choose how the team hands out new work (If-Match: its version, 0 for a team without a policy)."""
    policy = await assignment_policies.set_policy(session, org_id, unit_id, user_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{policy.version}"'
    return policy
