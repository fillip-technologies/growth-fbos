"""
Someone whose job People keeps gets roles from their posts (approved role changes). Access given to them by
hand in Users is extra access: it needs an end date within the limit. Others are unaffected.
"""
from datetime import datetime, timedelta, timezone

import pytest

from config import settings
from tests.test_internal_employment import declare, role
from tests.test_internal_people import API, make_person
from tests.test_user_access import make_role


def ends_in(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


async def put_access(client, user_id, **body):
    return await client.put(f"{API}/users/{user_id}/permissions", json={"reason": "Audit cover", **body})


async def managed_person(client, db_session, name="Asha"):
    await make_role(client, db_session, "sales_manager", ["identity.user.read"])
    person = await make_person(db_session, name)
    await db_session.commit()
    await declare(client, person.id, managed_roles=[role("sales_manager")])
    return person


@pytest.mark.asyncio
async def test_people_declaring_a_job_marks_the_user(async_client, db_session):
    person = await managed_person(async_client, db_session)
    assert (await async_client.get(f"{API}/users/{person.id}")).json()["managed_by_people"] is True
    other = await make_person(db_session, "Bina")
    await db_session.commit()
    assert (await async_client.get(f"{API}/users/{other.id}")).json()["managed_by_people"] is False


@pytest.mark.asyncio
async def test_extra_access_for_someone_people_manages_must_end_in_time(async_client, db_session):
    person = await managed_person(async_client, db_session)
    report = await make_role(async_client, db_session, "report_viewer", ["identity.org_unit.read"])

    permanent = await put_access(async_client, person.id, permissions=[{"code": "identity.org_unit.read"}])
    assert permanent.status_code == 422 and permanent.json()["code"] == "EXTRA_ACCESS_NEEDS_END_DATE"
    too_long = await put_access(async_client, person.id, permissions=[
        {"code": "identity.org_unit.read", "valid_to": ends_in(settings.extra_access_max_days + 5)}])
    assert too_long.status_code == 422
    preset = await async_client.post(f"{API}/role-assignments", json={
        "user_id": str(person.id), "role_id": str(report.id), "reason": "Audit"})
    assert preset.status_code == 422 and preset.json()["code"] == "EXTRA_ACCESS_NEEDS_END_DATE"

    ok = await put_access(async_client, person.id, permissions=[{"code": "identity.org_unit.read", "valid_to": ends_in(30)}])
    assert ok.status_code == 200, ok.text
    # Taking it away needs no end date
    assert (await put_access(async_client, person.id, permissions=[])).status_code == 200


@pytest.mark.asyncio
async def test_users_people_does_not_manage_are_unaffected(async_client, db_session):
    person = await make_person(db_session, "Chetan")
    await db_session.commit()
    res = await put_access(async_client, person.id, permissions=[{"code": "identity.org_unit.read"}])
    assert res.status_code == 200, res.text
