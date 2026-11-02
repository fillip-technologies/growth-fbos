"""
Resources, the capacity ledger and allocation: capacity from the calendar x FTE minus time off,
soft and hard bookings both consuming it, overload refused unless overridden (and audited),
demand filled by bookings, and the derived reads (availability, capacity, utilization, bench, gaps).

The test calendar works 09:00-17:00 UTC Monday to Friday (480 minutes). 2030-01-07 is a Monday.
"""
from datetime import date
import uuid

import pytest

from services.identity_client import Employee
from services.source_clients import Absence, Effort
from tests.conftest import BASE
from tests.helpers import ok, rebuild, resource

pytestmark = pytest.mark.asyncio

MON, TUE, WED, THU, FRI, SAT = "2030-01-07", "2030-01-08", "2030-01-09", "2030-01-10", "2030-01-11", "2030-01-12"
PROJECT = {"type": "project", "id": str(uuid.uuid4())}


async def ledger(client, resource_id: str, start: str = MON, end: str = SAT) -> dict[str, dict]:
    body = await ok(await client.get(f"{BASE}/resources/{resource_id}/capacity-ledger", params={"from": start, "to": end}))
    return {row["day"]: row for row in body["data"]}


async def book(client, resource_id: str, minutes: int, start: str = MON, end: str = FRI, **extra):
    return await client.post(f"{BASE}/allocations", json={
        "resource_id": resource_id, "subject": extra.pop("subject", PROJECT), "start_date": start, "end_date": end,
        "minutes_per_day": minutes, **extra,
    })


# --- The ledger ---------------------------------------------------------------


async def test_capacity_is_calendar_times_fte_minus_holidays(async_client, identity):
    identity.holidays = [{"date": TUE, "is_half_day": False}, {"date": WED, "is_half_day": True}]
    person = await resource(async_client, fte=0.5)
    await rebuild(async_client, MON, SAT)
    days = await ledger(async_client, person["id"])
    assert {day: row["capacity_minutes"] for day, row in days.items()} == {
        MON: 240, TUE: 0, WED: 120, THU: 240, FRI: 240, SAT: 0,
    }


async def test_without_a_calendar_the_gross_daily_capacity_applies_on_weekdays(async_client, identity):
    identity.has_calendar = False
    person = await resource(async_client, daily_capacity_minutes=420)
    await rebuild(async_client, MON, SAT)
    days = await ledger(async_client, person["id"])
    assert days[MON]["capacity_minutes"] == 420 and days[SAT]["capacity_minutes"] == 0


async def test_exceptions_take_away_working_minutes_and_overtime_adds(async_client):
    person = await resource(async_client)
    leave = await ok(await async_client.post(f"{BASE}/resources/{person['id']}/availability-exceptions", json={
        "starts_at": f"{WED}T10:00:00Z", "ends_at": f"{WED}T14:00:00Z", "exception_type": "leave",
    }), 201)
    assert leave["minutes"] == 240
    await ok(await async_client.post(f"{BASE}/resources/{person['id']}/availability-exceptions", json={
        "starts_at": f"{MON}T00:00:00Z", "ends_at": f"{TUE}T00:00:00Z", "exception_type": "leave",
    }), 201)
    days = await ledger(async_client, person["id"])
    assert days[WED]["capacity_minutes"] == 240 and days[MON]["capacity_minutes"] == 0 and days[TUE]["capacity_minutes"] == 480

    await ok(await async_client.delete(f"{BASE}/availability-exceptions/{leave['id']}"), 204)
    assert (await ledger(async_client, person["id"]))[WED]["capacity_minutes"] == 480
    naive = await async_client.post(f"{BASE}/resources/{person['id']}/availability-exceptions", json={
        "starts_at": f"{WED}T10:00:00", "ends_at": f"{WED}T14:00:00",
    })
    assert naive.status_code == 422


async def test_approved_absences_from_people_count_when_people_answers(async_client, absences):
    user = uuid.uuid4()
    person = await resource(async_client, user_id=user)
    absences.rows = [
        Absence(user_id=user, starts_on=date(2030, 1, 8), ends_on=date(2030, 1, 8)),
        Absence(user_id=user, starts_on=date(2030, 1, 9), ends_on=date(2030, 1, 9), half_day=True),
    ]
    outcome = await rebuild(async_client, MON, SAT)
    assert outcome["absences_counted"] is True and outcome["actuals_counted"] is False
    days = await ledger(async_client, person["id"])
    assert (days[TUE]["capacity_minutes"], days[WED]["capacity_minutes"]) == (0, 240)


