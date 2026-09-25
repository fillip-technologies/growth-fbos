"""Business logic for the Management service.

Simplifications:
- KPI result scope is reconstructed from the linked KPITarget; when no target
  is linked the scope defaults to empty.
- Manual measurements: source_type check against KPISource.source_type == 'manual';
  if no source exists the measurement is accepted (lenient for demo data).
- Capacity summary aggregates CapacityLedger rows for the unit's resources over
  the requested date range.
- Availability computes free_minutes as capacity - allocated from CapacityLedger.
- If-Match is enforced on KPITarget submit: version must match.
"""

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.performance import (
    CorrectiveAction,
    KPIDefinition,
    KPIMeasurement,
    KPIResult,
    KPISource,
    KPITarget,
)
from models.planning import PlanningPeriod
from models.resource import Allocation, CapacityLedger, Resource, ResourceSkill, Skill
from schemas.common import PageResponse, SubjectRef, UnitRef, UserRef
from schemas.management import (
    AllocationCreate,
    AllocationResponse,
    CapacitySummaryResponse,
    CorrectiveActionCreate,
    CorrectiveActionResponse,
    KpiDefinitionResponse,
    KpiRef,
    KpiRefWithDirection,
    KpiResultResponse,
    KpiScope,
    KpiSourceItem,
    KpiStatusRef,
    KpiTargetCreate,
    KpiTargetResponse,
    ManualMeasurementCreate,
    PeriodRef,
    ResourceAvailabilityResponse,
    ResourceRef,
    SkillCapacity,
    SkillLevel,
)
from services.pagination import paginate_by_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_if_match(if_match: Optional[str], current_version: int) -> None:
    from fastapi import HTTPException, status as http_status
    if if_match is None:
        raise HTTPException(
            status_code=428,
            detail={"code": "PRECONDITION_REQUIRED", "message": "If-Match header required.", "status": 428},
        )
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise HTTPException(
            status_code=412,
            detail={"code": "VERSION_CONFLICT", "message": f"Current version is {current_version}.", "status": 412},
        )


async def _get_kpi_def(session: AsyncSession, org_id: uuid.UUID, code: str) -> KPIDefinition:
    from fastapi import HTTPException
    res = await session.execute(
        select(KPIDefinition).where(KPIDefinition.organization_id == org_id, KPIDefinition.code == code)
    )
    kpi = res.scalars().first()
    if not kpi:
        raise HTTPException(status_code=422, detail={"code": "KPI_NOT_FOUND", "message": f"KPI '{code}' not found.", "status": 422})
    return kpi


async def _get_period(session: AsyncSession, org_id: uuid.UUID, period_id: uuid.UUID) -> PlanningPeriod:
    from fastapi import HTTPException
    period = await session.get(PlanningPeriod, period_id)
    if not period or period.organization_id != org_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Period not found.", "status": 404})
    return period


async def _build_target_response(session: AsyncSession, target: KPITarget) -> KpiTargetResponse:
    kpi = await session.get(KPIDefinition, target.kpi_definition_id)
    period = await session.get(PlanningPeriod, target.period_id)
    return KpiTargetResponse(
        id=target.id,
        kpi=KpiRef(code=kpi.code if kpi else "", name=kpi.name if kpi else "", unit=kpi.unit if kpi else ""),
        period=PeriodRef(id=period.id if period else target.period_id, name=period.name if period else ""),
        scope=KpiScope(unit_id=target.scope_unit_id, vertical_id=target.scope_vertical_id, user_id=target.scope_user_id),
        target_value=float(target.target_value),
        stretch_value=float(target.stretch_value) if target.stretch_value is not None else None,
        revision_no=target.revision_no,
        status=target.status,
        approval_request_id=target.approval_request_id,
    )


# ---------------------------------------------------------------------------
# KPI Targets
# ---------------------------------------------------------------------------


