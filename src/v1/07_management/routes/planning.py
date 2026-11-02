import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status

import permissions
import services.kpi_service as kpi_service
import services.planning_service as service
from dependencies import CurrentActor, DatabaseSession, Names, OrgId, require_permission
from schemas.common import ListResponse, PageResponse
from schemas.planning import (
    CheckInCreate,
    CheckInResponse,
    FiscalYearCreate,
    FiscalYearResponse,
    FiscalYearUpdate,
    GoalCreate,
    GoalKpisSet,
    GoalResponse,
    GoalUpdate,
    InitiativeCreate,
    InitiativeResponse,
    InitiativeUpdate,
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    PeriodCloseResponse,
    PeriodCreate,
    PeriodResponse,
    PeriodUpdate,
    RoadmapItemCreate,
    RoadmapItemResponse,
    RoadmapItemUpdate,
)

router = APIRouter(tags=["planning"])

CAN_READ_YEARS = Depends(require_permission(permissions.FISCAL_YEAR_READ))
CAN_MANAGE_YEARS = Depends(require_permission(permissions.FISCAL_YEAR_MANAGE))
CAN_READ_PERIODS = Depends(require_permission(permissions.PERIOD_READ))
CAN_MANAGE_PERIODS = Depends(require_permission(permissions.PERIOD_MANAGE))
CAN_CLOSE_PERIODS = Depends(require_permission(permissions.PERIOD_CLOSE_MANAGE))
CAN_READ_GOALS = Depends(require_permission(permissions.GOAL_READ))
CAN_MANAGE_GOALS = Depends(require_permission(permissions.GOAL_MANAGE))
CAN_READ_INITIATIVES = Depends(require_permission(permissions.INITIATIVE_READ))
CAN_MANAGE_INITIATIVES = Depends(require_permission(permissions.INITIATIVE_MANAGE))
CAN_CHECK_IN = Depends(require_permission(permissions.CHECK_IN_WRITE))

Limit = Query(25, ge=1, le=100)


# --- Fiscal years -------------------------------------------------------------


@router.get("/fiscal-years", response_model=PageResponse[FiscalYearResponse], dependencies=[CAN_READ_YEARS])
async def list_fiscal_years(
    session: DatabaseSession, org_id: OrgId, status_: Optional[str] = Query(None, alias="status"),
    limit: int = Limit, cursor: Optional[str] = Query(None),
) -> PageResponse[FiscalYearResponse]:
    return await service.list_fiscal_years(session, org_id, status_, limit, cursor)


@router.post("/fiscal-years", response_model=FiscalYearResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_YEARS])
async def create_fiscal_year(payload: FiscalYearCreate, session: DatabaseSession, org_id: OrgId) -> FiscalYearResponse:
    """Create a fiscal year, optionally with its quarters and months."""
    year = await service.create_fiscal_year(session, org_id, payload)
    await session.commit()
    return year