async def test_rebuilding_is_idempotent_and_keeps_actuals_when_delivery_is_silent(async_client, effort):
    user = uuid.uuid4()
    person = await resource(async_client, user_id=user)
    effort.rows = [Effort(user_id=user, day=date(2030, 1, 7), minutes=300, billable=True, productive=True)]
    await rebuild(async_client, MON, SAT)
    first = await ledger(async_client, person["id"])
    assert first[MON]["actual_minutes"] == 300

    effort.rows = None  # delivery unreachable: what the ledger knew stays
    await rebuild(async_client, MON, SAT)
    assert await ledger(async_client, person["id"]) == first


# --- Resources ----------------------------------------------------------------


async def test_one_person_has_one_resource_per_day(async_client):
    user = uuid.uuid4()
    await resource(async_client, user_id=user, effective_to="2030-06-30")
    clash = await async_client.post(f"{BASE}/resources", json={"user_id": str(user), "effective_from": "2030-06-01"})
    assert clash.status_code == 409 and clash.json()["detail"]["code"] == "RESOURCE_OVERLAP"
    await resource(async_client, user_id=user, effective_from="2030-07-01")
    unnamed = await async_client.post(f"{BASE}/resources", json={"resource_type": "employee", "effective_from": "2030-01-01"})
    assert unnamed.status_code == 422


async def test_resources_from_users_skips_non_employees_and_existing_ones(async_client, identity):
    unit = uuid.uuid4()
    hired, already, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    identity.employees_by_id = {
        hired: Employee(id=hired, name="Asha", email="asha@x", home_unit_id=unit),
        already: Employee(id=already, name="Ben", email="ben@x"),
    }
    identity.units[unit] = "Platform"
    await resource(async_client, user_id=already)
    batch = await ok(await async_client.post(f"{BASE}/resources/batch", json={
        "user_ids": [str(hired), str(already), str(stranger)], "effective_from": "2030-01-01",
    }), 201)
    assert [r["user"]["id"] for r in batch["created"]] == [str(hired)]
    assert batch["created"][0]["unit"] == {"id": str(unit), "name": "Platform", "unit_type": None}
    assert {(s["user_id"], s["reason"]) for s in batch["skipped"]} == {
        (str(already), "already_a_resource"), (str(stranger), "not_an_active_employee"),
    }


# --- Bookings -----------------------------------------------------------------


async def test_soft_and_hard_bookings_both_consume_capacity(async_client):
    person = await resource(async_client)
    await ok(await book(async_client, person["id"], 300), 201)
    await ok(await book(async_client, person["id"], 180, status="confirmed"), 201)
    await rebuild(async_client, MON, SAT)
    days = await ledger(async_client, person["id"])
    assert days[MON]["allocated_minutes"] == 480 and days[SAT]["allocated_minutes"] == 0  # weekends aren't booked

    res = await book(async_client, person["id"], 60, start=THU, end=SAT)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "CAPACITY_EXCEEDED" and detail["meta"]["overload_days"] == [THU, FRI]
    assert (await ledger(async_client, person["id"]))[THU]["overload"] is False  # the refused booking left nothing behind


async def test_an_override_books_anyway_and_is_written_to_history(async_client):
    person = await resource(async_client)
    booked = await ok(await book(async_client, person["id"], 540, start=MON, end=MON, override_reason="Go-live"), 201)
    assert booked["overload_days"] == [MON] and booked["override_reason"] == "Go-live" and booked["approved_by"]
    history = (await ok(await async_client.get(f"{BASE}/allocations/{booked['id']}/history")))["data"]
    assert [h["change_type"] for h in history] == ["created", "override"]
    assert history[1]["after"] == {"reason": "Go-live", "overload_days": [MON]}


