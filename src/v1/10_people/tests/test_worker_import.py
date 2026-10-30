"""Creating workers from identity's active employee users."""
import uuid
from typing import Optional

import pytest

from dependencies import get_actor, get_identity_client
from main import app
from services.identity_client import Actor, IdentityEmployee, IdentityEmployeePage
from tests.conftest import TEST_ORG_ID


def employee(name: str, *, code: Optional[str] = None, manager: Optional[uuid.UUID] = None) -> IdentityEmployee:
    return IdentityEmployee(
        id=uuid.uuid4(),
        name=name,
        email=f"{name.lower().replace(' ', '.')}@company.com",
        phone="+911234567890",
        employee_code=code,
        manager_user_id=manager,
        home_unit_id=uuid.uuid4(),
    )


class FakeIdentity:
    """Answers like identity's /internal/people/employees: active employees only, paged by offset."""

    def __init__(self, employees: list[IdentityEmployee]) -> None:
        self.employees = sorted(employees, key=lambda e: e.name)

    async def list_employees(self, organization_id, *, search=None, user_ids=None, limit=50, offset=0):
        rows = [e for e in self.employees if (not user_ids or e.id in user_ids)]
        if search:
            rows = [e for e in rows if search.lower() in e.name.lower()]
        page = rows[offset : offset + limit]
        return IdentityEmployeePage(data=page, has_more=len(rows) > offset + limit)


@pytest.fixture
def identity():
    people = [employee("Asha Rao", code="EMP-7"), employee("Bina Shah"), employee("Chetan Iyer")]
    fake = FakeIdentity(people)
    app.dependency_overrides[get_identity_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_identity_client, None)


def item(user: IdentityEmployee, **extra) -> dict:
    return {"user_id": str(user.id), "designation": "Engineer", "date_of_joining": "2024-01-15", **extra}


@pytest.mark.asyncio
async def test_importable_users_are_those_without_a_worker(async_client, identity):
    asha, bina, chetan = identity.employees
    res = await async_client.post("/v1/workers/import-from-users", json={"users": [item(asha)]})
    assert res.status_code == 201, res.text

    listed = await async_client.get("/v1/workers/importable-users")
    assert listed.status_code == 200, listed.text
    assert [u["name"] for u in listed.json()["data"]] == ["Bina Shah", "Chetan Iyer"]
    assert listed.json()["page"]["has_more"] is False


@pytest.mark.asyncio
async def test_importable_users_are_paged_across_linked_users(async_client, identity):
    asha, bina, chetan = identity.employees
    await async_client.post("/v1/workers/import-from-users", json={"users": [item(asha)]})

    first = (await async_client.get("/v1/workers/importable-users", params={"limit": 1})).json()
    assert [u["name"] for u in first["data"]] == ["Bina Shah"]
    assert first["page"]["has_more"] is True

    second = (
        await async_client.get("/v1/workers/importable-users", params={"limit": 1, "cursor": first["page"]["next_cursor"]})
    ).json()
    assert [u["name"] for u in second["data"]] == ["Chetan Iyer"]
    assert second["page"]["has_more"] is False


@pytest.mark.asyncio
async def test_import_copies_identity_details_and_records_the_hire(async_client, identity):
    asha, *_ = identity.employees
    res = await async_client.post("/v1/workers/import-from-users", json={"users": [item(asha)]})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["skipped"] == []
    worker = body["created"][0]
    assert worker["user_id"] == str(asha.id)
    assert (worker["first_name"], worker["last_name"]) == ("Asha", "Rao")
    assert worker["work_email"] == asha.email
    assert worker["unit_id"] == str(asha.home_unit_id)
    assert worker["worker_code"] == "EMP-7"  # identity's employee code
    assert worker["designation"] == "Engineer" and worker["date_of_joining"] == "2024-01-15"

    detail = (await async_client.get(f"/v1/workers/{worker['id']}")).json()
    assert detail["timeline"][0]["event_category"] == "hire"
    assert detail["timeline"][0]["new_state"]["source"] == "identity_import"


@pytest.mark.asyncio
async def test_the_employee_code_is_optional_and_can_be_filled_in_later(async_client, identity):
    _, bina, _ = identity.employees
    created = (await async_client.post("/v1/workers/import-from-users", json={"users": [item(bina)]})).json()["created"][0]
    assert created["worker_code"] is None

    patched = await async_client.patch(f"/v1/workers/{created['id']}", json={"worker_code": " EMP-100 "})
    assert patched.status_code == 200, patched.text
    assert patched.json()["worker_code"] == "EMP-100"

    cleared = await async_client.patch(f"/v1/workers/{created['id']}", json={"worker_code": ""})
    assert cleared.json()["worker_code"] is None