@router.get("/fiscal-years/{year_id}", response_model=FiscalYearResponse, dependencies=[CAN_READ_YEARS])
async def get_fiscal_year(year_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> FiscalYearResponse:
    return await service.get_fiscal_year_response(session, org_id, year_id)


@router.patch("/fiscal-years/{year_id}", response_model=FiscalYearResponse, dependencies=[CAN_MANAGE_YEARS])
async def update_fiscal_year(
    year_id: uuid.UUID, payload: FiscalYearUpdate, session: DatabaseSession, org_id: OrgId
) -> FiscalYearResponse:
    year = await service.update_fiscal_year(session, org_id, year_id, payload)
    await session.commit()
    return year


@router.post("/fiscal-years/{year_id}/close", response_model=FiscalYearResponse, dependencies=[CAN_MANAGE_YEARS, CAN_CLOSE_PERIODS])
async def close_fiscal_year(year_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> FiscalYearResponse:
    """Close the year and every period in it: their KPI results are frozen."""
    await kpi_service.close_fiscal_year(session, org_id, year_id)
    await session.commit()
    return await service.get_fiscal_year_response(session, org_id, year_id)


# --- Planning periods ---------------------------------------------------------


@router.get("/planning-periods", response_model=PageResponse[PeriodResponse], dependencies=[CAN_READ_PERIODS])
async def list_periods(
    session: DatabaseSession,
    org_id: OrgId,
    fiscal_year_id: Optional[uuid.UUID] = Query(None),
    period_type: Optional[str] = Query(None),
    parent_period_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    containing: Optional[date] = Query(None, description="Only periods that include this day"),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[PeriodResponse]:
    return await service.list_periods(
        session, org_id, fiscal_year_id, period_type, parent_period_id, status_, containing, limit, cursor
    )


@router.post("/planning-periods", response_model=PeriodResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_PERIODS])
async def create_period(payload: PeriodCreate, session: DatabaseSession, org_id: OrgId) -> PeriodResponse:
    period = await service.create_period(session, org_id, payload)
    await session.commit()
    return period


@router.get("/planning-periods/{period_id}", response_model=PeriodResponse, dependencies=[CAN_READ_PERIODS])
async def get_period(period_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> PeriodResponse:
    return await service.get_period_response(session, org_id, period_id)


@router.patch("/planning-periods/{period_id}", response_model=PeriodResponse, dependencies=[CAN_MANAGE_PERIODS])
async def update_period(period_id: uuid.UUID, payload: PeriodUpdate, session: DatabaseSession, org_id: OrgId) -> PeriodResponse:
    period = await service.update_period(session, org_id, period_id, payload)
    await session.commit()
    return period


@router.post("/planning-periods/{period_id}/close", response_model=PeriodCloseResponse, dependencies=[CAN_CLOSE_PERIODS])
async def close_period(period_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> PeriodCloseResponse:
    """Close the period (and those inside it): KPI results are recalculated a last time and frozen."""
    closed = await kpi_service.close_period(session, org_id, period_id)
    await session.commit()
    return closed


# --- Strategic goals ----------------------------------------------------------


@router.get("/goals", response_model=PageResponse[GoalResponse], dependencies=[CAN_READ_GOALS])
async def list_goals(
    session: DatabaseSession,
    org_id: OrgId,
    names: Names,
    period_id: Optional[uuid.UUID] = Query(None),
    owner_user_id: Optional[uuid.UUID] = Query(None),
    parent_goal_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[GoalResponse]:
    return await service.list_goals(session, org_id, names, period_id, owner_user_id, parent_goal_id, status_, limit, cursor)


@router.post("/goals", response_model=GoalResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_GOALS])
async def create_goal(payload: GoalCreate, session: DatabaseSession, org_id: OrgId, names: Names) -> GoalResponse:
    goal = await service.create_goal(session, org_id, payload, names)
    await session.commit()
    return goal


@router.get("/goals/{goal_id}", response_model=GoalResponse, dependencies=[CAN_READ_GOALS])
async def get_goal(goal_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, names: Names) -> GoalResponse:
    return await service.get_goal_response(session, org_id, goal_id, names)


@router.patch("/goals/{goal_id}", response_model=GoalResponse, dependencies=[CAN_MANAGE_GOALS])
async def update_goal(
    goal_id: uuid.UUID, payload: GoalUpdate, session: DatabaseSession, org_id: OrgId, names: Names,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> GoalResponse:
    goal = await service.update_goal(session, org_id, goal_id, payload, if_match, names)
    await session.commit()
    return goal


@router.put("/goals/{goal_id}/kpis", response_model=GoalResponse, dependencies=[CAN_MANAGE_GOALS])
async def set_goal_kpis(goal_id: uuid.UUID, payload: GoalKpisSet, session: DatabaseSession, org_id: OrgId, names: Names) -> GoalResponse:
    """Replace the KPIs that measure the goal, with their weights."""
    goal = await service.set_goal_kpis(session, org_id, goal_id, payload, names)
    await session.commit()
    return goal


@router.get("/goals/{goal_id}/check-ins", response_model=ListResponse[CheckInResponse], dependencies=[CAN_READ_GOALS])
async def list_goal_check_ins(
    goal_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, names: Names, limit: int = Limit
) -> ListResponse[CheckInResponse]:
    return ListResponse(data=await service.list_check_ins(session, org_id, names, limit, goal_id=goal_id))


@router.post("/goals/{goal_id}/check-ins", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_CHECK_IN])
async def check_in_on_goal(
    goal_id: uuid.UUID, payload: CheckInCreate, session: DatabaseSession, actor: CurrentActor, names: Names
) -> CheckInResponse:
    """The owner's confidence and story for the goal (owners only, unless you manage goals)."""
    check_in = await service.create_check_in(session, actor, payload, names, goal_id=goal_id)
    await session.commit()
    return check_in


# --- Initiatives --------------------------------------------------------------


@router.get("/initiatives", response_model=PageResponse[InitiativeResponse], dependencies=[CAN_READ_INITIATIVES])
async def list_initiatives(
    session: DatabaseSession,
    org_id: OrgId,
    names: Names,
    goal_id: Optional[uuid.UUID] = Query(None),
    owner_user_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[InitiativeResponse]:
    return await service.list_initiatives(session, org_id, names, goal_id, owner_user_id, status_, limit, cursor)


@router.post("/initiatives", response_model=InitiativeResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_INITIATIVES])
async def create_initiative(payload: InitiativeCreate, session: DatabaseSession, org_id: OrgId, names: Names) -> InitiativeResponse:
    initiative = await service.create_initiative(session, org_id, payload, names)
    await session.commit()
    return initiative


@router.get("/initiatives/{initiative_id}", response_model=InitiativeResponse, dependencies=[CAN_READ_INITIATIVES])
async def get_initiative(initiative_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, names: Names) -> InitiativeResponse:
    return await service.get_initiative_response(session, org_id, initiative_id, names)


@router.patch("/initiatives/{initiative_id}", response_model=InitiativeResponse, dependencies=[CAN_MANAGE_INITIATIVES])
async def update_initiative(
    initiative_id: uuid.UUID, payload: InitiativeUpdate, session: DatabaseSession, org_id: OrgId, names: Names
) -> InitiativeResponse:
    initiative = await service.update_initiative(session, org_id, initiative_id, payload, names)
    await session.commit()
    return initiative


@router.get("/initiatives/{initiative_id}/milestones", response_model=ListResponse[MilestoneResponse], dependencies=[CAN_READ_INITIATIVES])
async def list_milestones(initiative_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> ListResponse[MilestoneResponse]:
    return ListResponse(data=await service.list_milestones(session, org_id, initiative_id))


@router.post(
    "/initiatives/{initiative_id}/milestones", response_model=MilestoneResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_INITIATIVES],
)
async def create_milestone(
    initiative_id: uuid.UUID, payload: MilestoneCreate, session: DatabaseSession, org_id: OrgId
) -> MilestoneResponse:
    milestone = await service.create_milestone(session, org_id, initiative_id, payload)
    await session.commit()
    return milestone


@router.patch("/milestones/{milestone_id}", response_model=MilestoneResponse, dependencies=[CAN_MANAGE_INITIATIVES])
async def update_milestone(
    milestone_id: uuid.UUID, payload: MilestoneUpdate, session: DatabaseSession, org_id: OrgId
) -> MilestoneResponse:
    milestone = await service.update_milestone(session, org_id, milestone_id, payload)
    await session.commit()
    return milestone


@router.get("/initiatives/{initiative_id}/check-ins", response_model=ListResponse[CheckInResponse], dependencies=[CAN_READ_INITIATIVES])
async def list_initiative_check_ins(
    initiative_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, names: Names, limit: int = Limit
) -> ListResponse[CheckInResponse]:
    return ListResponse(data=await service.list_check_ins(session, org_id, names, limit, initiative_id=initiative_id))


@router.post(
    "/initiatives/{initiative_id}/check-ins", response_model=CheckInResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_CHECK_IN],
)
async def check_in_on_initiative(
    initiative_id: uuid.UUID, payload: CheckInCreate, session: DatabaseSession, actor: CurrentActor, names: Names
) -> CheckInResponse:
    check_in = await service.create_check_in(session, actor, payload, names, initiative_id=initiative_id)
    await session.commit()
    return check_in


# --- Roadmap ------------------------------------------------------------------


@router.get("/roadmap-items", response_model=PageResponse[RoadmapItemResponse], dependencies=[CAN_READ_INITIATIVES])
async def list_roadmap_items(
    session: DatabaseSession,
    org_id: OrgId,
    roadmap_code: Optional[str] = Query(None),
    initiative_id: Optional[uuid.UUID] = Query(None),
    limit: int = Limit,
    cursor: Optional[str] = Query(None),
) -> PageResponse[RoadmapItemResponse]:
    return await service.list_roadmap_items(session, org_id, roadmap_code, initiative_id, limit, cursor)


@router.post("/roadmap-items", response_model=RoadmapItemResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE_INITIATIVES])
async def create_roadmap_item(payload: RoadmapItemCreate, session: DatabaseSession, org_id: OrgId) -> RoadmapItemResponse:
    item = await service.create_roadmap_item(session, org_id, payload)
    await session.commit()
    return item


@router.patch("/roadmap-items/{item_id}", response_model=RoadmapItemResponse, dependencies=[CAN_MANAGE_INITIATIVES])
async def update_roadmap_item(
    item_id: uuid.UUID, payload: RoadmapItemUpdate, session: DatabaseSession, org_id: OrgId
) -> RoadmapItemResponse:
    item = await service.update_roadmap_item(session, org_id, item_id, payload)
    await session.commit()
    return item