async def list_kpi_targets(
    session: AsyncSession, org_id: uuid.UUID,
    period_id: Optional[uuid.UUID], kpi_code: Optional[str], status: Optional[str],
    limit: int, cursor: Optional[str],
) -> PageResponse[KpiTargetResponse]:
    query = select(KPITarget).where(KPITarget.organization_id == org_id)
    if period_id is not None:
        query = query.where(KPITarget.period_id == period_id)
    if status is not None:
        query = query.where(KPITarget.status == status)
    if kpi_code is not None:
        kpi_res = await session.execute(select(KPIDefinition).where(KPIDefinition.organization_id == org_id, KPIDefinition.code == kpi_code))
        kpi = kpi_res.scalars().first()
        if kpi:
            query = query.where(KPITarget.kpi_definition_id == kpi.id)
        else:
            return PageResponse(data=[], page=__import__('schemas.common', fromlist=['PageMeta']).PageMeta())
    rows, page = await paginate_by_id(session, query, KPITarget, limit, cursor)
    data = [await _build_target_response(session, t) for t in rows]
    return PageResponse(data=data, page=page)


async def create_kpi_target(
    session: AsyncSession, org_id: uuid.UUID, data: KpiTargetCreate,
) -> KpiTargetResponse:
    from fastapi import HTTPException
    kpi = await _get_kpi_def(session, org_id, data.kpi_code)
    period = await _get_period(session, org_id, data.period_id)

    # Check no open draft/pending target for same kpi+period+scope
    existing = await session.execute(
        select(KPITarget).where(
            KPITarget.organization_id == org_id,
            KPITarget.kpi_definition_id == kpi.id,
            KPITarget.period_id == period.id,
            KPITarget.status.in_(["draft", "pending_approval"]),
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail={"code": "DUPLICATE_OPEN_REQUEST", "message": "Only one open approval (or draft target) per subject and type.", "status": 409})

    target = KPITarget(
        organization_id=org_id,
        kpi_definition_id=kpi.id,
        period_id=period.id,
        goal_id=data.goal_id,
        scope_unit_id=data.scope.unit_id,
        scope_vertical_id=data.scope.vertical_id,
        scope_user_id=data.scope.user_id,
        target_value=data.target_value,
        stretch_value=data.stretch_value,
        revision_no=1,
        status="draft",
        version=1,
    )
    session.add(target)
    await session.flush()
    return await _build_target_response(session, target)


async def submit_kpi_target(
    session: AsyncSession, org_id: uuid.UUID, target_id: uuid.UUID, if_match: Optional[str],
) -> KpiTargetResponse:
    from fastapi import HTTPException
    res = await session.execute(select(KPITarget).where(KPITarget.id == target_id, KPITarget.organization_id == org_id))
    target = res.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "KPI target not found.", "status": 404})
    _check_if_match(if_match, target.version)
    if target.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "INVALID_STATE_TRANSITION", "message": f"Cannot submit from status '{target.status}'.", "status": 409, "meta": {"current_status": target.status, "allowed_actions": []}})
    target.status = "pending_approval"
    target.version += 1
    await session.flush()
    return await _build_target_response(session, target)


# ---------------------------------------------------------------------------
# KPI Definitions
# ---------------------------------------------------------------------------


async def list_kpi_definitions(
    session: AsyncSession, org_id: uuid.UUID, limit: int, cursor: Optional[str],
) -> PageResponse[KpiDefinitionResponse]:
    query = select(KPIDefinition).where(KPIDefinition.organization_id == org_id)
    rows, page = await paginate_by_id(session, query, KPIDefinition, limit, cursor)
    data = []
    for kpi in rows:
        sources_res = await session.execute(select(KPISource).where(KPISource.kpi_definition_id == kpi.id))
        sources = [
            KpiSourceItem(event_type=s.event_type, value_path=s.value_path, filter=s.filter, dimensions=s.dimension_map)
            for s in sources_res.scalars().all()
        ]
        data.append(KpiDefinitionResponse(
            code=kpi.code, name=kpi.name, unit=kpi.unit, direction=kpi.direction,
            aggregation=kpi.aggregation, formula=kpi.formula, frequency=kpi.frequency,
            sources=sources, status=kpi.status,
        ))
    return PageResponse(data=data, page=page)


# ---------------------------------------------------------------------------
# KPI Results
# ---------------------------------------------------------------------------


