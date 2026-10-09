"""
/internal/work-calendars: which working calendar each unit follows (its own, else the nearest
unit's above it, else the company's), for delivery's time limits in working hours.
"""
from datetime import date
import uuid

import pytest

from config import settings
from models.calendar import Calendar, CalendarHoliday
from models.org_unit import OrgUnit
from models.organization import Organization
from tests.conftest import TEST_ORG_ID
from tests.test_internal_people import API, make_unit

WORK_CALENDARS = f"{API}/internal/work-calendars"
WEEKDAYS_9_TO_6 = {day: [["09:00", "18:00"]] for day in ("mon", "tue", "wed", "thu", "fri")}


async def add_calendar(db_session, name: str, timezone: str = "Asia/Kolkata") -> Calendar:
    calendar = Calendar(id=uuid.uuid4(), organization_id=TEST_ORG_ID, name=name, timezone=timezone, weekly_hours=WEEKDAYS_9_TO_6)
    db_session.add(calendar)
    await db_session.flush()
    return calendar


@pytest.mark.asyncio
async def test_each_unit_follows_its_own_calendar_else_the_nearest_above_else_the_companys(async_client, db_session):
    branch = await make_unit(async_client, "BR", "branch")
    sales = await make_unit(async_client, "SALES", "department", branch)
    inside = await make_unit(async_client, "INSIDE", "team", sales)
    ops = await make_unit(async_client, "OPS", "department", branch)

    company = await add_calendar(db_session, "Head office")
    night_shift = await add_calendar(db_session, "Night shift", timezone="UTC")
    db_session.add(CalendarHoliday(id=uuid.uuid4(), calendar_id=night_shift.id, holiday_date=date(2026, 10, 20), name="Diwali", is_half_day=True))
    (await db_session.get(Organization, TEST_ORG_ID)).calendar_id = company.id
    (await db_session.get(OrgUnit, uuid.UUID(sales))).calendar_id = night_shift.id
    await db_session.commit()

    res = await async_client.get(WORK_CALENDARS, params={"organization_id": str(TEST_ORG_ID)})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["company_calendar_id"] == str(company.id)
    following = {unit: body["unit_calendars"][unit] for unit in (branch, sales, inside, ops)}
    assert following == {branch: str(company.id), sales: str(night_shift.id), inside: str(night_shift.id), ops: str(company.id)}
    calendars = {c["id"]: c for c in body["calendars"]}
    assert set(calendars) == {str(company.id), str(night_shift.id)}
    assert calendars[str(night_shift.id)]["timezone"] == "UTC"
    assert calendars[str(night_shift.id)]["holidays"] == [{"date": "2026-10-20", "is_half_day": True}]
    assert calendars[str(company.id)]["weekly_hours"]["mon"] == [["09:00", "18:00"]]


@pytest.mark.asyncio
async def test_without_any_calendar_time_runs_around_the_clock(async_client):
    branch = await make_unit(async_client, "BR", "branch")
    body = (await async_client.get(WORK_CALENDARS, params={"organization_id": str(TEST_ORG_ID)})).json()
    assert (body["company_calendar_id"], body["unit_calendars"][branch], body["calendars"]) == (None, None, [])


@pytest.mark.asyncio
async def test_an_unknown_organization_and_a_missing_token_are_refused(async_client, monkeypatch):
    assert (await async_client.get(WORK_CALENDARS, params={"organization_id": str(uuid.uuid4())})).status_code == 404
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    assert (await async_client.get(WORK_CALENDARS, params={"organization_id": str(TEST_ORG_ID)})).status_code == 403