@pytest.mark.asyncio
async def test_a_taken_code_is_rejected_or_dropped(async_client, identity):
    asha, bina, chetan = identity.employees
    await async_client.post("/v1/workers/import-from-users", json={"users": [item(asha)]})  # takes EMP-7
    identity.employees[2] = IdentityEmployee(**{**chetan.__dict__, "employee_code": "EMP-7"})
    chetan = identity.employees[2]

    # An explicit code that is taken skips the user; identity's own colliding code is just left empty.
    explicit = await async_client.post(
        "/v1/workers/import-from-users", json={"users": [item(bina, worker_code="EMP-7")]}
    )
    assert [s["reason"] for s in explicit.json()["skipped"]] == ["worker_code_taken"]
    derived = await async_client.post("/v1/workers/import-from-users", json={"users": [item(chetan)]})
    assert derived.json()["created"][0]["worker_code"] is None

    patched = await async_client.patch(
        f"/v1/workers/{derived.json()['created'][0]['id']}", json={"worker_code": "EMP-7"}
    )
    assert patched.status_code == 409


@pytest.mark.asyncio
async def test_users_that_cannot_be_imported_are_skipped_with_a_reason(async_client, identity):
    asha, bina, _ = identity.employees
    stranger = employee("Not Active")  # identity does not answer for them
    await async_client.post("/v1/workers/import-from-users", json={"users": [item(asha)]})

    res = await async_client.post(
        "/v1/workers/import-from-users",
        json={"users": [item(asha), item(stranger), item(bina), item(bina)]},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert [w["user_id"] for w in body["created"]] == [str(bina.id)]
    assert {(s["user_id"], s["reason"]) for s in body["skipped"]} == {
        (str(asha.id), "already_linked"),
        (str(stranger.id), "not_an_active_employee"),
        (str(bina.id), "duplicate_in_request"),
    }


@pytest.mark.asyncio
async def test_a_worker_with_the_same_work_email_is_not_duplicated(async_client, identity):
    asha, *_ = identity.employees
    await async_client.post(
        "/v1/workers",
        json={
            "first_name": "Asha", "last_name": "Rao", "work_email": asha.email,
            "designation": "Engineer", "date_of_joining": "2023-01-01",
        },
    )
    res = await async_client.post("/v1/workers/import-from-users", json={"users": [item(asha)]})
    assert [s["reason"] for s in res.json()["skipped"]] == ["work_email_taken"]


@pytest.mark.asyncio
async def test_managers_are_linked_when_the_manager_is_a_worker_too(async_client):
    boss = employee("Boss Person")
    report = employee("Report Person", manager=boss.id)
    fake = FakeIdentity([boss, report])
    app.dependency_overrides[get_identity_client] = lambda: fake
    try:
        res = await async_client.post("/v1/workers/import-from-users", json={"users": [item(report), item(boss)]})
    finally:
        app.dependency_overrides.pop(get_identity_client, None)
    created = {w["first_name"]: w for w in res.json()["created"]}
    assert created["Report"]["manager_id"] == created["Boss"]["id"]
    assert created["Boss"]["manager_id"] is None


@pytest.mark.asyncio
async def test_one_worker_per_user_is_enforced_by_the_database(async_client, identity):
    asha, *_ = identity.employees
    body = {
        "first_name": "A", "last_name": "B", "designation": "Engineer", "date_of_joining": "2023-01-01",
        "user_id": str(asha.id),
    }
    first = await async_client.post("/v1/workers", json={**body, "work_email": "a1@company.com"})
    assert first.status_code == 201, first.text
    with pytest.raises(Exception) as raised:
        await async_client.post("/v1/workers", json={**body, "work_email": "a2@company.com"})
    assert "uq_workers_org_user" in str(raised.value) or "UNIQUE" in str(raised.value).upper()


@pytest.mark.asyncio
async def test_importing_needs_the_employee_manage_permission(async_client, identity):
    app.dependency_overrides[get_actor] = lambda: Actor(
        user_id=uuid.uuid4(), organization_id=TEST_ORG_ID, user_type="employee", name="Reader",
        permissions=frozenset(["people.employee.read"]),
    )
    assert (await async_client.get("/v1/workers/importable-users")).status_code == 403
    assert (await async_client.post("/v1/workers/import-from-users", json={"users": []})).status_code in (403, 422)
    asha, *_ = identity.employees
    assert (await async_client.post("/v1/workers/import-from-users", json={"users": [item(asha)]})).status_code == 403
