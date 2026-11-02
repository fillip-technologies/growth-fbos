"""
Demand and allocation, and the reads derived from the capacity ledger.

- A requirement is demand without a person (a placeholder): a skill at a minimum level, a number
  of people and of minutes, over dates. It is open, partially filled, filled or cancelled.
- An allocation reserves a resource's minutes per day against a subject (a project, an
  initiative). It is never a task assignment: delivery owns tasks.
- `proposed` is a soft booking, `confirmed` a hard one; both consume capacity. Only a named person
  can be hard-booked (Kantata's rule).
- Booking past capacity is refused (409 CAPACITY_EXCEEDED, listing the days), as Resource Guru does.
  Booking anyway needs `management.allocation.override` and a reason; who overrode, why and on which
  days goes into the allocation's history, where every change is written with before and after.
- Utilization is denominated by the ledger's calendar capacity, never by submitted time.
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    AllocationNotFoundError,
    InvalidStateTransitionError,
    NamedResourceRequiredError,
    PermissionDeniedError,
    ResourceOverloadedError,
    ResourceRequirementNotFoundError,
    SkillMismatchError,
    UnknownReferenceError,
    ValidationFailedError,
)
from models.resource import (
    Allocation,
    AllocationHistory,
    CapacityGap,
    CapacityLedger,
    Resource,
    ResourceRequirement,
    ResourceSkill,
    Skill,
)
from schemas.common import PageResponse, SubjectRef, UnitRef
from schemas.resource import (
    AllocationCreate,
    AllocationHistoryResponse,
    AllocationResponse,
    AllocationTransition,
    AllocationUpdate,
    BenchResponse,
    BenchRow,
    CapacityGapResponse,
    CapacitySummaryResponse,
    RequirementCreate,
    RequirementResponse,
    RequirementUpdate,
    ResourceAvailabilityResponse,
    ResourceRef,
    SkillCapacity,
    SkillRef,
    UtilizationResponse,
    UtilizationRow,
)
from services import capacity_ledger
from services.common import Directory, check_date_range, check_if_match, get_in_org
from services.identity_client import Actor
from services.pagination import paginate_by_id
from services.resource_service import LedgerSources, get_resource, skill_by_code, skill_levels
from services.source_clients import EffortClient

BOOKED = capacity_ledger.BOOKING_STATUSES
# "Unassigned for about two weeks" (10 working days) puts someone on the bench.
BENCH_WINDOW_DAYS = 14
PEOPLE_TYPES = ("employee", "contractor")


def _pct(part: int, whole: int) -> Optional[float]:
    return round(part / whole * 100, 1) if whole > 0 else None


# --- Availability and capacity ------------------------------------------------


async def _ledger_totals(
    session: AsyncSession, resource_ids: list[uuid.UUID], from_date: date, to_date: date
) -> dict[uuid.UUID, tuple[int, int, int, bool]]:
    """Per resource: capacity, allocated and actual minutes in the window, and whether any day is overloaded."""
    if not resource_ids:
        return {}
    rows = await session.execute(
        select(
            CapacityLedger.resource_id,
            func.sum(CapacityLedger.capacity_minutes),
            func.sum(CapacityLedger.allocated_minutes),
            func.sum(CapacityLedger.actual_minutes),
            func.max(CapacityLedger.overload),
        )
        .where(CapacityLedger.resource_id.in_(resource_ids), CapacityLedger.day >= from_date, CapacityLedger.day <= to_date)
        .group_by(CapacityLedger.resource_id)
    )
    return {row[0]: (int(row[1] or 0), int(row[2] or 0), int(row[3] or 0), bool(row[4])) for row in rows}


async def list_availability(
    session: AsyncSession,
    org_id: uuid.UUID,
    directory: Directory,
    from_date: date,
    to_date: date,
    skill: Optional[str],
    min_level: Optional[int],
    unit_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[ResourceAvailabilityResponse]:
    """Who is free in the window, from the ledger; filtered on skill and level before paging."""
    capacity_ledger.check_window(from_date, to_date)
    query = select(Resource).where(
        Resource.organization_id == org_id,
        Resource.status == "active",
        Resource.effective_from <= to_date,
        (Resource.effective_to.is_(None)) | (Resource.effective_to >= from_date),
    )
    if unit_id is not None:
        query = query.where(Resource.unit_id == unit_id)
    if skill is not None:
        skill_row = await skill_by_code(session, org_id, skill, field="skill")
        holders = select(ResourceSkill.resource_id).where(
            ResourceSkill.skill_id == skill_row.id, ResourceSkill.level >= (min_level or 1)
        )
        query = query.where(Resource.id.in_(holders))
    rows, page = await paginate_by_id(session, query, Resource, limit, cursor)
    totals = await _ledger_totals(session, [row.id for row in rows], from_date, to_date)
    data = []
    for resource in rows:
        capacity, allocated, _, _ = totals.get(resource.id, (0, 0, 0, False))
        data.append(ResourceAvailabilityResponse(
            resource_id=resource.id,
            user=await directory.user(resource.user_id),
            unit=await directory.unit(resource.unit_id),
            skills=await skill_levels(session, resource.id),
            capacity_minutes=capacity,
            allocated_minutes=allocated,
            free_minutes=max(0, capacity - allocated),
            utilization_pct=_pct(allocated, capacity) or 0.0,
        ))
    return PageResponse(data=data, page=page)


async def capacity_summary(
    session: AsyncSession, org_id: uuid.UUID, directory: Directory, unit_id: uuid.UUID, from_date: date, to_date: date
) -> CapacitySummaryResponse:
    capacity_ledger.check_window(from_date, to_date)
    resources = (
        await session.execute(
            select(Resource).where(Resource.organization_id == org_id, Resource.unit_id == unit_id, Resource.status == "active")
        )
    ).scalars().all()
    ids = [resource.id for resource in resources]
    totals = await _ledger_totals(session, ids, from_date, to_date)
    capacity = sum(t[0] for t in totals.values())
    allocated = sum(t[1] for t in totals.values())
    actual = sum(t[2] for t in totals.values())
    by_skill: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    if ids:
        held = await session.execute(
            select(ResourceSkill.resource_id, Skill.code).join(Skill, Skill.id == ResourceSkill.skill_id)
            .where(ResourceSkill.resource_id.in_(ids))
        )
        for resource_id, code in held:
            resource_capacity, resource_allocated, _, _ = totals.get(resource_id, (0, 0, 0, False))
            by_skill[code][0] += resource_capacity
            by_skill[code][1] += resource_allocated
    return CapacitySummaryResponse(
        unit=await directory.unit(unit_id) or UnitRef(id=unit_id),
        from_=from_date,
        to=to_date,
        capacity_minutes=capacity,
        allocated_minutes=allocated,
        actual_minutes=actual,
        utilization_pct=_pct(allocated, capacity) or 0.0,
        overloaded_resources=sum(1 for t in totals.values() if t[3]),
        by_skill=[SkillCapacity(skill=code, capacity_minutes=v[0], allocated_minutes=v[1]) for code, v in sorted(by_skill.items())],
    )


# --- Requirements -------------------------------------------------------------


async def _requirement_fill(session: AsyncSession, requirement: ResourceRequirement) -> tuple[int, int]:
    """(people, minutes) booked against the requirement inside its dates, from the ledger's working days."""
    allocations = (
        await session.execute(
            select(Allocation).where(Allocation.requirement_id == requirement.id, Allocation.status.in_(BOOKED))
        )
    ).scalars().all()
    minutes = 0
    for allocation in allocations:
        start = max(allocation.start_date, requirement.start_date)
        end = min(allocation.end_date, requirement.end_date)
        if end < start:
            continue
        # Bookings count on working days only; a day the booking counted on has allocated minutes in the ledger.
        days = (
            await session.execute(
                select(func.count()).select_from(CapacityLedger).where(
                    CapacityLedger.resource_id == allocation.resource_id,
                    CapacityLedger.day >= start, CapacityLedger.day <= end, CapacityLedger.allocated_minutes > 0,
                )
            )
        ).scalar_one()
        minutes += allocation.minutes_per_day * days
    return len({allocation.resource_id for allocation in allocations}), minutes


