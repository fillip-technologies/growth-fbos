import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
from dependencies import DatabaseSession, OrgId, People, UserId, require_any_permission, require_permission
from schemas.common import PageResponse
from schemas.routing import (
    RequestableTypesResponse,
    RequestCreate,
    RouteResponse,
    RoutingRuleCreate,
    RoutingRuleResponse,
    RoutingRuleUpdate,
)
from schemas.tasks import TaskResponse
import services.routing as service
import services.tasks as tasks
from services.tasks import TaskFilters

router = APIRouter(tags=["routing"])

CAN_READ = Depends(require_permission(permissions.TASK_READ))
CAN_MANAGE = Depends(require_permission(permissions.TEMPLATE_MANAGE))
CAN_REQUEST = Depends(require_permission(permissions.TASK_REQUEST))
# The task form fills in the team, the request form shows where a request goes.
CAN_ROUTE = Depends(require_any_permission(permissions.TASK_WRITE, permissions.TASK_REQUEST))


# --- Rules: which team does which work ---------------------------------------


@router.get("/routing-rules", response_model=PageResponse[RoutingRuleResponse], dependencies=[CAN_READ])
async def list_routing_rules(
    session: DatabaseSession,
    org_id: OrgId,
    include_inactive: bool = Query(False),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[RoutingRuleResponse]:
    """The organization's routing rules, oldest first."""
    return await service.list_rules(session, org_id, include_inactive, limit, cursor)


@router.post("/routing-rules", response_model=RoutingRuleResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_routing_rule(payload: RoutingRuleCreate, session: DatabaseSession, org_id: OrgId) -> RoutingRuleResponse:
    """Send a task type's work, or a discipline's, (for one vertical) to a team."""
    rule = await service.create_rule(session, org_id, payload)
    await session.commit()
    return rule


@router.patch("/routing-rules/{rule_id}", response_model=RoutingRuleResponse, dependencies=[CAN_MANAGE])
async def update_routing_rule(
    rule_id: uuid.UUID,
    payload: RoutingRuleUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> RoutingRuleResponse:
    """Change a rule's team or whether it takes requests, or turn it off (If-Match: its version)."""
    rule = await service.update_rule(session, org_id, rule_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{rule.version}"'
    return rule


@router.get("/task-routing", response_model=RouteResponse, dependencies=[CAN_ROUTE])
async def get_task_routing(
    session: DatabaseSession,
    org_id: OrgId,
    task_type_code: str = Query(...),
    vertical_id: Optional[uuid.UUID] = Query(None, description="The vertical the work is for (a project's)"),
) -> RouteResponse:
    """The team this kind of work goes to by the routing rules; none when no rule covers it."""
    return await service.route(session, org_id, task_type_code, vertical_id)


# --- Requests: asking another team for work ------------------------------------


@router.get("/requestable-types", response_model=RequestableTypesResponse, dependencies=[CAN_REQUEST])
async def list_requestable_types(session: DatabaseSession, org_id: OrgId) -> RequestableTypesResponse:
    """The kinds of work other teams take requests for, and which team each goes to."""
    return await service.requestable_types(session, org_id)


@router.post("/requests", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_REQUEST])
async def create_request(
    payload: RequestCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    people: People,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TaskResponse:
    """Ask the team that does this kind of work for it: the task waits in that team's queue."""
    task = await service.create_request(session, org_id, user_id, payload, people)
    await session.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return task


@router.get("/requests", response_model=PageResponse[TaskResponse], dependencies=[CAN_REQUEST])
async def list_my_requests(
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    status_: Optional[list[str]] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[TaskResponse]:
    """The requests you sent to other teams, newest first, to follow them."""
    filters = TaskFilters(requested_by=user_id, statuses=status_)
    return await tasks.list_tasks(session, org_id, user_id, filters, limit, cursor)
