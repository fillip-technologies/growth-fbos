"""
The capacity ledger builder: one `capacity_ledger` row per resource and day (plan §4.4).

- capacity  = the working calendar's minutes that day x FTE (the resource's own calendar, else its
              unit's, else the company's; with none, `daily_capacity_minutes` x FTE on weekdays),
              minus approved absences (people) and availability exceptions, plus overtime.
- allocated = the minutes per day of every allocation covering a working day, soft (proposed) and
              hard (confirmed) alike: a soft booking that costs nothing is not a plan.
- actual    = effort recorded that day (delivery).
- overload  = allocated > capacity.

The ledger is a cache, never a source of truth: rebuilding a window deletes its rows and writes them
again from the sources, so the same inputs always give the same rows. Late leave approvals,
backdated timesheets and corrected calendars heal on the next rebuild. When delivery can't answer,
the actual minutes already in the ledger are kept rather than wiped.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ValidationFailedError
from models.resource import Allocation, AvailabilityException, CapacityLedger, Resource
from services.identity_client import IdentityClient
from services.source_clients import AbsenceClient, EffortClient
from services.work_calendar import WorkCalendar, calendar_from

MAX_WINDOW_DAYS = 400
BOOKING_STATUSES = ("proposed", "confirmed")
ADDS_CAPACITY = "overtime"


def as_utc(moment: datetime) -> datetime:
    """Stored datetimes come back without a zone (MySQL DATETIME); they are written in UTC."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def days_in(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def check_window(start: date, end: date) -> None:
    if end < start:
        raise ValidationFailedError("to", "must be on or after from")
    if (end - start).days + 1 > MAX_WINDOW_DAYS:
        raise ValidationFailedError("to", f"a window spans at most {MAX_WINDOW_DAYS} days")


@dataclass(frozen=True)
class Calendars:
    """Identity's calendars for one organization, and which one each unit follows."""

    by_id: dict[uuid.UUID, WorkCalendar]
    unit_calendar: dict[uuid.UUID, Optional[uuid.UUID]]
    company_calendar_id: Optional[uuid.UUID]

    def for_resource(self, resource: Resource) -> Optional[WorkCalendar]:
        for calendar_id in (
            resource.calendar_id,
            self.unit_calendar.get(resource.unit_id) if resource.unit_id else None,
            self.company_calendar_id,
        ):
            if calendar_id is not None and calendar_id in self.by_id:
                return self.by_id[calendar_id]
        return None


async def load_calendars(identity: IdentityClient, organization_id: uuid.UUID) -> Calendars:
    body = await identity.work_calendars(organization_id)
    by_id = {}
    for data in body.get("calendars") or []:
        parsed = calendar_from(data)
        if parsed is not None:
            by_id[uuid.UUID(str(data["id"]))] = parsed
    unit_calendar = {
        uuid.UUID(str(unit_id)): uuid.UUID(str(calendar_id)) if calendar_id else None
        for unit_id, calendar_id in (body.get("unit_calendars") or {}).items()
    }
    company = body.get("company_calendar_id")
    return Calendars(by_id, unit_calendar, uuid.UUID(str(company)) if company else None)


def base_minutes(resource: Resource, calendar: Optional[WorkCalendar], day: date) -> int:
    """The day's gross working minutes for the resource, before FTE and exceptions."""
    if calendar is not None:
        return calendar.day_minutes(day)
    return resource.daily_capacity_minutes if day.weekday() < 5 else 0


def _day_bounds(day: date, calendar: Optional[WorkCalendar]) -> tuple[datetime, datetime]:
    zone = calendar.zone if calendar is not None else timezone.utc
    start = datetime.combine(day, time(0), tzinfo=zone)
    return start, start + timedelta(days=1)


def exception_minutes_on(
    resource: Resource, calendar: Optional[WorkCalendar], day: date, starts_at: datetime, ends_at: datetime
) -> float:
    """Working minutes of `day` an exception covers, before FTE."""
    if calendar is not None:
        return calendar.minutes_within(day, starts_at, ends_at)
    day_start, day_end = _day_bounds(day, None)
    overlap = (min(day_end, ends_at) - max(day_start, starts_at)).total_seconds() / 60
    return min(max(overlap, 0.0), float(base_minutes(resource, None, day)))


def exception_total_minutes(
    resource: Resource, calendar: Optional[WorkCalendar], starts_at: datetime, ends_at: datetime
) -> int:
    zone = calendar.zone if calendar is not None else timezone.utc
    first, last = starts_at.astimezone(zone).date(), ends_at.astimezone(zone).date()
    total = sum(exception_minutes_on(resource, calendar, day, starts_at, ends_at) for day in days_in(first, last))
    return round(total * float(resource.fte))


@dataclass(frozen=True)
class RebuildOutcome:
    resources: int
    days: int
    rows: int
    absences_counted: bool
    actuals_counted: bool