async def _refresh_requirement(session: AsyncSession, requirement_id: Optional[uuid.UUID]) -> None:
    if requirement_id is None:
        return
    requirement = await session.get(ResourceRequirement, requirement_id)
    if requirement is None or requirement.status == "cancelled":
        return
    people, minutes = await _requirement_fill(session, requirement)
    if people >= requirement.quantity and minutes >= requirement.required_minutes:
        requirement.status = "filled"
    elif people:
        requirement.status = "partially_filled"
    else:
        requirement.status = "open"
    await session.flush()


async def _requirement_response(session: AsyncSession, requirement: ResourceRequirement) -> RequirementResponse:
    skill = await session.get(Skill, requirement.skill_id) if requirement.skill_id else None
    people, minutes = await _requirement_fill(session, requirement)
    return RequirementResponse(
        id=requirement.id,
        subject=SubjectRef(type=requirement.subject_type, id=requirement.subject_id),
        skill=SkillRef(code=skill.code, name=skill.name) if skill else None,
        min_level=requirement.min_level,
        quantity=requirement.quantity,
        required_minutes=requirement.required_minutes,
        allocated_minutes=minutes,
        allocated_people=people,
        start_date=requirement.start_date,
        end_date=requirement.end_date,
        priority=requirement.priority,
        status=requirement.status,
    )