async def test_only_a_named_person_can_be_hard_booked(async_client):
    placeholder = await ok(await async_client.post(f"{BASE}/resources", json={
        "resource_type": "placeholder", "effective_from": "2030-01-01",
    }), 201)
    res = await book(async_client, placeholder["id"], 120, status="confirmed")
    assert res.status_code == 422 and res.json()["detail"]["code"] == "NAMED_RESOURCE_REQUIRED"
    soft = await ok(await book(async_client, placeholder["id"], 120), 201)
    res = await async_client.post(f"{BASE}/allocations/{soft['id']}/confirm", json={})
    assert res.status_code == 422


async def test_changing_and_cancelling_a_booking_moves_the_ledger(async_client):
    person = await resource(async_client)
    booking = await ok(await book(async_client, person["id"], 240, start=MON, end=TUE), 201)
    assert (await async_client.patch(f"{BASE}/allocations/{booking['id']}", json={"end_date": WED})).status_code == 428
    moved = await ok(await async_client.patch(
        f"{BASE}/allocations/{booking['id']}", json={"start_date": WED, "end_date": THU}, headers={"If-Match": "1"}
    ))
    days = await ledger(async_client, person["id"])
    assert (days[MON]["allocated_minutes"], days[WED]["allocated_minutes"]) == (0, 240)
    confirmed = await ok(await async_client.post(f"{BASE}/allocations/{moved['id']}/confirm", json={}))
    assert confirmed["status"] == "confirmed"
    await ok(await async_client.post(f"{BASE}/allocations/{moved['id']}/cancel", json={"reason": "Descoped"}))
    assert (await ledger(async_client, person["id"]))[WED]["allocated_minutes"] == 0
    history = (await ok(await async_client.get(f"{BASE}/allocations/{moved['id']}/history")))["data"]
    assert [h["change_type"] for h in history] == ["created", "updated", "confirmed", "cancelled"]
    assert history[1]["before"]["start_date"] == MON and history[1]["after"]["start_date"] == WED


async def test_a_booking_must_fall_within_the_resources_dates(async_client):
    person = await resource(async_client, effective_from="2030-01-08")
    res = await book(async_client, person["id"], 60, start=MON, end=TUE)
    assert res.status_code == 422


# --- Demand -------------------------------------------------------------------


async def _skill(client, code: str = "PY") -> dict:
    return await ok(await client.post(f"{BASE}/skills", json={"code": code, "name": "Python", "category": "engineering"}), 201)


async def test_requirements_fill_from_bookings_by_people_with_the_skill(async_client):
    skill = await _skill(async_client)
    novice, expert = await resource(async_client), await resource(async_client)
    await ok(await async_client.put(f"{BASE}/resources/{novice['id']}/skills/{skill['id']}", json={"level": 1}))
    await ok(await async_client.put(f"{BASE}/resources/{expert['id']}/skills/{skill['id']}", json={"level": 4}))
    requirement = await ok(await async_client.post(f"{BASE}/resource-requirements", json={
        "subject": PROJECT, "skill_code": "PY", "min_level": 3, "quantity": 1, "required_minutes": 960,
        "start_date": MON, "end_date": FRI,
    }), 201)
    assert requirement["status"] == "open"

    res = await book(async_client, novice["id"], 480, requirement_id=requirement["id"])
    assert res.status_code == 422 and res.json()["detail"]["code"] == "SKILL_MISMATCH"
    wrong_subject = await book(async_client, expert["id"], 480, requirement_id=requirement["id"], subject={"type": "project", "id": str(uuid.uuid4())})
    assert wrong_subject.status_code == 422

    await ok(await book(async_client, expert["id"], 480, start=MON, end=MON, requirement_id=requirement["id"]), 201)
    partly = await ok(await async_client.get(f"{BASE}/resource-requirements/{requirement['id']}"))
    assert (partly["status"], partly["allocated_minutes"], partly["allocated_people"]) == ("partially_filled", 480, 1)
    await ok(await book(async_client, expert["id"], 480, start=TUE, end=TUE, requirement_id=requirement["id"]), 201)
    assert (await ok(await async_client.get(f"{BASE}/resource-requirements/{requirement['id']}")))["status"] == "filled"