async def rebuild(
    session: AsyncSession,
    identity: IdentityClient,
    absences: AbsenceClient,
    effort: EffortClient,
    organization_id: uuid.UUID,
    from_date: date,
    to_date: date,
    resource_ids: Optional[list[uuid.UUID]] = None,
) -> RebuildOutcome:
    check_window(from_date, to_date)
    query = select(Resource).where(
        Resource.organization_id == organization_id,
        Resource.status == "active",
        Resource.effective_from <= to_date,
        (Resource.effective_to.is_(None)) | (Resource.effective_to >= from_date),
    )
    if resource_ids:
        query = query.where(Resource.id.in_(resource_ids))
    resources = list((await session.execute(query)).scalars().all())
    if not resources:
        return RebuildOutcome(0, 0, 0, False, False)
    ids = [resource.id for resource in resources]

    calendars = await load_calendars(identity, organization_id)
    absence_rows = await absences.absences(organization_id, from_date, to_date)
    effort_rows = await effort.effort(organization_id, from_date, to_date)

    absent: dict[uuid.UUID, dict[date, bool]] = defaultdict(dict)  # user -> day -> half day only
    for absence in absence_rows or []:
        for day in days_in(max(absence.starts_on, from_date), min(absence.ends_on, to_date)):
            absent[absence.user_id][day] = absence.half_day and absent[absence.user_id].get(day, True)
    recorded: dict[tuple[uuid.UUID, date], int] = defaultdict(int)
    for row in effort_rows or []:
        recorded[(row.user_id, row.day)] += row.minutes

    window_start = datetime.combine(from_date, time(0), tzinfo=timezone.utc) - timedelta(days=1)
    window_end = datetime.combine(to_date, time(0), tzinfo=timezone.utc) + timedelta(days=2)
    exceptions = (
        await session.execute(
            select(AvailabilityException).where(
                AvailabilityException.resource_id.in_(ids),
                AvailabilityException.starts_at < window_end,
                AvailabilityException.ends_at > window_start,
            )
        )
    ).scalars().all()
    exceptions_of: dict[uuid.UUID, list[AvailabilityException]] = defaultdict(list)
    for exception in exceptions:
        exceptions_of[exception.resource_id].append(exception)

    allocations = (
        await session.execute(
            select(Allocation).where(
                Allocation.resource_id.in_(ids),
                Allocation.status.in_(BOOKING_STATUSES),
                Allocation.start_date <= to_date,
                Allocation.end_date >= from_date,
            )
        )
    ).scalars().all()
    allocations_of: dict[uuid.UUID, list[Allocation]] = defaultdict(list)
    for allocation in allocations:
        allocations_of[allocation.resource_id].append(allocation)

    kept_actuals: dict[tuple[uuid.UUID, date], int] = {}
    if effort_rows is None:
        previous = await session.execute(
            select(CapacityLedger.resource_id, CapacityLedger.day, CapacityLedger.actual_minutes).where(
                CapacityLedger.resource_id.in_(ids), CapacityLedger.day >= from_date, CapacityLedger.day <= to_date
            )
        )
        kept_actuals = {(row.resource_id, row.day): row.actual_minutes for row in previous}

    await session.execute(
        delete(CapacityLedger).where(
            CapacityLedger.resource_id.in_(ids), CapacityLedger.day >= from_date, CapacityLedger.day <= to_date
        )
    )

    rows = []
    for resource in resources:
        calendar = calendars.for_resource(resource)
        fte = float(resource.fte)
        first = max(from_date, resource.effective_from)
        last = min(to_date, resource.effective_to) if resource.effective_to else to_date
        for day in days_in(first, last):
            base = base_minutes(resource, calendar, day)
            capacity = base * fte
            half_day = absent.get(resource.user_id, {}).get(day) if resource.user_id else None
            if half_day is not None:
                capacity -= capacity / 2 if half_day else capacity
            for exception in exceptions_of[resource.id]:
                covered = exception_minutes_on(
                    resource, calendar, day, as_utc(exception.starts_at), as_utc(exception.ends_at)
                ) * fte
                capacity += covered if exception.exception_type == ADDS_CAPACITY else -covered
            allocated = sum(
                allocation.minutes_per_day
                for allocation in allocations_of[resource.id]
                if base > 0 and allocation.start_date <= day <= allocation.end_date
            )
            if effort_rows is not None:
                actual = recorded.get((resource.user_id, day), 0) if resource.user_id else 0
            else:
                actual = kept_actuals.get((resource.id, day), 0)
            capacity_minutes = max(0, round(capacity))
            rows.append(CapacityLedger(
                resource_id=resource.id, day=day, capacity_minutes=capacity_minutes,
                allocated_minutes=allocated, actual_minutes=actual, overload=allocated > capacity_minutes,
            ))
    session.add_all(rows)
    await session.flush()
    return RebuildOutcome(
        resources=len(resources),
        days=(to_date - from_date).days + 1,
        rows=len(rows),
        absences_counted=absence_rows is not None,
        actuals_counted=effort_rows is not None,
    )