async def get_requirement(session: AsyncSession, org_id: uuid.UUID, requirement_id: uuid.UUID) -> ResourceRequirement:
    return await get_in_org(
        session, ResourceRequirement, requirement_id, org_id, ResourceRequirementNotFoundError(str(requirement_id))
    )


async def list_requirements(
    session: AsyncSession,
    org_id: uuid.UUID,
    status: Optional[str],
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[RequirementResponse]:
    query = select(ResourceRequirement).where(ResourceRequirement.organization_id == org_id)
    if status is not None:
        query = query.where(ResourceRequirement.status == status)
    if subject_type is not None:
        query = query.where(ResourceRequirement.subject_type == subject_type)
    if subject_id is not None:
        query = query.where(ResourceRequirement.subject_id == subject_id)
    rows, page = await paginate_by_id(session, query, ResourceRequirement, limit, cursor)
    return PageResponse(data=[await _requirement_response(session, row) for row in rows], page=page)


async def create_requirement(session: AsyncSession, org_id: uuid.UUID, data: RequirementCreate) -> RequirementResponse:
    check_date_range(data.start_date, data.end_date)
    skill = await skill_by_code(session, org_id, data.skill_code) if data.skill_code else None
    requirement = ResourceRequirement(
        organization_id=org_id, subject_type=data.subject.type, subject_id=data.subject.id,
        skill_id=skill.id if skill else None, min_level=data.min_level, quantity=data.quantity,
        required_minutes=data.required_minutes, start_date=data.start_date, end_date=data.end_date,
        priority=data.priority, status="open",
    )
    session.add(requirement)
    await session.flush()
    return await _requirement_response(session, requirement)


async def get_requirement_response(session: AsyncSession, org_id: uuid.UUID, requirement_id: uuid.UUID) -> RequirementResponse:
    return await _requirement_response(session, await get_requirement(session, org_id, requirement_id))


async def update_requirement(
    session: AsyncSession, org_id: uuid.UUID, requirement_id: uuid.UUID, data: RequirementUpdate
) -> RequirementResponse:
    requirement = await get_requirement(session, org_id, requirement_id)
    if requirement.status == "cancelled":
        raise InvalidStateTransitionError("requirement", requirement.status, "change")
    changes = data.model_dump(exclude_unset=True)
    check_date_range(changes.get("start_date", requirement.start_date), changes.get("end_date", requirement.end_date))
    for field_name, value in changes.items():
        setattr(requirement, field_name, value)
    await session.flush()
    await _refresh_requirement(session, requirement.id)
    return await _requirement_response(session, requirement)


async def cancel_requirement(session: AsyncSession, org_id: uuid.UUID, requirement_id: uuid.UUID) -> RequirementResponse:
    requirement = await get_requirement(session, org_id, requirement_id)
    if requirement.status == "cancelled":
        raise InvalidStateTransitionError("requirement", requirement.status, "cancel")
    requirement.status = "cancelled"
    await session.flush()
    return await _requirement_response(session, requirement)


# --- Allocations --------------------------------------------------------------


def _snapshot(allocation: Allocation) -> dict[str, Any]:
    return {
        "resource_id": str(allocation.resource_id),
        "requirement_id": str(allocation.requirement_id) if allocation.requirement_id else None,
        "subject": {"type": allocation.subject_type, "id": str(allocation.subject_id)},
        "start_date": allocation.start_date.isoformat(),
        "end_date": allocation.end_date.isoformat(),
        "minutes_per_day": allocation.minutes_per_day,
        "status": allocation.status,
        "version": allocation.version,
    }


def _history(allocation: Allocation, change_type: str, actor: Actor, before: Optional[dict], after: Optional[dict]) -> AllocationHistory:
    return AllocationHistory(
        allocation_id=allocation.id, change_type=change_type, before=before, after=after, changed_by=actor.user_id
    )


async def _allocation_response(
    allocation: Allocation, resource: Resource, directory: Directory, overload_days: list[date]
) -> AllocationResponse:
    return AllocationResponse(
        id=allocation.id,
        resource=ResourceRef(id=resource.id, user=await directory.user(resource.user_id)),
        requirement_id=allocation.requirement_id,
        subject=SubjectRef(type=allocation.subject_type, id=allocation.subject_id),
        start_date=allocation.start_date,
        end_date=allocation.end_date,
        minutes_per_day=allocation.minutes_per_day,
        status=allocation.status,
        override_reason=allocation.override_reason,
        approved_by=allocation.approved_by,
        version=allocation.version,
        overload_days=overload_days,
    )


def _check_named(resource: Resource) -> None:
    if resource.resource_type == "placeholder" or (resource.resource_type in PEOPLE_TYPES and resource.user_id is None):
        raise NamedResourceRequiredError()


def _check_within_resource(resource: Resource, start: date, end: date) -> None:
    check_date_range(start, end)
    capacity_ledger.check_window(start, end)
    if start < resource.effective_from or (resource.effective_to is not None and end > resource.effective_to):
        raise ValidationFailedError("start_date", "the booking must fall within the resource's effective dates")
    if resource.status != "active":
        raise ValidationFailedError("resource_id", "the resource isn't active")


async def _check_requirement(
    session: AsyncSession, org_id: uuid.UUID, requirement_id: uuid.UUID, resource: Resource, subject_type: str, subject_id: uuid.UUID
) -> None:
    requirement = await session.get(ResourceRequirement, requirement_id)
    if requirement is None or requirement.organization_id != org_id:
        raise UnknownReferenceError("RESOURCE_REQUIREMENT_NOT_FOUND", "requirement_id", "Requirement not found.")
    if requirement.status == "cancelled":
        raise InvalidStateTransitionError("requirement", requirement.status, "book against")
    if (requirement.subject_type, requirement.subject_id) != (subject_type, subject_id):
        raise ValidationFailedError("subject", "a booking against a requirement is for the requirement's subject")
    if requirement.skill_id is not None:
        held = await session.get(ResourceSkill, (resource.id, requirement.skill_id))
        if held is None or held.level < requirement.min_level:
            skill = await session.get(Skill, requirement.skill_id)
            raise SkillMismatchError(skill.code if skill else str(requirement.skill_id), requirement.min_level)


async def _overload_days(session: AsyncSession, resource_id: uuid.UUID, start: date, end: date) -> list[date]:
    rows = await session.execute(
        select(CapacityLedger.day).where(
            CapacityLedger.resource_id == resource_id, CapacityLedger.day >= start, CapacityLedger.day <= end,
            CapacityLedger.overload.is_(True),
        ).order_by(CapacityLedger.day)
    )
    return list(rows.scalars())


async def _book(
    session: AsyncSession,
    actor: Actor,
    sources: LedgerSources,
    allocation: Allocation,
    windows: list[tuple[date, date]],
    override_reason: Optional[str],
) -> list[date]:
    """Rebuild the affected days with the booking in place; refuse it on overload unless overridden."""
    start, end = min(w[0] for w in windows), max(w[1] for w in windows)
    await sources.rebuild(session, actor.organization_id, start, end, [allocation.resource_id])
    overloaded = await _overload_days(session, allocation.resource_id, allocation.start_date, allocation.end_date)
    if not overloaded or allocation.status == "cancelled":
        return []
    if not override_reason:
        raise ResourceOverloadedError([day.isoformat() for day in overloaded], allocation.minutes_per_day)
    if not actor.has(permissions.ALLOCATION_OVERRIDE):
        raise PermissionDeniedError(permissions.ALLOCATION_OVERRIDE, "Booking past capacity needs the override permission.")
    allocation.override_reason, allocation.approved_by = override_reason, actor.user_id
    session.add(_history(
        allocation, "override", actor, None,
        {"reason": override_reason, "overload_days": [day.isoformat() for day in overloaded]},
    ))
    return overloaded


async def create_allocation(
    session: AsyncSession, actor: Actor, data: AllocationCreate, directory: Directory, sources: LedgerSources
) -> AllocationResponse:
    resource = await get_resource(session, actor.organization_id, data.resource_id)
    _check_within_resource(resource, data.start_date, data.end_date)
    if data.status == "confirmed":
        _check_named(resource)
    if data.requirement_id is not None:
        await _check_requirement(session, actor.organization_id, data.requirement_id, resource, data.subject.type, data.subject.id)
    allocation = Allocation(
        id=uuid.uuid4(), resource_id=resource.id, organization_id=actor.organization_id,
        requirement_id=data.requirement_id, subject_type=data.subject.type, subject_id=data.subject.id,
        start_date=data.start_date, end_date=data.end_date, minutes_per_day=data.minutes_per_day,
        status=data.status, version=1,
    )
    session.add(allocation)
    await session.flush()
    session.add(_history(allocation, "created", actor, None, _snapshot(allocation)))
    overloaded = await _book(session, actor, sources, allocation, [(data.start_date, data.end_date)], data.override_reason)
    await _refresh_requirement(session, allocation.requirement_id)
    await session.flush()
    return await _allocation_response(allocation, resource, directory, overloaded)


async def _get_allocation(session: AsyncSession, org_id: uuid.UUID, allocation_id: uuid.UUID) -> Allocation:
    return await get_in_org(session, Allocation, allocation_id, org_id, AllocationNotFoundError(str(allocation_id)))


async def list_allocations(
    session: AsyncSession,
    org_id: uuid.UUID,
    directory: Directory,
    resource_id: Optional[uuid.UUID],
    requirement_id: Optional[uuid.UUID],
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    status: Optional[str],
    from_date: Optional[date],
    to_date: Optional[date],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[AllocationResponse]:
    query = select(Allocation).where(Allocation.organization_id == org_id)
    for column, value in (
        (Allocation.resource_id, resource_id), (Allocation.requirement_id, requirement_id),
        (Allocation.subject_type, subject_type), (Allocation.subject_id, subject_id), (Allocation.status, status),
    ):
        if value is not None:
            query = query.where(column == value)
    if from_date is not None:
        query = query.where(Allocation.end_date >= from_date)
    if to_date is not None:
        query = query.where(Allocation.start_date <= to_date)
    rows, page = await paginate_by_id(session, query, Allocation, limit, cursor)
    data = []
    for allocation in rows:
        resource = await session.get(Resource, allocation.resource_id)
        data.append(await _allocation_response(allocation, resource, directory, []))
    return PageResponse(data=data, page=page)


async def get_allocation(session: AsyncSession, org_id: uuid.UUID, allocation_id: uuid.UUID, directory: Directory) -> AllocationResponse:
    allocation = await _get_allocation(session, org_id, allocation_id)
    resource = await session.get(Resource, allocation.resource_id)
    overloaded = await _overload_days(session, allocation.resource_id, allocation.start_date, allocation.end_date)
    return await _allocation_response(allocation, resource, directory, overloaded if allocation.status in BOOKED else [])


async def update_allocation(
    session: AsyncSession, actor: Actor, allocation_id: uuid.UUID, data: AllocationUpdate, if_match: Optional[str],
    directory: Directory, sources: LedgerSources,
) -> AllocationResponse:
    allocation = await _get_allocation(session, actor.organization_id, allocation_id)
    check_if_match(if_match, allocation.version)
    if allocation.status not in BOOKED:
        raise InvalidStateTransitionError("allocation", allocation.status, "change")
    resource = await session.get(Resource, allocation.resource_id)
    before = _snapshot(allocation)
    old_window = (allocation.start_date, allocation.end_date)
    changes = data.model_dump(exclude_unset=True, exclude={"override_reason"})
    for field_name, value in changes.items():
        setattr(allocation, field_name, value)
    _check_within_resource(resource, allocation.start_date, allocation.end_date)
    allocation.version += 1
    await session.flush()
    session.add(_history(allocation, "updated", actor, before, _snapshot(allocation)))
    overloaded = await _book(
        session, actor, sources, allocation, [old_window, (allocation.start_date, allocation.end_date)], data.override_reason
    )
    await _refresh_requirement(session, allocation.requirement_id)
    await session.flush()
    return await _allocation_response(allocation, resource, directory, overloaded)


async def confirm_allocation(
    session: AsyncSession, actor: Actor, allocation_id: uuid.UUID, data: AllocationTransition, directory: Directory,
    sources: LedgerSources,
) -> AllocationResponse:
    """Soft to hard. Capacity is unchanged (soft bookings already count), but an overload must still be overridden."""
    allocation = await _get_allocation(session, actor.organization_id, allocation_id)
    if allocation.status != "proposed":
        raise InvalidStateTransitionError("allocation", allocation.status, "confirm")
    resource = await session.get(Resource, allocation.resource_id)
    _check_named(resource)
    before = _snapshot(allocation)
    allocation.status = "confirmed"
    allocation.version += 1
    session.add(_history(allocation, "confirmed", actor, before, _snapshot(allocation)))
    overloaded = await _book(
        session, actor, sources, allocation, [(allocation.start_date, allocation.end_date)],
        data.override_reason or allocation.override_reason,
    )
    await session.flush()
    return await _allocation_response(allocation, resource, directory, overloaded)


async def cancel_allocation(
    session: AsyncSession, actor: Actor, allocation_id: uuid.UUID, data: AllocationTransition, directory: Directory,
    sources: LedgerSources,
) -> AllocationResponse:
    allocation = await _get_allocation(session, actor.organization_id, allocation_id)
    if allocation.status not in BOOKED:
        raise InvalidStateTransitionError("allocation", allocation.status, "cancel")
    resource = await session.get(Resource, allocation.resource_id)
    before = _snapshot(allocation)
    allocation.status = "cancelled"
    allocation.version += 1
    after = {**_snapshot(allocation), "reason": data.reason}
    session.add(_history(allocation, "cancelled", actor, before, after))
    await session.flush()
    await sources.rebuild(session, actor.organization_id, allocation.start_date, allocation.end_date, [resource.id])
    await _refresh_requirement(session, allocation.requirement_id)
    return await _allocation_response(allocation, resource, directory, [])


async def allocation_history(session: AsyncSession, org_id: uuid.UUID, allocation_id: uuid.UUID) -> list[AllocationHistoryResponse]:
    allocation = await _get_allocation(session, org_id, allocation_id)
    rows = (
        await session.execute(
            select(AllocationHistory).where(AllocationHistory.allocation_id == allocation.id)
            .order_by(AllocationHistory.changed_at, AllocationHistory.id)
        )
    ).scalars().all()
    return [
        AllocationHistoryResponse(
            id=row.id, allocation_id=row.allocation_id, change_type=row.change_type, before=row.before,
            after=row.after, changed_by=row.changed_by, changed_at=row.changed_at,
        )
        for row in rows
    ]


# --- Capacity gaps ------------------------------------------------------------


def _severity(gap: int, demand: int) -> str:
    share = gap / demand if demand else 0
    if share >= 0.5:
        return "high"
    if share >= 0.2:
        return "medium"
    return "low" if gap > 0 else "none"


def _gap_response(gap: CapacityGap, skill: Optional[Skill]) -> CapacityGapResponse:
    return CapacityGapResponse(
        id=gap.id, skill=SkillRef(code=skill.code, name=skill.name) if skill else None, unit_id=gap.unit_id,
        period_start=gap.period_start, period_end=gap.period_end, required_minutes=gap.required_minutes,
        available_minutes=gap.available_minutes, gap_minutes=gap.gap_minutes, severity=gap.severity, status=gap.status,
    )


async def calculate_gaps(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> list[CapacityGapResponse]:
    """
    Unmet demand by skill over the window: what open requirements still need (prorated to the window)
    against the free ledger minutes of people holding the skill at the level asked for. Replaces the
    gaps previously calculated for the same window.
    """
    capacity_ledger.check_window(from_date, to_date)
    requirements = (
        await session.execute(
            select(ResourceRequirement).where(
                ResourceRequirement.organization_id == org_id,
                ResourceRequirement.status.in_(("open", "partially_filled")),
                ResourceRequirement.start_date <= to_date,
                ResourceRequirement.end_date >= from_date,
            )
        )
    ).scalars().all()
    demand: dict[Optional[uuid.UUID], int] = defaultdict(int)
    min_level: dict[Optional[uuid.UUID], int] = {}
    for requirement in requirements:
        _, booked = await _requirement_fill(session, requirement)
        remaining = max(0, requirement.required_minutes - booked)
        span = (requirement.end_date - requirement.start_date).days + 1
        inside = (min(requirement.end_date, to_date) - max(requirement.start_date, from_date)).days + 1
        demand[requirement.skill_id] += round(remaining * inside / span)
        min_level[requirement.skill_id] = min(min_level.get(requirement.skill_id, requirement.min_level), requirement.min_level)

    await session.execute(
        delete(CapacityGap).where(
            CapacityGap.organization_id == org_id, CapacityGap.period_start == from_date, CapacityGap.period_end == to_date
        )
    )
    gaps = []
    for skill_id, required in demand.items():
        if required <= 0:
            continue
        holders = select(Resource.id).where(Resource.organization_id == org_id, Resource.status == "active")
        if skill_id is not None:
            holders = holders.where(
                Resource.id.in_(select(ResourceSkill.resource_id).where(
                    ResourceSkill.skill_id == skill_id, ResourceSkill.level >= min_level[skill_id]
                ))
            )
        free = (
            await session.execute(
                select(func.sum(CapacityLedger.capacity_minutes - CapacityLedger.allocated_minutes)).where(
                    CapacityLedger.resource_id.in_(holders), CapacityLedger.day >= from_date, CapacityLedger.day <= to_date,
                    CapacityLedger.capacity_minutes > CapacityLedger.allocated_minutes,
                )
            )
        ).scalar_one_or_none()
        available = int(free or 0)
        gap_minutes = max(0, required - available)
        gap = CapacityGap(
            organization_id=org_id, skill_id=skill_id, unit_id=None, period_start=from_date, period_end=to_date,
            required_minutes=required, available_minutes=available, gap_minutes=gap_minutes,
            severity=_severity(gap_minutes, required), status="open" if gap_minutes else "covered",
        )
        session.add(gap)
        gaps.append(gap)
    await session.flush()
    return [_gap_response(gap, await session.get(Skill, gap.skill_id) if gap.skill_id else None) for gap in gaps]


async def list_gaps(
    session: AsyncSession, org_id: uuid.UUID, status: Optional[str], limit: int, cursor: Optional[str]
) -> PageResponse[CapacityGapResponse]:
    query = select(CapacityGap).where(CapacityGap.organization_id == org_id)
    if status is not None:
        query = query.where(CapacityGap.status == status)
    rows, page = await paginate_by_id(session, query, CapacityGap, limit, cursor)
    return PageResponse(
        data=[_gap_response(row, await session.get(Skill, row.skill_id) if row.skill_id else None) for row in rows], page=page
    )


# --- Utilization and the bench ------------------------------------------------


def _utilization_row(
    resource_id: uuid.UUID, user, capacity: int, allocated: int,
    recorded: Optional[int], billable: Optional[int], productive: Optional[int],
) -> UtilizationRow:
    return UtilizationRow(
        resource_id=resource_id, user=user, capacity_minutes=capacity, allocated_minutes=allocated,
        planned_pct=_pct(allocated, capacity), recorded_minutes=recorded, billable_minutes=billable,
        productive_minutes=productive,
        billable_pct=_pct(billable, capacity) if billable is not None else None,
        productive_pct=_pct(productive, capacity) if productive is not None else None,
        total_pct=_pct(recorded, capacity) if recorded is not None else None,
    )


async def utilization(
    session: AsyncSession, org_id: uuid.UUID, directory: Directory, effort: EffortClient,
    from_date: date, to_date: date, unit_id: Optional[uuid.UUID],
) -> UtilizationResponse:
    """Billable, productive and total utilization (recorded effort / ledger capacity), plus planned (booked / capacity)."""
    capacity_ledger.check_window(from_date, to_date)
    query = select(Resource).where(
        Resource.organization_id == org_id, Resource.status == "active", Resource.resource_type.in_(PEOPLE_TYPES)
    )
    if unit_id is not None:
        query = query.where(Resource.unit_id == unit_id)
    resources = (await session.execute(query)).scalars().all()
    totals = await _ledger_totals(session, [r.id for r in resources], from_date, to_date)
    effort_rows = await effort.effort(org_id, from_date, to_date)
    by_user: dict[uuid.UUID, list[int]] = defaultdict(lambda: [0, 0, 0])  # recorded, billable, productive
    for row in effort_rows or []:
        if from_date <= row.day <= to_date:
            by_user[row.user_id][0] += row.minutes
            by_user[row.user_id][1] += row.minutes if row.billable else 0
            by_user[row.user_id][2] += row.minutes if row.productive else 0
    available = effort_rows is not None
    rows, sums = [], [0, 0, 0, 0, 0]
    for resource in resources:
        capacity, allocated, _, _ = totals.get(resource.id, (0, 0, 0, False))
        recorded, billable, productive = by_user.get(resource.user_id, [0, 0, 0]) if available else (None, None, None)
        rows.append(_utilization_row(resource.id, await directory.user(resource.user_id), capacity, allocated, recorded, billable, productive))
        sums[0] += capacity
        sums[1] += allocated
        if available:
            sums[2] += recorded
            sums[3] += billable
            sums[4] += productive
    total = _utilization_row(
        uuid.UUID(int=0), None, sums[0], sums[1],
        sums[2] if available else None, sums[3] if available else None, sums[4] if available else None,
    )
    return UtilizationResponse(from_=from_date, to=to_date, actuals_available=available, totals=total, data=rows)


async def bench(
    session: AsyncSession, org_id: uuid.UUID, directory: Directory, as_of: date, unit_id: Optional[uuid.UUID]
) -> BenchResponse:
    """People with no confirmed booking in the next two weeks (about ten working days)."""
    window_end = as_of + timedelta(days=BENCH_WINDOW_DAYS - 1)
    query = select(Resource).where(
        Resource.organization_id == org_id, Resource.status == "active", Resource.resource_type.in_(PEOPLE_TYPES),
        Resource.effective_from <= as_of, (Resource.effective_to.is_(None)) | (Resource.effective_to >= as_of),
    )
    if unit_id is not None:
        query = query.where(Resource.unit_id == unit_id)
    resources = (await session.execute(query.order_by(Resource.id))).scalars().all()
    rows = []
    for resource in resources:
        overlapping = (
            await session.execute(
                select(Allocation.status).where(
                    Allocation.resource_id == resource.id, Allocation.status.in_(BOOKED),
                    Allocation.start_date <= window_end, Allocation.end_date >= as_of,
                )
            )
        ).scalars().all()
        if "confirmed" in overlapping:
            continue
        next_start = (
            await session.execute(
                select(func.min(Allocation.start_date)).where(
                    Allocation.resource_id == resource.id, Allocation.status == "confirmed", Allocation.start_date > window_end
                )
            )
        ).scalar_one_or_none()
        rows.append(BenchRow(
            resource_id=resource.id, user=await directory.user(resource.user_id), unit=await directory.unit(resource.unit_id),
            soft_booked=bool(overlapping), next_confirmed_start=next_start,
        ))
    return BenchResponse(as_of=as_of, window_end=window_end, data=rows)
