"""
Resources (the capacity projection of a person or a thing), the skills catalog, skill levels,
availability exceptions and the ledger they feed.

- A person has at most one resource row for any day: effective-dated rows of the same user can't
  overlap. A change from a date is a new row after closing the old one (`effective_to`).
- "Add from users" creates resources for active employees picked from identity, placed in their
  home unit; existing resources and people who aren't active employees are skipped and reported.
- `internal_cost_rate` is a rate-card figure set here. Only holders of `management.cost.read` see
  it or set it: it is effectively a pay band.
- Changing a resource or its exceptions rebuilds that resource's ledger for the affected days.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import (
    AvailabilityExceptionNotFoundError,
    DuplicateSkillCodeError,
    OverlapError,
    PermissionDeniedError,
    ResourceNotFoundError,
    SkillNotFoundError,
    UnknownReferenceError,
    ValidationFailedError,
)
from models.resource import AvailabilityException, CapacityLedger, Resource, ResourceSkill, Skill
from schemas.common import PageResponse
from schemas.resource import (
    AvailabilityExceptionCreate,
    AvailabilityExceptionResponse,
    LedgerDay,
    LedgerRebuildResponse,
    ResourceBatchCreate,
    ResourceBatchResponse,
    ResourceCreate,
    ResourceResponse,
    ResourceSkillSet,
    ResourceUpdate,
    SkillCreate,
    SkillLevel,
    SkillResponse,
    SkillUpdate,
    SkippedUser,
)
from services import capacity_ledger
from services.common import Directory, as_float, check_date_range, get_in_org
from services.identity_client import Actor, IdentityClient
from services.pagination import paginate_by_id
from services.source_clients import AbsenceClient, EffortClient

# How far ahead a change to a resource is rebuilt into the ledger straight away; the worker covers the rest.
REBUILD_AHEAD_DAYS = 120


class LedgerSources:
    """What a ledger rebuild needs, passed along together."""

    def __init__(self, identity: IdentityClient, absences: AbsenceClient, effort: EffortClient) -> None:
        self.identity = identity
        self.absences = absences
        self.effort = effort

    async def rebuild(
        self, session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date, resource_ids: Optional[list[uuid.UUID]] = None
    ) -> capacity_ledger.RebuildOutcome:
        return await capacity_ledger.rebuild(
            session, self.identity, self.absences, self.effort, org_id, from_date, to_date, resource_ids
        )


# --- Responses ----------------------------------------------------------------


async def skill_levels(session: AsyncSession, resource_id: uuid.UUID) -> list[SkillLevel]:
    rows = (
        await session.execute(
            select(Skill.code, ResourceSkill.level)
            .join(Skill, Skill.id == ResourceSkill.skill_id)
            .where(ResourceSkill.resource_id == resource_id)
            .order_by(Skill.code)
        )
    ).all()
    return [SkillLevel(code=row.code, level=row.level) for row in rows]


async def resource_response(
    session: AsyncSession, resource: Resource, directory: Directory, actor: Actor
) -> ResourceResponse:
    return ResourceResponse(
        id=resource.id,
        resource_type=resource.resource_type,
        user=await directory.user(resource.user_id),
        unit=await directory.unit(resource.unit_id),
        calendar_id=resource.calendar_id,
        employment_type=resource.employment_type,
        fte=float(resource.fte),
        daily_capacity_minutes=resource.daily_capacity_minutes,
        internal_cost_rate=as_float(resource.internal_cost_rate) if actor.has(permissions.COST_READ) else None,
        effective_from=resource.effective_from,
        effective_to=resource.effective_to,
        status=resource.status,
        skills=await skill_levels(session, resource.id),
    )


def _skill_response(skill: Skill) -> SkillResponse:
    return SkillResponse(id=skill.id, code=skill.code, name=skill.name, category=skill.category)


def exception_response(exception: AvailabilityException) -> AvailabilityExceptionResponse:
    return AvailabilityExceptionResponse(
        id=exception.id,
        resource_id=exception.resource_id,
        starts_at=capacity_ledger.as_utc(exception.starts_at),
        ends_at=capacity_ledger.as_utc(exception.ends_at),
        exception_type=exception.exception_type,
        minutes=exception.minutes,
        source=exception.source,
        reason=exception.reason,
    )


# --- Resources ----------------------------------------------------------------


async def get_resource(session: AsyncSession, org_id: uuid.UUID, resource_id: uuid.UUID) -> Resource:
    return await get_in_org(session, Resource, resource_id, org_id, ResourceNotFoundError(str(resource_id)))


async def _check_no_overlap(
    session: AsyncSession, org_id: uuid.UUID, user_id: Optional[uuid.UUID], start: date, end: Optional[date],
    exclude_id: Optional[uuid.UUID] = None,
) -> None:
    if user_id is None:
        return
    query = select(Resource).where(
        Resource.organization_id == org_id,
        Resource.user_id == user_id,
        (Resource.effective_to.is_(None)) | (Resource.effective_to >= start),
    )
    if end is not None:
        query = query.where(Resource.effective_from <= end)
    if exclude_id is not None:
        query = query.where(Resource.id != exclude_id)
    if (await session.execute(query.limit(1))).scalars().first():
        raise OverlapError(
            "RESOURCE_OVERLAP", "This person already has a resource for some of these dates; end it first."
        )


def _require_cost_access(actor: Actor) -> None:
    if not actor.has(permissions.COST_READ):
        raise PermissionDeniedError(permissions.COST_READ, "Setting a cost rate needs access to cost rates.")


async def _rebuild_resource(session: AsyncSession, sources: LedgerSources, resource: Resource) -> None:
    today = date.today()
    start = max(resource.effective_from, today - timedelta(days=31))
    end = today + timedelta(days=REBUILD_AHEAD_DAYS)
    if resource.effective_to is not None:
        end = min(end, max(resource.effective_to, start))
    # Rows outside the resource's dates disappear because the rebuild only writes days it is effective.
    await sources.rebuild(session, resource.organization_id, min(start, end), end, [resource.id])


async def list_resources(
    session: AsyncSession,
    actor: Actor,
    directory: Directory,
    unit_id: Optional[uuid.UUID],
    user_id: Optional[uuid.UUID],
    status: Optional[str],
    active_on: Optional[date],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[ResourceResponse]:
    query = select(Resource).where(Resource.organization_id == actor.organization_id)
    if unit_id is not None:
        query = query.where(Resource.unit_id == unit_id)
    if user_id is not None:
        query = query.where(Resource.user_id == user_id)
    if status is not None:
        query = query.where(Resource.status == status)
    if active_on is not None:
        query = query.where(
            Resource.effective_from <= active_on, (Resource.effective_to.is_(None)) | (Resource.effective_to >= active_on)
        )
    rows, page = await paginate_by_id(session, query, Resource, limit, cursor)
    return PageResponse(data=[await resource_response(session, row, directory, actor) for row in rows], page=page)


async def create_resource(
    session: AsyncSession, actor: Actor, data: ResourceCreate, directory: Directory, sources: LedgerSources
) -> ResourceResponse:
    if data.internal_cost_rate is not None:
        _require_cost_access(actor)
    if data.effective_to is not None:
        check_date_range(data.effective_from, data.effective_to, start_field="effective_from", end_field="effective_to")
    if data.resource_type in ("employee", "contractor") and data.user_id is None:
        raise ValidationFailedError("user_id", "a person's resource names the person; use a placeholder for an unnamed role")
    await _check_no_overlap(session, actor.organization_id, data.user_id, data.effective_from, data.effective_to)
    resource = Resource(organization_id=actor.organization_id, status="active", **data.model_dump())
    session.add(resource)
    await session.flush()
    await _rebuild_resource(session, sources, resource)
    return await resource_response(session, resource, directory, actor)


async def create_resources_from_users(
    session: AsyncSession, actor: Actor, data: ResourceBatchCreate, directory: Directory,
    identity: IdentityClient, sources: LedgerSources,
) -> ResourceBatchResponse:
    requested = list(dict.fromkeys(data.user_ids))
    employees = {employee.id: employee for employee in await identity.employees(actor.organization_id, requested)}
    created, skipped = [], []
    for user_id in requested:
        employee = employees.get(user_id)
        if employee is None:
            skipped.append(SkippedUser(user_id=user_id, reason="not_an_active_employee"))
            continue
        try:
            await _check_no_overlap(session, actor.organization_id, user_id, data.effective_from, None)
        except OverlapError:
            skipped.append(SkippedUser(user_id=user_id, reason="already_a_resource"))
            continue
        resource = Resource(
            organization_id=actor.organization_id, resource_type="employee", user_id=user_id,
            unit_id=employee.home_unit_id, employment_type=data.employment_type, fte=data.fte,
            daily_capacity_minutes=data.daily_capacity_minutes, effective_from=data.effective_from, status="active",
        )
        session.add(resource)
        await session.flush()
        created.append(resource)
    if created:
        today = date.today()
        start = max(data.effective_from, today - timedelta(days=31))
        await sources.rebuild(
            session, actor.organization_id, start, max(start, today + timedelta(days=REBUILD_AHEAD_DAYS)),
            [resource.id for resource in created],
        )
    return ResourceBatchResponse(
        created=[await resource_response(session, resource, directory, actor) for resource in created], skipped=skipped
    )


async def get_resource_response(
    session: AsyncSession, actor: Actor, resource_id: uuid.UUID, directory: Directory
) -> ResourceResponse:
    return await resource_response(session, await get_resource(session, actor.organization_id, resource_id), directory, actor)


async def update_resource(
    session: AsyncSession, actor: Actor, resource_id: uuid.UUID, data: ResourceUpdate, directory: Directory,
    sources: LedgerSources,
) -> ResourceResponse:
    resource = await get_resource(session, actor.organization_id, resource_id)
    changes = data.model_dump(exclude_unset=True)
    if "internal_cost_rate" in changes:
        _require_cost_access(actor)
    if "effective_to" in changes and changes["effective_to"] is not None:
        check_date_range(resource.effective_from, changes["effective_to"], start_field="effective_from", end_field="effective_to")
    for field_name, value in changes.items():
        setattr(resource, field_name, value)
    await session.flush()
    await _rebuild_resource(session, sources, resource)
    return await resource_response(session, resource, directory, actor)


# --- Skills -------------------------------------------------------------------


async def get_skill(session: AsyncSession, org_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
    return await get_in_org(session, Skill, skill_id, org_id, SkillNotFoundError(str(skill_id)))


async def skill_by_code(session: AsyncSession, org_id: uuid.UUID, code: str, field: str = "skill_code") -> Skill:
    skill = (await session.execute(select(Skill).where(Skill.organization_id == org_id, Skill.code == code))).scalars().first()
    if skill is None:
        raise UnknownReferenceError("SKILL_NOT_FOUND", field, f"Skill '{code}' not found.")
    return skill


async def list_skills(
    session: AsyncSession, org_id: uuid.UUID, category: Optional[str], limit: int, cursor: Optional[str]
) -> PageResponse[SkillResponse]:
    query = select(Skill).where(Skill.organization_id == org_id)
    if category is not None:
        query = query.where(Skill.category == category)
    rows, page = await paginate_by_id(session, query, Skill, limit, cursor)
    return PageResponse(data=[_skill_response(row) for row in rows], page=page)


async def create_skill(session: AsyncSession, org_id: uuid.UUID, data: SkillCreate) -> SkillResponse:
    exists = await session.execute(select(Skill.id).where(Skill.organization_id == org_id, Skill.code == data.code))
    if exists.first():
        raise DuplicateSkillCodeError(data.code)
    skill = Skill(organization_id=org_id, **data.model_dump())
    session.add(skill)
    await session.flush()
    return _skill_response(skill)


async def update_skill(session: AsyncSession, org_id: uuid.UUID, skill_id: uuid.UUID, data: SkillUpdate) -> SkillResponse:
    skill = await get_skill(session, org_id, skill_id)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(skill, field_name, value)
    await session.flush()
    return _skill_response(skill)


async def set_resource_skill(
    session: AsyncSession, actor: Actor, resource_id: uuid.UUID, skill_id: uuid.UUID, data: ResourceSkillSet,
    directory: Directory,
) -> ResourceResponse:
    resource = await get_resource(session, actor.organization_id, resource_id)
    await get_skill(session, actor.organization_id, skill_id)
    held = await session.get(ResourceSkill, (resource.id, skill_id))
    if held is None:
        held = ResourceSkill(resource_id=resource.id, skill_id=skill_id)
        session.add(held)
    held.level, held.years_experience, held.valid_until = data.level, data.years_experience, data.valid_until
    held.verified_by = actor.user_id
    await session.flush()
    return await resource_response(session, resource, directory, actor)


async def remove_resource_skill(session: AsyncSession, org_id: uuid.UUID, resource_id: uuid.UUID, skill_id: uuid.UUID) -> None:
    resource = await get_resource(session, org_id, resource_id)
    held = await session.get(ResourceSkill, (resource.id, skill_id))
    if held is None:
        raise SkillNotFoundError(str(skill_id))
    await session.delete(held)
    await session.flush()


# --- Availability exceptions --------------------------------------------------


async def list_exceptions(
    session: AsyncSession, org_id: uuid.UUID, resource_id: uuid.UUID, from_date: Optional[date], to_date: Optional[date]
) -> list[AvailabilityExceptionResponse]:
    await get_resource(session, org_id, resource_id)
    query = select(AvailabilityException).where(AvailabilityException.resource_id == resource_id)
    if to_date is not None:
        query = query.where(AvailabilityException.starts_at < _midnight(to_date + timedelta(days=1)))
    if from_date is not None:
        query = query.where(AvailabilityException.ends_at > _midnight(from_date))
    rows = (await session.execute(query.order_by(AvailabilityException.starts_at))).scalars().all()
    return [exception_response(row) for row in rows]


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=timezone.utc)


async def create_exception(
    session: AsyncSession, org_id: uuid.UUID, resource_id: uuid.UUID, data: AvailabilityExceptionCreate,
    sources: LedgerSources,
) -> AvailabilityExceptionResponse:
    resource = await get_resource(session, org_id, resource_id)
    calendars = await capacity_ledger.load_calendars(sources.identity, org_id)
    starts_at, ends_at = capacity_ledger.as_utc(data.starts_at), capacity_ledger.as_utc(data.ends_at)
    minutes = capacity_ledger.exception_total_minutes(resource, calendars.for_resource(resource), starts_at, ends_at)
    exception = AvailabilityException(
        resource_id=resource.id, starts_at=starts_at, ends_at=ends_at, exception_type=data.exception_type,
        minutes=minutes, source="manual", reason=data.reason,
    )
    session.add(exception)
    await session.flush()
    await sources.rebuild(session, org_id, starts_at.date() - timedelta(days=1), ends_at.date() + timedelta(days=1), [resource.id])
    return exception_response(exception)


async def delete_exception(
    session: AsyncSession, org_id: uuid.UUID, exception_id: uuid.UUID, sources: LedgerSources
) -> None:
    exception = await session.get(AvailabilityException, exception_id)
    resource = await session.get(Resource, exception.resource_id) if exception else None
    if exception is None or resource is None or resource.organization_id != org_id:
        raise AvailabilityExceptionNotFoundError(str(exception_id))
    window = (capacity_ledger.as_utc(exception.starts_at).date() - timedelta(days=1),
              capacity_ledger.as_utc(exception.ends_at).date() + timedelta(days=1))
    await session.delete(exception)
    await session.flush()
    await sources.rebuild(session, org_id, window[0], window[1], [resource.id])


# --- Ledger -------------------------------------------------------------------


async def ledger_days(
    session: AsyncSession, org_id: uuid.UUID, resource_id: uuid.UUID, from_date: date, to_date: date
) -> list[LedgerDay]:
    capacity_ledger.check_window(from_date, to_date)
    await get_resource(session, org_id, resource_id)
    rows = (
        await session.execute(
            select(CapacityLedger)
            .where(CapacityLedger.resource_id == resource_id, CapacityLedger.day >= from_date, CapacityLedger.day <= to_date)
            .order_by(CapacityLedger.day)
        )
    ).scalars().all()
    return [
        LedgerDay(
            resource_id=row.resource_id, day=row.day, capacity_minutes=row.capacity_minutes,
            allocated_minutes=row.allocated_minutes, actual_minutes=row.actual_minutes,
            free_minutes=max(0, row.capacity_minutes - row.allocated_minutes), overload=row.overload,
        )
        for row in rows
    ]


async def rebuild_ledger(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date, resource_ids: Optional[list[uuid.UUID]],
    sources: LedgerSources,
) -> LedgerRebuildResponse:
    for resource_id in resource_ids or []:
        await get_resource(session, org_id, resource_id)
    outcome = await sources.rebuild(session, org_id, from_date, to_date, resource_ids)
    return LedgerRebuildResponse(**outcome.__dict__)