async def test_capacity_gaps_compare_unmet_demand_with_free_skilled_capacity(async_client):
    skill = await _skill(async_client)
    person = await resource(async_client)
    await ok(await async_client.put(f"{BASE}/resources/{person['id']}/skills/{skill['id']}", json={"level": 3}))
    await ok(await async_client.post(f"{BASE}/resource-requirements", json={
        "subject": PROJECT, "skill_code": "PY", "min_level": 2, "required_minutes": 3600,
        "start_date": MON, "end_date": FRI,
    }), 201)
    await rebuild(async_client, MON, FRI)
    gaps = (await ok(await async_client.post(f"{BASE}/capacity-gaps/calculations", json={"from": MON, "to": FRI})))["data"]
    assert len(gaps) == 1
    gap = gaps[0]
    assert (gap["required_minutes"], gap["available_minutes"], gap["gap_minutes"]) == (3600, 2400, 1200)
    assert gap["severity"] == "medium" and gap["skill"]["code"] == "PY"
    again = (await ok(await async_client.post(f"{BASE}/capacity-gaps/calculations", json={"from": MON, "to": FRI})))["data"]
    listed = (await ok(await async_client.get(f"{BASE}/capacity-gaps")))["data"]
    assert len(again) == 1 and [g["id"] for g in listed] == [again[0]["id"]]


# --- Reads --------------------------------------------------------------------


async def test_availability_and_unit_capacity(async_client, identity):
    unit = uuid.uuid4()
    identity.units[unit] = "Platform"
    skill = await _skill(async_client)
    busy, free = await resource(async_client, unit_id=str(unit)), await resource(async_client, unit_id=str(unit))
    await ok(await async_client.put(f"{BASE}/resources/{free['id']}/skills/{skill['id']}", json={"level": 2}))
    await ok(await book(async_client, busy["id"], 480, status="confirmed"), 201)
    await rebuild(async_client, MON, FRI)

    available = (await ok(await async_client.get(f"{BASE}/availability", params={"from": MON, "to": FRI, "skill": "PY", "min_level": 2})))["data"]
    assert [(row["resource_id"], row["free_minutes"]) for row in available] == [(free["id"], 2400)]

    summary = await ok(await async_client.get(f"{BASE}/capacity", params={"unit_id": str(unit), "from": MON, "to": FRI}))
    assert summary["unit"]["name"] == "Platform" and summary["from"] == MON
    assert (summary["capacity_minutes"], summary["allocated_minutes"], summary["utilization_pct"]) == (4800, 2400, 50.0)
    assert summary["by_skill"] == [{"skill": "PY", "capacity_minutes": 2400, "allocated_minutes": 0}]


async def test_utilization_is_denominated_by_calendar_capacity(async_client, effort):
    user = uuid.uuid4()
    await resource(async_client, user_id=user)
    await rebuild(async_client, MON, FRI)
    unknown = await ok(await async_client.get(f"{BASE}/utilization", params={"from": MON, "to": FRI}))
    assert unknown["actuals_available"] is False and unknown["data"][0]["billable_pct"] is None

    # Only billable time was logged: utilization is still billable / capacity, not 100%.
    effort.rows = [Effort(user_id=user, day=date(2030, 1, 7), minutes=480, billable=True, productive=True)]
    known = await ok(await async_client.get(f"{BASE}/utilization", params={"from": MON, "to": FRI}))
    row = known["data"][0]
    assert (row["capacity_minutes"], row["billable_minutes"], row["billable_pct"], row["total_pct"]) == (2400, 480, 20.0, 20.0)


async def test_the_bench_is_whoever_has_no_confirmed_booking_in_two_weeks(async_client):
    hard, soft, idle = [await resource(async_client) for _ in range(3)]
    await ok(await book(async_client, hard["id"], 240, status="confirmed"), 201)
    await ok(await book(async_client, soft["id"], 240), 201)
    await ok(await book(async_client, idle["id"], 240, start="2030-02-04", end="2030-02-08", status="confirmed"), 201)
    bench = await ok(await async_client.get(f"{BASE}/bench", params={"as_of": MON}))
    rows = {row["resource_id"]: row for row in bench["data"]}
    assert set(rows) == {soft["id"], idle["id"]}
    assert rows[soft["id"]]["soft_booked"] is True
    assert rows[idle["id"]]["next_confirmed_start"] == "2030-02-04"
