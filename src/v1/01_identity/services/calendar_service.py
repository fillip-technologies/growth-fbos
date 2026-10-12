import logging
import re
from typing import Optional
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import (
    CalendarNotFoundError,
    PreconditionFailedError,
    PreconditionRequiredError,
    ValidationFailedError,
)
from models.calendar import Calendar, CalendarHoliday, CalendarWorkingDay
from schemas.calendar import (
    CalendarCreate,
    CalendarResponse,
    HolidayBatch,
    HolidayItem,
    WorkingDayItem,
)
from schemas.common import PageInfo, PaginatedResponse
from services.event_publisher import event_publisher

logger = logging.getLogger("identity.calendar_service")

_CLOCK = re.compile(r"^([01]\d|2[0-4]):([0-5]\d)$")


def _clock_minutes(clock: str) -> Optional[int]:
    """Minutes after midnight of an "HH:MM" time (up to 24:00), or None."""
    match = _CLOCK.match(clock)
    if not match:
        return None
    total = int(match.group(1)) * 60 + int(match.group(2))
    return total if total <= 24 * 60 else None


def _hours_problem(hours: list[tuple[str, str]]) -> Optional[str]:
    """What is wrong with one day's time ranges, or None."""
    ranges = []
    for start, end in hours:
        opens, closes = _clock_minutes(start), _clock_minutes(end)
        if opens is None or closes is None:
            return f"{start}–{end}: times must be HH:MM"
        if closes <= opens:
            return f"{start}–{end}: the end must be after the start"
        ranges.append((opens, closes))
    ranges.sort()
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            return "time ranges overlap"
    return None


def _working_day_errors(working_days: list[WorkingDayItem], holiday_dates: set) -> list[dict[str, str]]:
    errors = []
    seen = set()
    for index, day in enumerate(working_days):
        field = f"working_days.{index}"
        if day.date in seen:
            errors.append({"field": f"{field}.date", "issue": f"{day.date}: listed twice as a working day"})
        if day.date in holiday_dates:
            errors.append({"field": f"{field}.date", "issue": f"{day.date}: is also a holiday; keep one of the two"})
        seen.add(day.date)
        problem = _hours_problem(day.hours)
        if problem:
            errors.append({"field": f"{field}.hours", "issue": f"{day.date}: {problem}"})
    return errors


class CalendarService:
    def _build_response(self, calendar: Calendar) -> CalendarResponse:
        holidays = [
            HolidayItem(
                date=h.holiday_date,
                name=h.name,
                is_half_day=h.is_half_day,
            )
            for h in (calendar.holidays or [])
        ]
        working_days = [
            WorkingDayItem(date=w.work_date, name=w.name, hours=w.hours)
            for w in sorted(calendar.working_days or [], key=lambda w: w.work_date)
        ]
        return CalendarResponse(
            id=calendar.id,
            name=calendar.name,
            timezone=calendar.timezone,
            weekly_hours=calendar.weekly_hours,
            holidays=holidays,
            working_days=working_days,
            version=calendar.version,
        )

    async def list_calendars(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        limit: int = 25,
        cursor: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> PaginatedResponse[CalendarResponse]:
        query = (
            select(Calendar)
            .options(selectinload(Calendar.holidays))
            .where(Calendar.organization_id == organization_id)
        )

        if sort:
            sort_fields = [s.strip() for s in sort.split(",")]
            for field in sort_fields:
                if field.startswith("-"):
                    attr = field[1:]
                    if hasattr(Calendar, attr):
                        query = query.order_by(getattr(Calendar, attr).desc())
                else:
                    if hasattr(Calendar, field):
                        query = query.order_by(getattr(Calendar, field).asc())
        else:
            query = query.order_by(Calendar.name.asc(), Calendar.id.asc())

        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        calendars = list(result.scalars().all())

        has_more = len(calendars) > limit
        if has_more:
            calendars = calendars[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [self._build_response(c) for c in calendars]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def create_calendar(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: CalendarCreate,
    ) -> CalendarResponse:
        calendar = Calendar(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name=data.name,
            timezone=data.timezone,
            weekly_hours=data.weekly_hours,
            version=1,
        )
        session.add(calendar)
        await session.commit()
        await session.refresh(calendar)

        # Ensure holidays collection is loaded
        stmt = select(Calendar).options(selectinload(Calendar.holidays)).where(Calendar.id == calendar.id)
        calendar = (await session.execute(stmt)).scalar_one()

        await event_publisher.publish(
            "identity.calendar.created.v1",
            {
                "calendar_id": str(calendar.id),
                "organization_id": str(organization_id),
                "name": calendar.name,
                "timezone": calendar.timezone,
            },
        )

        return self._build_response(calendar)

    async def replace_holidays(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        calendar_id: uuid.UUID,
        data: HolidayBatch,
        if_match: Optional[str] = None,
    ) -> CalendarResponse:
        if if_match is None:
            raise PreconditionRequiredError("If-Match header is required")

        stmt = select(Calendar).options(selectinload(Calendar.holidays)).where(
            Calendar.id == calendar_id, Calendar.organization_id == organization_id
        )
        result = await session.execute(stmt)
        calendar = result.scalar_one_or_none()
        if not calendar:
            raise CalendarNotFoundError()

        clean_match = if_match.strip(' "')
        if clean_match.isdigit() and int(clean_match) != calendar.version:
            raise PreconditionFailedError(
                f"ETag mismatch. Current version is '{calendar.version}'"
            )

        # Without a list of working days, the ones the calendar has stay; a holiday mustn't land on one.
        working_days = data.working_days
        if working_days is None:
            working_days = [
                WorkingDayItem(date=w.work_date, name=w.name, hours=w.hours) for w in calendar.working_days
            ]
        errors = _working_day_errors(working_days, {h.date for h in data.holidays})
        if errors:
            raise ValidationFailedError(errors)

        # Clear existing holidays
        await session.execute(
            delete(CalendarHoliday).where(CalendarHoliday.calendar_id == calendar.id)
        )

        # Insert new holidays
        for h in data.holidays:
            holiday = CalendarHoliday(
                id=uuid.uuid4(),
                calendar_id=calendar.id,
                holiday_date=h.date,
                name=h.name,
                is_half_day=h.is_half_day,
            )
            session.add(holiday)

        if data.working_days is not None:
            await session.execute(
                delete(CalendarWorkingDay).where(CalendarWorkingDay.calendar_id == calendar.id)
            )
            for w in data.working_days:
                session.add(
                    CalendarWorkingDay(
                        id=uuid.uuid4(),
                        calendar_id=calendar.id,
                        work_date=w.date,
                        name=w.name.strip(),
                        hours=[list(r) for r in sorted(w.hours)],
                    )
                )

        calendar.version += 1
        await session.commit()
        await session.refresh(calendar)

        # Reload with updated holidays
        stmt = select(Calendar).options(selectinload(Calendar.holidays)).where(Calendar.id == calendar.id)
        calendar = (await session.execute(stmt)).scalar_one()

        await event_publisher.publish(
            "identity.calendar.updated.v1",
            {
                "calendar_id": str(calendar.id),
                "organization_id": str(organization_id),
                "version": calendar.version,
                "holiday_count": len(calendar.holidays),
                "working_day_count": len(calendar.working_days),
            },
        )

        return self._build_response(calendar)


calendar_service = CalendarService()
