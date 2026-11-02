"""
Planning: fiscal years, their periods (quarter > month > sprint), strategic goals that cascade,
the initiatives that deliver them with milestones and a roadmap, and owners' check-ins.

Rules kept here (plan §4.1): a period sits inside its fiscal year and inside its parent; periods of
the same type under the same parent don't overlap; fiscal years of an organization don't overlap; a
goal's period and parent belong to its organization; a cascaded goal can't outlive its parent and
can't become its own ancestor. Only the owner checks in on a goal or initiative, unless the caller
manages goals or initiatives.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    DuplicateFiscalYearError,
    DuplicateGoalCodeError,
    DuplicateInitiativeCodeError,
    FiscalYearNotFoundError,
    InitiativeNotFoundError,
    InvalidStateTransitionError,
    KPINotFoundError,
    MilestoneNotFoundError,
    OverlapError,
    PermissionDeniedError,
    PlanningPeriodNotFoundError,
    RoadmapItemNotFoundError,
    StrategicGoalNotFoundError,
    UnknownReferenceError,
    ValidationFailedError,
)
from models.performance import GoalKPI, KPIDefinition
from models.planning import (
    FiscalYear,
    GoalCheckIn,
    Initiative,
    InitiativeMilestone,
    PlanningPeriod,
    RoadmapItem,
    StrategicGoal,
)
from schemas.common import PageResponse
from schemas.planning import (
    CheckInCreate,
    CheckInResponse,
    FiscalYearCreate,
    FiscalYearResponse,
    FiscalYearUpdate,
    GoalCreate,
    GoalKpiResponse,
    GoalKpisSet,
    GoalResponse,
    GoalScope,
    GoalUpdate,
    InitiativeCreate,
    InitiativeResponse,
    InitiativeUpdate,
    MilestoneCreate,
    MilestoneResponse,
    MilestoneUpdate,
    PeriodCreate,
    PeriodRef,
    PeriodResponse,
    PeriodUpdate,
    RoadmapItemCreate,
    RoadmapItemResponse,
    RoadmapItemUpdate,
)
from services.common import Directory, check_date_range, check_if_match, get_in_org
from services.identity_client import Actor
from services.pagination import paginate_by_id

CLOSED = "closed"


# --- Responses ----------------------------------------------------------------


def fiscal_year_response(year: FiscalYear) -> FiscalYearResponse:
    return FiscalYearResponse(
        id=year.id, code=year.code, start_date=year.start_date, end_date=year.end_date, status=year.status
    )


def period_response(period: PlanningPeriod) -> PeriodResponse:
    return PeriodResponse(
        id=period.id,
        fiscal_year_id=period.fiscal_year_id,
        parent_period_id=period.parent_period_id,
        period_type=period.period_type,
        name=period.name,
        start_date=period.start_date,
        end_date=period.end_date,
        status=period.status,
    )


def confidence_band(confidence: float) -> str:
    if confidence >= 0.7:
        return "confident"
    if confidence >= 0.4:
        return "at_risk"
    return "change_approach"


async def check_in_response(check_in: GoalCheckIn, directory: Directory) -> CheckInResponse:
    confidence = float(check_in.confidence)
    return CheckInResponse(
        id=check_in.id,
        goal_id=check_in.goal_id,
        initiative_id=check_in.initiative_id,
        period_id=check_in.period_id,
        confidence=confidence,
        confidence_band=confidence_band(confidence),
        rag=check_in.rag,
        narrative=check_in.narrative,
        author=await directory.user(check_in.author_user_id),
        created_at=check_in.created_at,
    )


async def latest_check_in(
    session: AsyncSession, *, goal_id: Optional[uuid.UUID] = None, initiative_id: Optional[uuid.UUID] = None
) -> Optional[GoalCheckIn]:
    query = select(GoalCheckIn)
    query = query.where(GoalCheckIn.goal_id == goal_id) if goal_id else query.where(GoalCheckIn.initiative_id == initiative_id)
    query = query.order_by(GoalCheckIn.created_at.desc(), GoalCheckIn.id.desc()).limit(1)
    return (await session.execute(query)).scalars().first()


async def _goal_response(session: AsyncSession, goal: StrategicGoal, directory: Directory) -> GoalResponse:
    period = await session.get(PlanningPeriod, goal.period_id) if goal.period_id else None
    kpi_rows = (
        await session.execute(
            select(GoalKPI, KPIDefinition)
            .join(KPIDefinition, KPIDefinition.id == GoalKPI.kpi_definition_id)
            .where(GoalKPI.goal_id == goal.id)
            .order_by(KPIDefinition.code)
        )
    ).all()
    check_in = await latest_check_in(session, goal_id=goal.id)
    return GoalResponse(
        id=goal.id,
        code=goal.code,
        name=goal.name,
        description=goal.description,
        period=PeriodRef(id=period.id, name=period.name) if period else None,
        parent_goal_id=goal.parent_goal_id,
        scope=GoalScope(unit_id=goal.scope_unit_id, vertical_id=goal.scope_vertical_id),
        owner=await directory.user(goal.owner_user_id),
        priority=goal.priority,
        status=goal.status,
        version=goal.version,
        kpis=[GoalKpiResponse(kpi_code=kpi.code, name=kpi.name, weight=float(link.weight)) for link, kpi in kpi_rows],
        latest_check_in=await check_in_response(check_in, directory) if check_in else None,
    )


async def _initiative_response(session: AsyncSession, initiative: Initiative, directory: Directory) -> InitiativeResponse:
    progress = (
        await session.execute(
            select(func.avg(InitiativeMilestone.progress_pct)).where(InitiativeMilestone.initiative_id == initiative.id)
        )
    ).scalar_one_or_none()
    check_in = await latest_check_in(session, initiative_id=initiative.id)
    return InitiativeResponse(
        id=initiative.id,
        goal_id=initiative.goal_id,
        code=initiative.code,
        name=initiative.name,
        owner=await directory.user(initiative.owner_user_id),
        start_date=initiative.start_date,
        end_date=initiative.end_date,
        status=initiative.status,
        linked_work_unit_id=initiative.linked_work_unit_id,
        progress_pct=round(float(progress), 2) if progress is not None else None,
        latest_check_in=await check_in_response(check_in, directory) if check_in else None,
    )


def _milestone_response(milestone: InitiativeMilestone) -> MilestoneResponse:
    return MilestoneResponse(
        id=milestone.id,
        initiative_id=milestone.initiative_id,
        name=milestone.name,
        due_date=milestone.due_date,
        status=milestone.status,
        progress_pct=float(milestone.progress_pct),
    )


def _roadmap_response(item: RoadmapItem) -> RoadmapItemResponse:
    return RoadmapItemResponse(
        id=item.id,
        roadmap_code=item.roadmap_code,
        title=item.title,
        initiative_id=item.initiative_id,
        seq=item.seq,
        start_date=item.start_date,
        end_date=item.end_date,
        status=item.status,
    )


# --- Lookups ------------------------------------------------------------------


async def get_fiscal_year(session: AsyncSession, org_id: uuid.UUID, year_id: uuid.UUID) -> FiscalYear:
    return await get_in_org(session, FiscalYear, year_id, org_id, FiscalYearNotFoundError(str(year_id)))


async def get_period(session: AsyncSession, org_id: uuid.UUID, period_id: uuid.UUID) -> PlanningPeriod:
    return await get_in_org(session, PlanningPeriod, period_id, org_id, PlanningPeriodNotFoundError(str(period_id)))


async def period_reference(session: AsyncSession, org_id: uuid.UUID, period_id: uuid.UUID, field: str = "period_id") -> PlanningPeriod:
    """A period named in a request body: unknown ones are a 422 on that field."""
    period = await session.get(PlanningPeriod, period_id)
    if period is None or period.organization_id != org_id:
        raise UnknownReferenceError("PLANNING_PERIOD_NOT_FOUND", field, "Planning period not found.")
    return period


async def get_goal(session: AsyncSession, org_id: uuid.UUID, goal_id: uuid.UUID) -> StrategicGoal:
    return await get_in_org(session, StrategicGoal, goal_id, org_id, StrategicGoalNotFoundError(str(goal_id)))


async def get_initiative(session: AsyncSession, org_id: uuid.UUID, initiative_id: uuid.UUID) -> Initiative:
    return await get_in_org(session, Initiative, initiative_id, org_id, InitiativeNotFoundError(str(initiative_id)))


async def _get_milestone(session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID) -> InitiativeMilestone:
    milestone = await session.get(InitiativeMilestone, milestone_id)
    if milestone is None:
        raise MilestoneNotFoundError(str(milestone_id))
    initiative = await session.get(Initiative, milestone.initiative_id)
    if initiative is None or initiative.organization_id != org_id:
        raise MilestoneNotFoundError(str(milestone_id))
    return milestone


# --- Fiscal years -------------------------------------------------------------


async def _check_fiscal_year(
    session: AsyncSession, org_id: uuid.UUID, code: str, start: date, end: date, exclude_id: Optional[uuid.UUID] = None
) -> None:
    check_date_range(start, end)
    if (end - start).days > 400:
        raise ValidationFailedError("end_date", "a fiscal year spans at most 400 days")
    others = select(FiscalYear).where(FiscalYear.organization_id == org_id)
    if exclude_id is not None:
        others = others.where(FiscalYear.id != exclude_id)
    rows = (await session.execute(others)).scalars().all()
    if any(row.code == code for row in rows):
        raise DuplicateFiscalYearError(code)
    if any(row.start_date <= end and start <= row.end_date for row in rows):
        raise OverlapError("FISCAL_YEAR_OVERLAP", "Fiscal years of an organization can't overlap.")


def _month_end(day: date) -> date:
    next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def _months(start: date, end: date) -> list[tuple[date, date]]:
    months, current = [], start
    while current <= end:
        last = min(_month_end(current), end)
        months.append((current, last))
        current = last + timedelta(days=1)
    return months


def _generate_periods(year: FiscalYear, types: set[str]) -> list[PlanningPeriod]:
    """Quarters of three months from the year's start, each holding its months (or months alone)."""
    months = _months(year.start_date, year.end_date)
    periods: list[PlanningPeriod] = []
    quarters: list[PlanningPeriod] = []
    if "quarter" in types:
        for index in range(0, len(months), 3):
            chunk = months[index : index + 3]
            quarters.append(
                PlanningPeriod(
                    id=uuid.uuid4(), organization_id=year.organization_id, fiscal_year_id=year.id,
                    period_type="quarter", name=f"{year.code} Q{index // 3 + 1}",
                    start_date=chunk[0][0], end_date=chunk[-1][1], status="active",
                )
            )
        periods.extend(quarters)
    if "month" in types:
        for index, (first, last) in enumerate(months):
            parent = quarters[index // 3] if quarters else None
            periods.append(
                PlanningPeriod(
                    id=uuid.uuid4(), organization_id=year.organization_id, fiscal_year_id=year.id,
                    parent_period_id=parent.id if parent else None, period_type="month",
                    name=f"{year.code} {first.strftime('%b %Y')}", start_date=first, end_date=last, status="active",
                )
            )
    return periods


async def list_fiscal_years(
    session: AsyncSession, org_id: uuid.UUID, status: Optional[str], limit: int, cursor: Optional[str]
) -> PageResponse[FiscalYearResponse]:
    query = select(FiscalYear).where(FiscalYear.organization_id == org_id)
    if status is not None:
        query = query.where(FiscalYear.status == status)
    rows, page = await paginate_by_id(session, query, FiscalYear, limit, cursor)
    return PageResponse(data=[fiscal_year_response(row) for row in rows], page=page)


async def create_fiscal_year(session: AsyncSession, org_id: uuid.UUID, data: FiscalYearCreate) -> FiscalYearResponse:
    await _check_fiscal_year(session, org_id, data.code, data.start_date, data.end_date)
    year = FiscalYear(
        id=uuid.uuid4(), organization_id=org_id, code=data.code,
        start_date=data.start_date, end_date=data.end_date, status="active",
    )
    session.add(year)
    await session.flush()
    session.add_all(_generate_periods(year, set(data.period_types)))
    await session.flush()
    return fiscal_year_response(year)


async def get_fiscal_year_response(session: AsyncSession, org_id: uuid.UUID, year_id: uuid.UUID) -> FiscalYearResponse:
    return fiscal_year_response(await get_fiscal_year(session, org_id, year_id))


async def update_fiscal_year(
    session: AsyncSession, org_id: uuid.UUID, year_id: uuid.UUID, data: FiscalYearUpdate
) -> FiscalYearResponse:
    year = await get_fiscal_year(session, org_id, year_id)
    if year.status == CLOSED:
        raise InvalidStateTransitionError("fiscal year", year.status, "change")
    code = data.code or year.code
    start = data.start_date or year.start_date
    end = data.end_date or year.end_date
    await _check_fiscal_year(session, org_id, code, start, end, exclude_id=year.id)
    outside = (
        await session.execute(
            select(func.count()).select_from(PlanningPeriod).where(
                PlanningPeriod.fiscal_year_id == year.id,
                (PlanningPeriod.start_date < start) | (PlanningPeriod.end_date > end),
            )
        )
    ).scalar_one()
    if outside:
        raise ValidationFailedError("start_date", "the year must still hold all of its periods")
    year.code, year.start_date, year.end_date = code, start, end
    await session.flush()
    return fiscal_year_response(year)


# --- Planning periods ---------------------------------------------------------


async def _check_period(
    session: AsyncSession,
    org_id: uuid.UUID,
    year: FiscalYear,
    parent_id: Optional[uuid.UUID],
    period_type: str,
    start: date,
    end: date,
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    check_date_range(start, end)
    if start < year.start_date or end > year.end_date:
        raise ValidationFailedError("start_date", "a period must sit inside its fiscal year")
    if parent_id is not None:
        parent = await session.get(PlanningPeriod, parent_id)
        if parent is None or parent.organization_id != org_id or parent.fiscal_year_id != year.id:
            raise UnknownReferenceError(
                "PLANNING_PERIOD_NOT_FOUND", "parent_period_id", "The parent period isn't in this fiscal year."
            )
        if start < parent.start_date or end > parent.end_date:
            raise ValidationFailedError("start_date", "a period must sit inside its parent period")
        if parent.period_type == period_type:
            raise ValidationFailedError("period_type", "a period can't nest inside a period of the same type")
    siblings = select(PlanningPeriod).where(
        PlanningPeriod.fiscal_year_id == year.id,
        PlanningPeriod.period_type == period_type,
        PlanningPeriod.start_date <= end,
        PlanningPeriod.end_date >= start,
    )
    siblings = siblings.where(
        PlanningPeriod.parent_period_id == parent_id if parent_id else PlanningPeriod.parent_period_id.is_(None)
    )
    if exclude_id is not None:
        siblings = siblings.where(PlanningPeriod.id != exclude_id)
    if (await session.execute(siblings.limit(1))).scalars().first():
        raise OverlapError("PERIOD_OVERLAP", f"Another {period_type} under the same parent overlaps these dates.")


async def list_periods(
    session: AsyncSession,
    org_id: uuid.UUID,
    fiscal_year_id: Optional[uuid.UUID],
    period_type: Optional[str],
    parent_period_id: Optional[uuid.UUID],
    status: Optional[str],
    containing: Optional[date],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[PeriodResponse]:
    query = select(PlanningPeriod).where(PlanningPeriod.organization_id == org_id)
    if fiscal_year_id is not None:
        query = query.where(PlanningPeriod.fiscal_year_id == fiscal_year_id)
    if period_type is not None:
        query = query.where(PlanningPeriod.period_type == period_type)
    if parent_period_id is not None:
        query = query.where(PlanningPeriod.parent_period_id == parent_period_id)
    if status is not None:
        query = query.where(PlanningPeriod.status == status)
    if containing is not None:
        query = query.where(PlanningPeriod.start_date <= containing, PlanningPeriod.end_date >= containing)
    rows, page = await paginate_by_id(session, query, PlanningPeriod, limit, cursor)
    return PageResponse(data=[period_response(row) for row in rows], page=page)


async def create_period(session: AsyncSession, org_id: uuid.UUID, data: PeriodCreate) -> PeriodResponse:
    year = await session.get(FiscalYear, data.fiscal_year_id)
    if year is None or year.organization_id != org_id:
        raise UnknownReferenceError("FISCAL_YEAR_NOT_FOUND", "fiscal_year_id", "Fiscal year not found.")
    if year.status == CLOSED:
        raise InvalidStateTransitionError("fiscal year", year.status, "add a period to")
    await _check_period(session, org_id, year, data.parent_period_id, data.period_type, data.start_date, data.end_date)
    period = PlanningPeriod(
        organization_id=org_id, fiscal_year_id=year.id, parent_period_id=data.parent_period_id,
        period_type=data.period_type, name=data.name, start_date=data.start_date, end_date=data.end_date,
        status="active",
    )
    session.add(period)
    await session.flush()
    return period_response(period)


async def get_period_response(session: AsyncSession, org_id: uuid.UUID, period_id: uuid.UUID) -> PeriodResponse:
    return period_response(await get_period(session, org_id, period_id))


async def update_period(
    session: AsyncSession, org_id: uuid.UUID, period_id: uuid.UUID, data: PeriodUpdate
) -> PeriodResponse:
    period = await get_period(session, org_id, period_id)
    if period.status == CLOSED:
        raise InvalidStateTransitionError("period", period.status, "change")
    start = data.start_date or period.start_date
    end = data.end_date or period.end_date
    if (start, end) != (period.start_date, period.end_date):
        year = await session.get(FiscalYear, period.fiscal_year_id)
        await _check_period(session, org_id, year, period.parent_period_id, period.period_type, start, end, exclude_id=period.id)
        children_outside = (
            await session.execute(
                select(func.count()).select_from(PlanningPeriod).where(
                    PlanningPeriod.parent_period_id == period.id,
                    (PlanningPeriod.start_date < start) | (PlanningPeriod.end_date > end),
                )
            )
        ).scalar_one()
        if children_outside:
            raise ValidationFailedError("start_date", "the period must still hold all of its child periods")
    if data.name is not None:
        period.name = data.name
    period.start_date, period.end_date = start, end
    await session.flush()
    return period_response(period)


# --- Strategic goals ----------------------------------------------------------


async def _check_goal_links(
    session: AsyncSession,
    org_id: uuid.UUID,
    goal_id: Optional[uuid.UUID],
    period_id: Optional[uuid.UUID],
    parent_goal_id: Optional[uuid.UUID],
) -> None:
    period = await period_reference(session, org_id, period_id) if period_id else None
    if parent_goal_id is None:
        return
    parent = await session.get(StrategicGoal, parent_goal_id)
    if parent is None or parent.organization_id != org_id:
        raise UnknownReferenceError("STRATEGIC_GOAL_NOT_FOUND", "parent_goal_id", "Parent goal not found.")
    # Walk up from the parent: meeting the goal itself would make it its own ancestor.
    ancestor, seen = parent, set()
    while ancestor is not None and ancestor.id not in seen:
        if goal_id is not None and ancestor.id == goal_id:
            raise ValidationFailedError("parent_goal_id", "a goal can't cascade from itself or its own sub-goals")
        seen.add(ancestor.id)
        ancestor = await session.get(StrategicGoal, ancestor.parent_goal_id) if ancestor.parent_goal_id else None
    if period is not None and parent.period_id is not None:
        parent_period = await session.get(PlanningPeriod, parent.period_id)
        if parent_period is not None and period.end_date > parent_period.end_date:
            raise ValidationFailedError("period_id", "a cascaded goal can't outlive its parent goal")


async def list_goals(
    session: AsyncSession,
    org_id: uuid.UUID,
    directory: Directory,
    period_id: Optional[uuid.UUID],
    owner_user_id: Optional[uuid.UUID],
    parent_goal_id: Optional[uuid.UUID],
    status: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[GoalResponse]:
    query = select(StrategicGoal).where(StrategicGoal.organization_id == org_id)
    if period_id is not None:
        query = query.where(StrategicGoal.period_id == period_id)
    if owner_user_id is not None:
        query = query.where(StrategicGoal.owner_user_id == owner_user_id)
    if parent_goal_id is not None:
        query = query.where(StrategicGoal.parent_goal_id == parent_goal_id)
    if status is not None:
        query = query.where(StrategicGoal.status == status)
    rows, page = await paginate_by_id(session, query, StrategicGoal, limit, cursor)
    return PageResponse(data=[await _goal_response(session, row, directory) for row in rows], page=page)


async def create_goal(session: AsyncSession, org_id: uuid.UUID, data: GoalCreate, directory: Directory) -> GoalResponse:
    duplicate = await session.execute(
        select(StrategicGoal.id).where(StrategicGoal.organization_id == org_id, StrategicGoal.code == data.code)
    )
    if duplicate.first():
        raise DuplicateGoalCodeError(data.code)
    await _check_goal_links(session, org_id, None, data.period_id, data.parent_goal_id)
    goal = StrategicGoal(
        organization_id=org_id, code=data.code, name=data.name, description=data.description,
        period_id=data.period_id, parent_goal_id=data.parent_goal_id, scope_unit_id=data.scope.unit_id,
        scope_vertical_id=data.scope.vertical_id, owner_user_id=data.owner_user_id, priority=data.priority,
        status="active", version=1,
    )
    session.add(goal)
    await session.flush()
    return await _goal_response(session, goal, directory)


async def get_goal_response(session: AsyncSession, org_id: uuid.UUID, goal_id: uuid.UUID, directory: Directory) -> GoalResponse:
    return await _goal_response(session, await get_goal(session, org_id, goal_id), directory)


async def update_goal(
    session: AsyncSession, org_id: uuid.UUID, goal_id: uuid.UUID, data: GoalUpdate, if_match: Optional[str], directory: Directory
) -> GoalResponse:
    goal = await get_goal(session, org_id, goal_id)
    check_if_match(if_match, goal.version)
    changes = data.model_dump(exclude_unset=True)
    if "period_id" in changes or "parent_goal_id" in changes:
        await _check_goal_links(
            session, org_id, goal.id, changes.get("period_id", goal.period_id), changes.get("parent_goal_id", goal.parent_goal_id)
        )
    scope = changes.pop("scope", None)
    if scope is not None:
        goal.scope_unit_id, goal.scope_vertical_id = scope.get("unit_id"), scope.get("vertical_id")
    for field_name, value in changes.items():
        setattr(goal, field_name, value)
    goal.version += 1
    await session.flush()
    return await _goal_response(session, goal, directory)


async def set_goal_kpis(
    session: AsyncSession, org_id: uuid.UUID, goal_id: uuid.UUID, data: GoalKpisSet, directory: Directory
) -> GoalResponse:
    goal = await get_goal(session, org_id, goal_id)
    codes = [item.kpi_code for item in data.items]
    if len(set(codes)) != len(codes):
        raise ValidationFailedError("items", "each KPI may be linked once")
    kpis = {
        kpi.code: kpi
        for kpi in (
            await session.execute(
                select(KPIDefinition).where(KPIDefinition.organization_id == org_id, KPIDefinition.code.in_(codes))
            )
        ).scalars()
    } if codes else {}
    missing = [code for code in codes if code not in kpis]
    if missing:
        raise KPINotFoundError(missing[0])
    for link in (await session.execute(select(GoalKPI).where(GoalKPI.goal_id == goal.id))).scalars().all():
        await session.delete(link)
    await session.flush()
    session.add_all(GoalKPI(goal_id=goal.id, kpi_definition_id=kpis[item.kpi_code].id, weight=item.weight) for item in data.items)
    goal.version += 1
    await session.flush()
    return await _goal_response(session, goal, directory)


# --- Initiatives --------------------------------------------------------------


async def list_initiatives(
    session: AsyncSession,
    org_id: uuid.UUID,
    directory: Directory,
    goal_id: Optional[uuid.UUID],
    owner_user_id: Optional[uuid.UUID],
    status: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[InitiativeResponse]:
    query = select(Initiative).where(Initiative.organization_id == org_id)
    if goal_id is not None:
        query = query.where(Initiative.goal_id == goal_id)
    if owner_user_id is not None:
        query = query.where(Initiative.owner_user_id == owner_user_id)
    if status is not None:
        query = query.where(Initiative.status == status)
    rows, page = await paginate_by_id(session, query, Initiative, limit, cursor)
    return PageResponse(data=[await _initiative_response(session, row, directory) for row in rows], page=page)


async def create_initiative(
    session: AsyncSession, org_id: uuid.UUID, data: InitiativeCreate, directory: Directory
) -> InitiativeResponse:
    check_date_range(data.start_date, data.end_date)
    goal = await session.get(StrategicGoal, data.goal_id)
    if goal is None or goal.organization_id != org_id:
        raise UnknownReferenceError("STRATEGIC_GOAL_NOT_FOUND", "goal_id", "Goal not found.")
    duplicate = await session.execute(
        select(Initiative.id).where(Initiative.organization_id == org_id, Initiative.code == data.code)
    )
    if duplicate.first():
        raise DuplicateInitiativeCodeError(data.code)
    initiative = Initiative(organization_id=org_id, **data.model_dump())
    session.add(initiative)
    await session.flush()
    return await _initiative_response(session, initiative, directory)


async def get_initiative_response(
    session: AsyncSession, org_id: uuid.UUID, initiative_id: uuid.UUID, directory: Directory
) -> InitiativeResponse:
    return await _initiative_response(session, await get_initiative(session, org_id, initiative_id), directory)


async def update_initiative(
    session: AsyncSession, org_id: uuid.UUID, initiative_id: uuid.UUID, data: InitiativeUpdate, directory: Directory
) -> InitiativeResponse:
    initiative = await get_initiative(session, org_id, initiative_id)
    changes = data.model_dump(exclude_unset=True)
    check_date_range(changes.get("start_date", initiative.start_date), changes.get("end_date", initiative.end_date))
    for field_name, value in changes.items():
        setattr(initiative, field_name, value)
    await session.flush()
    return await _initiative_response(session, initiative, directory)


# --- Milestones ---------------------------------------------------------------


async def list_milestones(session: AsyncSession, org_id: uuid.UUID, initiative_id: uuid.UUID) -> list[MilestoneResponse]:
    await get_initiative(session, org_id, initiative_id)
    rows = (
        await session.execute(
            select(InitiativeMilestone)
            .where(InitiativeMilestone.initiative_id == initiative_id)
            .order_by(InitiativeMilestone.due_date, InitiativeMilestone.id)
        )
    ).scalars().all()
    return [_milestone_response(row) for row in rows]


async def create_milestone(
    session: AsyncSession, org_id: uuid.UUID, initiative_id: uuid.UUID, data: MilestoneCreate
) -> MilestoneResponse:
    await get_initiative(session, org_id, initiative_id)
    milestone = InitiativeMilestone(initiative_id=initiative_id, **data.model_dump())
    session.add(milestone)
    await session.flush()
    return _milestone_response(milestone)


async def update_milestone(
    session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID, data: MilestoneUpdate
) -> MilestoneResponse:
    milestone = await _get_milestone(session, org_id, milestone_id)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(milestone, field_name, value)
    if milestone.status == "done":
        milestone.progress_pct = 100
    await session.flush()
    return _milestone_response(milestone)


# --- Roadmap ------------------------------------------------------------------


async def _check_roadmap_initiative(session: AsyncSession, org_id: uuid.UUID, initiative_id: Optional[uuid.UUID]) -> None:
    if initiative_id is None:
        return
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None or initiative.organization_id != org_id:
        raise UnknownReferenceError("INITIATIVE_NOT_FOUND", "initiative_id", "Initiative not found.")


async def list_roadmap_items(
    session: AsyncSession, org_id: uuid.UUID, roadmap_code: Optional[str], initiative_id: Optional[uuid.UUID],
    limit: int, cursor: Optional[str],
) -> PageResponse[RoadmapItemResponse]:
    query = select(RoadmapItem).where(RoadmapItem.organization_id == org_id)
    if roadmap_code is not None:
        query = query.where(RoadmapItem.roadmap_code == roadmap_code)
    if initiative_id is not None:
        query = query.where(RoadmapItem.initiative_id == initiative_id)
    rows, page = await paginate_by_id(session, query, RoadmapItem, limit, cursor)
    return PageResponse(data=[_roadmap_response(row) for row in rows], page=page)


async def create_roadmap_item(session: AsyncSession, org_id: uuid.UUID, data: RoadmapItemCreate) -> RoadmapItemResponse:
    check_date_range(data.start_date, data.end_date)
    await _check_roadmap_initiative(session, org_id, data.initiative_id)
    item = RoadmapItem(organization_id=org_id, **data.model_dump())
    session.add(item)
    await session.flush()
    return _roadmap_response(item)


async def update_roadmap_item(
    session: AsyncSession, org_id: uuid.UUID, item_id: uuid.UUID, data: RoadmapItemUpdate
) -> RoadmapItemResponse:
    item = await get_in_org(session, RoadmapItem, item_id, org_id, RoadmapItemNotFoundError(str(item_id)))
    changes = data.model_dump(exclude_unset=True)
    check_date_range(changes.get("start_date", item.start_date), changes.get("end_date", item.end_date))
    if "initiative_id" in changes:
        await _check_roadmap_initiative(session, org_id, changes["initiative_id"])
    for field_name, value in changes.items():
        setattr(item, field_name, value)
    await session.flush()
    return _roadmap_response(item)


# --- Check-ins ----------------------------------------------------------------


async def _subject_for_check_in(
    session: AsyncSession, actor: Actor, goal_id: Optional[uuid.UUID], initiative_id: Optional[uuid.UUID]
) -> None:
    """Only the owner checks in, unless the caller manages goals (or initiatives)."""
    if goal_id is not None:
        owner, manage = (await get_goal(session, actor.organization_id, goal_id)).owner_user_id, permissions.GOAL_MANAGE
    else:
        owner = (await get_initiative(session, actor.organization_id, initiative_id)).owner_user_id
        manage = permissions.INITIATIVE_MANAGE
    if owner != actor.user_id and not actor.has(manage):
        raise PermissionDeniedError(manage, "Only the owner checks in on this, unless you manage it.")


async def create_check_in(
    session: AsyncSession,
    actor: Actor,
    data: CheckInCreate,
    directory: Directory,
    *,
    goal_id: Optional[uuid.UUID] = None,
    initiative_id: Optional[uuid.UUID] = None,
) -> CheckInResponse:
    await _subject_for_check_in(session, actor, goal_id, initiative_id)
    if data.period_id is not None:
        await period_reference(session, actor.organization_id, data.period_id)
    check_in = GoalCheckIn(
        organization_id=actor.organization_id,
        goal_id=goal_id,
        initiative_id=initiative_id,
        period_id=data.period_id,
        confidence=Decimal(str(data.confidence)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        rag=data.rag,
        narrative=data.narrative,
        author_user_id=actor.user_id,
    )
    session.add(check_in)
    await session.flush()
    await session.refresh(check_in)
    return await check_in_response(check_in, directory)


async def list_check_ins(
    session: AsyncSession,
    org_id: uuid.UUID,
    directory: Directory,
    limit: int,
    *,
    goal_id: Optional[uuid.UUID] = None,
    initiative_id: Optional[uuid.UUID] = None,
) -> list[CheckInResponse]:
    """The latest `limit` check-ins, newest first: the history of the owner's confidence."""
    if goal_id is not None:
        await get_goal(session, org_id, goal_id)
        query = select(GoalCheckIn).where(GoalCheckIn.goal_id == goal_id)
    else:
        await get_initiative(session, org_id, initiative_id)
        query = select(GoalCheckIn).where(GoalCheckIn.initiative_id == initiative_id)
    query = query.where(GoalCheckIn.organization_id == org_id).order_by(
        GoalCheckIn.created_at.desc(), GoalCheckIn.id.desc()
    ).limit(limit)
    return [await check_in_response(row, directory) for row in (await session.execute(query)).scalars().all()]