async def list_kpi_results(
    session: AsyncSession, org_id: uuid.UUID,
    period_id: uuid.UUID, kpi_code: Optional[str], unit_id: Optional[uuid.UUID],
    vertical_id: Optional[uuid.UUID], status: Optional[str], limit: int, cursor: Optional[str],
) -> PageResponse[KpiResultResponse]:
    query = select(KPIResult).where(KPIResult.organization_id == org_id, KPIResult.period_id == period_id)
    if status is not None:
        query = query.where(KPIResult.status == status)
    if kpi_code is not None:
        kpi_res = await session.execute(select(KPIDefinition).where(KPIDefinition.code == kpi_code))
        kpi = kpi_res.scalars().first()
        if kpi:
            query = query.where(KPIResult.kpi_definition_id == kpi.id)
    rows, page = await paginate_by_id(session, query, KPIResult, limit, cursor)
    data = []
    for result in rows:
        kpi = await session.get(KPIDefinition, result.kpi_definition_id)
        period = await session.get(PlanningPeriod, result.period_id)
        # Reconstruct scope from linked target
        scope = KpiScope()
        if result.target_id:
            target = await session.get(KPITarget, result.target_id)
            if target:
                scope = KpiScope(unit_id=target.scope_unit_id, vertical_id=target.scope_vertical_id, user_id=target.scope_user_id)
        if unit_id and scope.unit_id != unit_id:
            continue
        if vertical_id and scope.vertical_id != vertical_id:
            continue
        data.append(KpiResultResponse(
            kpi=KpiRefWithDirection(code=kpi.code if kpi else "", name=kpi.name if kpi else "", unit=kpi.unit if kpi else "", direction=kpi.direction if kpi else "higher_is_better"),
            period=PeriodRef(id=period.id if period else result.period_id, name=period.name if period else ""),
            scope=scope,
            actual_value=float(result.actual_value),
            target_value=float(result.target_value),
            achievement_pct=float(result.achievement_pct),
            variance_abs=float(result.variance_abs),
            variance_pct=float(result.variance_pct),
            status=result.status,
            trend=result.trend,
            calculated_at=result.calculated_at,
        ))
    return PageResponse(data=data, page=page)


# ---------------------------------------------------------------------------
# Manual measurements
# ---------------------------------------------------------------------------


async def record_measurement(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: ManualMeasurementCreate,
) -> None:
    from fastapi import HTTPException
    kpi = await _get_kpi_def(session, org_id, data.kpi_code)
    # Check source_type: if any event-based source exists, reject
    sources_res = await session.execute(select(KPISource).where(KPISource.kpi_definition_id == kpi.id, KPISource.source_type != "manual"))
    if sources_res.scalars().first():
        raise HTTPException(status_code=422, detail={"code": "KPI_NOT_MANUAL", "message": "The KPI is fed by business events.", "status": 422})

    dims = data.dimensions or {}
    session.add(KPIMeasurement(
        kpi_definition_id=kpi.id,
        organization_id=org_id,
        measured_on=data.measured_on,
        value=data.value,
        unit_id=dims.get("unit_id"),
        vertical_id=dims.get("vertical_id"),
        user_id=dims.get("user_id"),
        source_type="manual",
        entered_by=user_id,
    ))
    await session.flush()


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------


async def list_corrective_actions(
    session: AsyncSession, org_id: uuid.UUID,
    status: Optional[str], owner_user_id: Optional[uuid.UUID], limit: int, cursor: Optional[str],
) -> PageResponse[CorrectiveActionResponse]:
    query = select(CorrectiveAction).where(CorrectiveAction.organization_id == org_id)
    if status is not None:
        query = query.where(CorrectiveAction.status == status)
    if owner_user_id is not None:
        query = query.where(CorrectiveAction.owner_user_id == owner_user_id)
    rows, page = await paginate_by_id(session, query, CorrectiveAction, limit, cursor)
    data = []
    for ca in rows:
        result = await session.get(KPIResult, ca.kpi_result_id)
        kpi = await session.get(KPIDefinition, result.kpi_definition_id) if result else None
        data.append(CorrectiveActionResponse(
            id=ca.id,
            title=ca.title,
            kpi=KpiStatusRef(code=kpi.code if kpi else "", status=result.status if result else "no_data"),
            owner=UserRef(id=ca.owner_user_id, name="Owner"),
            due_date=ca.due_date,
            task_id=ca.task_id,
            status=ca.status,
        ))
    return PageResponse(data=data, page=page)


