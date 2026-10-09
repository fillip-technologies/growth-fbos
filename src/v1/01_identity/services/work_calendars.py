"""
Which working calendar each unit follows, for other services counting working time (delivery's
time limits): the unit's own calendar, else the nearest unit's above it, else the company's.
No calendar anywhere means no working hours are set, and time runs around the clock.
"""
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import OrganizationNotFoundError
from models.calendar import Calendar
from models.org_unit import OrgUnit
from models.organization import Organization
from schemas.calendar import WorkCalendar, WorkCalendarHoliday, WorkCalendarsResponse


async def work_calendars(session: AsyncSession, organization_id: uuid.UUID) -> WorkCalendarsResponse:
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise OrganizationNotFoundError()
    units = (
        await session.execute(
            select(OrgUnit.id, OrgUnit.path, OrgUnit.calendar_id).where(OrgUnit.organization_id == organization_id)
        )
    ).all()
    own_calendar = {unit.id: unit.calendar_id for unit in units}

    def followed(path: str) -> Optional[uuid.UUID]:
        for link in reversed(path.strip("/").split("/")):
            calendar_id = own_calendar.get(uuid.UUID(link)) if link else None
            if calendar_id is not None:
                return calendar_id
        return organization.calendar_id

    unit_calendars = {unit.id: followed(unit.path) for unit in units}
    used = {calendar_id for calendar_id in [*unit_calendars.values(), organization.calendar_id] if calendar_id}
    calendars = (
        await session.execute(select(Calendar).where(Calendar.id.in_(used), Calendar.organization_id == organization_id))
    ).scalars().all() if used else []
    return WorkCalendarsResponse(
        company_calendar_id=organization.calendar_id,
        unit_calendars=unit_calendars,
        calendars=[
            WorkCalendar(
                id=calendar.id,
                timezone=calendar.timezone,
                weekly_hours=calendar.weekly_hours or {},
                holidays=[WorkCalendarHoliday(date=h.holiday_date, is_half_day=h.is_half_day) for h in calendar.holidays],
            )
            for calendar in calendars
        ],
    )
