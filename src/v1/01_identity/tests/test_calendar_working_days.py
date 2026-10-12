"""
Extra working days on a working calendar: a date worked on with its own hours, usually one the
week leaves off. They are saved with the holidays (PUT /calendars/{id}/holidays); a client that
doesn't send them leaves them as they are.
"""
import httpx
import pytest

CALENDARS = "/api/identity/v1/calendars"
WEEKDAYS_9_TO_6 = {day: [["09:00", "18:00"]] for day in ("mon", "tue", "wed", "thu", "fri")}
SATURDAY = {"date": "2026-10-17", "name": "Diwali make-up day", "hours": [["14:00", "18:00"], ["09:00", "13:00"]]}


async def new_calendar(client: httpx.AsyncClient) -> dict:
    res = await client.post(CALENDARS, json={"name": "Head office", "timezone": "Asia/Kolkata", "weekly_hours": WEEKDAYS_9_TO_6})
    assert res.status_code == 201, res.text
    return res.json()


async def save(client: httpx.AsyncClient, calendar: dict, body: dict) -> httpx.Response:
    return await client.put(f"{CALENDARS}/{calendar['id']}/holidays", json=body, headers={"If-Match": f'"{calendar["version"]}"'})


@pytest.mark.asyncio
async def test_working_days_are_saved_with_the_holidays_and_listed(async_client):
    calendar = await new_calendar(async_client)
    assert calendar["working_days"] == []

    res = await save(async_client, calendar, {
        "holidays": [{"date": "2026-10-20", "name": "Diwali", "is_half_day": False}],
        "working_days": [SATURDAY],
    })
    assert res.status_code == 200, res.text
    saved = res.json()
    assert saved["version"] == calendar["version"] + 1
    assert [h["date"] for h in saved["holidays"]] == ["2026-10-20"]
    # Ranges come back in order.
    assert saved["working_days"] == [{**SATURDAY, "hours": [["09:00", "13:00"], ["14:00", "18:00"]]}]

    listed = (await async_client.get(CALENDARS)).json()["data"]
    assert next(c for c in listed if c["id"] == calendar["id"])["working_days"] == saved["working_days"]


@pytest.mark.asyncio
async def test_saving_without_working_days_keeps_them_and_an_empty_list_clears_them(async_client):
    calendar = await new_calendar(async_client)
    calendar = (await save(async_client, calendar, {"holidays": [], "working_days": [SATURDAY]})).json()

    # An older client sends only the holidays.
    res = await save(async_client, calendar, {"holidays": [{"date": "2026-12-25", "name": "Christmas", "is_half_day": False}]})
    assert res.status_code == 200, res.text
    calendar = res.json()
    assert [w["date"] for w in calendar["working_days"]] == ["2026-10-17"]
    assert [h["date"] for h in calendar["holidays"]] == ["2026-12-25"]

    calendar = (await save(async_client, calendar, {"holidays": [], "working_days": []})).json()
    assert calendar["working_days"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("hours, issue", [
    ([["18:00", "09:00"]], "18:00–09:00: the end must be after the start"),
    ([["9:00", "13:00"]], "9:00–13:00: times must be HH:MM"),
    ([["09:00", "13:00"], ["12:00", "18:00"]], "time ranges overlap"),
])
async def test_wrong_hours_are_refused(async_client, hours, issue):
    calendar = await new_calendar(async_client)
    res = await save(async_client, calendar, {"holidays": [], "working_days": [{**SATURDAY, "hours": hours}]})
    assert res.status_code == 422, res.text
    body = res.json()
    assert body["code"] == "VALIDATION_FAILED"
    assert body["errors"] == [{"field": "working_days.0.hours", "issue": f"2026-10-17: {issue}"}]


@pytest.mark.asyncio
async def test_a_day_without_hours_is_refused(async_client):
    calendar = await new_calendar(async_client)
    res = await save(async_client, calendar, {"holidays": [], "working_days": [{**SATURDAY, "hours": []}]})
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_a_date_twice_or_both_holiday_and_working_day_is_refused(async_client):
    calendar = await new_calendar(async_client)
    twice = await save(async_client, calendar, {"holidays": [], "working_days": [SATURDAY, SATURDAY]})
    assert twice.status_code == 422, twice.text
    assert twice.json()["errors"] == [{"field": "working_days.1.date", "issue": "2026-10-17: listed twice as a working day"}]

    both = await save(async_client, calendar, {
        "holidays": [{"date": "2026-10-17", "name": "Festival", "is_half_day": False}],
        "working_days": [SATURDAY],
    })
    assert both.status_code == 422, both.text
    assert both.json()["errors"][0]["field"] == "working_days.0.date"

    # Nothing was saved, so the version is unchanged.
    calendar = (await save(async_client, calendar, {"holidays": [], "working_days": [SATURDAY]})).json()
    # A holiday sent alone mustn't land on a working day the calendar keeps.
    kept = await save(async_client, calendar, {"holidays": [{"date": "2026-10-17", "name": "Festival", "is_half_day": False}]})
    assert kept.status_code == 422, kept.text