async def create_corrective_action(
    session: AsyncSession, org_id: uuid.UUID, data: CorrectiveActionCreate,
) -> CorrectiveActionResponse:
    kpi = await _get_kpi_def(session, org_id, data.kpi_code)
    period = await _get_period(session, org_id, data.period_id)

    # Find or create a KPIResult for this kpi+period
    result_res = await session.execute(
        select(KPIResult).where(
            KPIResult.organization_id == org_id,
            KPIResult.kpi_definition_id == kpi.id,
            KPIResult.period_id == period.id,
        )
    )
    result = result_res.scalars().first()
    if not result:
        result = KPIResult(
            kpi_definition_id=kpi.id, organization_id=org_id, period_id=period.id,
            actual_value=0, target_value=0, achievement_pct=0,
            variance_abs=0, variance_pct=0, status="amber", trend="stable",
            calc_version=1, inputs_hash="",
        )
        session.add(result)
        await session.flush()

    ca = CorrectiveAction(
        kpi_result_id=result.id,
        organization_id=org_id,
        title=data.title,
        owner_user_id=data.owner_user_id,
        due_date=data.due_date,
        status="open",
    )
    session.add(ca)
    await session.flush()

    return CorrectiveActionResponse(
        id=ca.id, title=ca.title,
        kpi=KpiStatusRef(code=kpi.code, status=result.status),
        owner=UserRef(id=ca.owner_user_id, name="Owner"),
        due_date=ca.due_date, task_id=ca.task_id, status=ca.status,
    )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


async def list_availability(
    session: AsyncSession, org_id: uuid.UUID,
    from_date: date, to_date: date, skill: Optional[str],
    min_level: Optional[int], unit_id: Optional[uuid.UUID],
    limit: int, cursor: Optional[str],
) -> PageResponse[ResourceAvailabilityResponse]:
    query = select(Resource).where(Resource.organization_id == org_id, Resource.status == "active")
    if unit_id is not None:
        query = query.where(Resource.unit_id == unit_id)
    rows, page = await paginate_by_id(session, query, Resource, limit, cursor)

    data = []
    for resource in rows:
        # Skills
        rs_res = await session.execute(select(ResourceSkill).where(ResourceSkill.resource_id == resource.id))
        resource_skills = list(rs_res.all())

        if skill is not None:
            skill_res = await session.execute(select(Skill).where(Skill.organization_id == org_id, Skill.code == skill))
            skill_obj = skill_res.scalars().first()
            if not skill_obj:
                continue
            matching = [rs for rs in resource_skills if rs.skill_id == skill_obj.id]
            if not matching:
                continue
            if min_level and matching[0].level < min_level:
                continue

        # Aggregate capacity and allocated minutes over the date range
        cap_res = await session.execute(
            select(func.sum(CapacityLedger.capacity_minutes), func.sum(CapacityLedger.allocated_minutes))
            .where(CapacityLedger.resource_id == resource.id, CapacityLedger.day >= from_date, CapacityLedger.day <= to_date)
        )
        cap_row = cap_res.first()
        capacity_minutes = int(cap_row[0] or 0)
        allocated_minutes = int(cap_row[1] or 0)
        free_minutes = max(0, capacity_minutes - allocated_minutes)
        utilization_pct = round((allocated_minutes / capacity_minutes * 100), 1) if capacity_minutes > 0 else 0.0

        # Build skill list
        skill_list = []
        for rs in resource_skills:
            sk = await session.get(Skill, rs.skill_id)
            if sk:
                skill_list.append(SkillLevel(code=sk.code, level=rs.level))

        data.append(ResourceAvailabilityResponse(
            resource_id=resource.id,
            user=UserRef(id=resource.user_id or resource.id, name="Resource"),
            unit=UnitRef(id=resource.unit_id, name="Unit") if resource.unit_id else None,
            skills=skill_list,
            capacity_minutes=capacity_minutes,
            allocated_minutes=allocated_minutes,
            free_minutes=free_minutes,
            utilization_pct=utilization_pct,
        ))
    return PageResponse(data=data, page=page)


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------


async def create_allocation(
    session: AsyncSession, org_id: uuid.UUID, data: AllocationCreate,
) -> AllocationResponse:
    from fastapi import HTTPException
    resource = await session.get(Resource, data.resource_id)
    if not resource or resource.organization_id != org_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Resource not found.", "status": 404})

    # Check capacity on each day in range
    from datetime import timedelta
    overload_days = []
    current = data.start_date
    while current <= data.end_date:
        cap_res = await session.execute(
            select(CapacityLedger).where(CapacityLedger.resource_id == resource.id, CapacityLedger.day == current)
        )
        ledger = cap_res.scalars().first()
        if ledger:
            if ledger.allocated_minutes + data.minutes_per_day > ledger.capacity_minutes:
                overload_days.append(current)
        current += timedelta(days=1)

    if overload_days and not data.override_reason:
        raise HTTPException(
            status_code=409,
            detail={"code": "CAPACITY_EXCEEDED", "message": "Allocated minutes would exceed capacity on some days.", "status": 409, "meta": {"overload_days": [str(d) for d in overload_days], "capacity_minutes": resource.daily_capacity_minutes, "requested_minutes": data.minutes_per_day}},
        )

    allocation = Allocation(
        resource_id=data.resource_id,
        organization_id=org_id,
        requirement_id=data.requirement_id,
        subject_type=data.subject.type,
        subject_id=data.subject.id,
        start_date=data.start_date,
        end_date=data.end_date,
        minutes_per_day=data.minutes_per_day,
        status="confirmed",
        override_reason=data.override_reason,
        version=1,
    )
    session.add(allocation)
    await session.flush()

    return AllocationResponse(
        id=allocation.id,
        resource=ResourceRef(id=resource.id, user=UserRef(id=resource.user_id or resource.id, name="Resource")),
        subject={"type": data.subject.type, "id": data.subject.id},
        start_date=allocation.start_date,
        end_date=allocation.end_date,
        minutes_per_day=allocation.minutes_per_day,
        status=allocation.status,
        overload_days=overload_days,
    )


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------


async def get_capacity(
    session: AsyncSession, org_id: uuid.UUID,
    unit_id: uuid.UUID, from_date: date, to_date: date,
) -> CapacitySummaryResponse:
    resources_res = await session.execute(
        select(Resource).where(Resource.organization_id == org_id, Resource.unit_id == unit_id, Resource.status == "active")
    )
    resources = list(resources_res.scalars().all())
    resource_ids = [r.id for r in resources]

    cap_minutes = alloc_minutes = actual_minutes = 0
    overloaded_resources = 0

    if resource_ids:
        agg_res = await session.execute(
            select(func.sum(CapacityLedger.capacity_minutes), func.sum(CapacityLedger.allocated_minutes), func.sum(CapacityLedger.actual_minutes))
            .where(CapacityLedger.resource_id.in_(resource_ids), CapacityLedger.day >= from_date, CapacityLedger.day <= to_date)
        )
        row = agg_res.first()
        cap_minutes = int(row[0] or 0)
        alloc_minutes = int(row[1] or 0)
        actual_minutes = int(row[2] or 0)

        overload_res = await session.execute(
            select(func.count(CapacityLedger.resource_id.distinct()))
            .where(CapacityLedger.resource_id.in_(resource_ids), CapacityLedger.day >= from_date, CapacityLedger.day <= to_date, CapacityLedger.overload == True)
        )
        overloaded_resources = int(overload_res.scalar_one() or 0)

    utilization_pct = round((alloc_minutes / cap_minutes * 100), 1) if cap_minutes > 0 else 0.0

    return CapacitySummaryResponse(
        unit=UnitRef(id=unit_id, name="Unit"),
        from_=from_date,
        to=to_date,
        capacity_minutes=cap_minutes,
        allocated_minutes=alloc_minutes,
        actual_minutes=actual_minutes,
        utilization_pct=utilization_pct,
        overloaded_resources=overloaded_resources,
        by_skill=[],
    )
