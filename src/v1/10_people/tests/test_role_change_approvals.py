"""Approval routes for role changes: steps, standing approvers, delegation, escalation."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from models.role_change import RoleChangeStep
from services import role_changes
from tests.test_role_changes import APPROVER_ID, PAST, act_as, as_approver, as_requester, make_worker, request, set_salary
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

UNIT_A, UNIT_B = uuid.uuid4(), uuid.uuid4()
HEAD_A, HEAD_B = uuid.uuid4(), uuid.uuid4()
HR_HEAD, FINANCE = uuid.uuid4(), uuid.uuid4()
DELEGATE = uuid.uuid4()
TODAY = date.today().isoformat()


async def decide(client, change_id, user_id, action="approve", **body):
    act_as(user_id)
    body = body or ({"note": "ok"} if action == "reject" else {})
    return await client.post(f"/v1/role-changes/{change_id}/{action}", json=body)


async def new_post(client, worker_id, **fields):
    body = {"change_type": "add_post", "post_type": "concurrent", "new_designation": "Trainer",
            "new_unit_id": str(UNIT_B), "new_time_share": 40, **fields}
    res = await request(client, worker_id, **body)
    assert res.status_code == 201, res.text
    return res.json()


def names(change) -> list[str]:
    return [s["name"] for s in change["steps"]]


@pytest.mark.asyncio
async def test_an_ordinary_change_has_one_open_approval(async_client):
    worker_id = await make_worker(async_client)
    change = (await request(async_client, worker_id, new_designation="Senior Engineer")).json()
    assert names(change) == ["Approval"] and change["steps"][0]["open_to_pool"] is True
    assert change["awaiting_step"] == "Approval"
    done = (await decide(async_client, change["id"], APPROVER_ID)).json()
    assert done["status"] == "applied" and done["awaiting_step"] is None and done["steps"][0]["status"] == "approved"


@pytest.mark.asyncio
async def test_a_new_post_needs_both_department_heads_in_order(async_client, identity):
    identity.heads = {UNIT_A: HEAD_A, UNIT_B: HEAD_B}
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    change = await new_post(async_client, worker_id)
    assert names(change) == ["Approval", "Department head approval", "Department head approval"]
    assert [s["unit_id"] for s in change["steps"][1:]] == [str(UNIT_A), str(UNIT_B)]

    first = (await decide(async_client, change["id"], APPROVER_ID)).json()
    assert first["status"] == "pending" and first["steps"][1]["status"] == "active"

    # The wrong department head, and someone with no named role, cannot decide the current step
    wrong = await decide(async_client, change["id"], HEAD_B)
    assert wrong.status_code == 403 and wrong.json()["code"] == "NOT_AN_APPROVER"
    assert (await decide(async_client, change["id"], APPROVER_ID)).status_code == 403

    second = (await decide(async_client, change["id"], HEAD_A)).json()
    assert second["status"] == "pending" and second["awaiting_step"] == "Department head approval"
    assert (await async_client.get(f"/v1/workers/{worker_id}/posts")).json()["data"][0]["post_type"] == "primary"
    assert len((await async_client.get(f"/v1/workers/{worker_id}/posts")).json()["data"]) == 1  # not started yet

    final = (await decide(async_client, change["id"], HEAD_B)).json()
    assert final["status"] == "applied" and [s["status"] for s in final["steps"]] == ["approved"] * 3
    assert len((await async_client.get(f"/v1/workers/{worker_id}/posts")).json()["data"]) == 2


@pytest.mark.asyncio
async def test_one_person_heading_both_departments_approves_once(async_client, identity):
    identity.heads = {UNIT_A: HEAD_A, UNIT_B: HEAD_A}
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    change = await new_post(async_client, worker_id)
    assert names(change) == ["Approval", "Department head approval"]


@pytest.mark.asyncio
async def test_a_department_without_a_head_adds_no_step(async_client, identity):
    identity.heads = {UNIT_B: HEAD_B}
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    change = await new_post(async_client, worker_id)
    assert [s["unit_id"] for s in change["steps"][1:]] == [str(UNIT_B)]


@pytest.mark.asyncio
async def test_a_demotion_adds_the_hr_head_and_a_pay_change_adds_finance(async_client):
    # Not set up yet: no extra steps
    worker_id = await make_worker(async_client)
    await set_salary(async_client, worker_id, 1_200_000)
    plain = await request(async_client, worker_id, change_type="demotion", new_designation="Junior", new_annual_ctc=1_000_000)
    assert names(plain.json()) == ["Approval"]
    await async_client.post(f"/v1/role-changes/{plain.json()['id']}/cancel")

    for key, user in (("hr_head", HR_HEAD), ("finance", FINANCE)):
        assert (await async_client.put(f"/v1/role-change-approvers/{key}", json={"user_ids": [str(user)]})).status_code == 200

    demotion = (await request(async_client, worker_id, change_type="demotion", new_designation="Junior", new_annual_ctc=1_000_000)).json()
    assert names(demotion) == ["Approval", "HR head approval", "Finance approval"]
    await async_client.post(f"/v1/role-changes/{demotion['id']}/cancel")

    promotion = (await request(async_client, worker_id, new_designation="Lead")).json()
    assert names(promotion) == ["Approval"]  # no pay change, not a demotion
    await async_client.post(f"/v1/role-changes/{promotion['id']}/cancel")

    raise_ = (await request(async_client, worker_id, new_annual_ctc=1_500_000)).json()
    assert names(raise_) == ["Approval", "Finance approval"]
    await decide(async_client, raise_["id"], APPROVER_ID)
    assert (await decide(async_client, raise_["id"], HR_HEAD)).status_code == 403
    assert (await decide(async_client, raise_["id"], FINANCE)).json()["status"] == "applied"


@pytest.mark.asyncio
async def test_the_requester_or_the_employee_cannot_decide_a_step_meant_for_them(async_client):
    await async_client.put("/v1/role-change-approvers/finance", json={"user_ids": [str(TEST_USER_ID)]})
    worker_id = await make_worker(async_client)
    await set_salary(async_client, worker_id)
    change = (await request(async_client, worker_id, new_annual_ctc=1_500_000)).json()
    finance = change["steps"][1]
    # The requester is the only finance approver: the step opens to anyone who may approve
    assert finance["open_to_pool"] is True and finance["approver_user_ids"] == []

    employee_user = uuid.uuid4()
    other = await make_worker(async_client, "self@company.com", user_id=str(employee_user))
    mine = (await request(async_client, other, new_designation="Lead")).json()
    own = await decide(async_client, mine["id"], employee_user)
    assert own.status_code == 403 and own.json()["code"] == "SELF_APPROVAL_FORBIDDEN"


@pytest.mark.asyncio
async def test_a_delegate_decides_for_an_approver_while_the_delegation_lasts(async_client, identity):
    identity.heads = {UNIT_A: HEAD_A, UNIT_B: HEAD_B}
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    change = await new_post(async_client, worker_id, new_unit_id=str(UNIT_A))  # one department: one head step
    await decide(async_client, change["id"], APPROVER_ID)

    assert (await decide(async_client, change["id"], DELEGATE)).status_code == 403

    act_as(HEAD_A)
    week = {"to_user_id": str(DELEGATE), "valid_from": TODAY, "valid_to": (date.today() + timedelta(days=7)).isoformat(), "reason": "Away"}
    created = await async_client.post("/v1/role-change-delegations", json=week)
    assert created.status_code == 201, created.text
    overlap = await async_client.post("/v1/role-change-delegations", json=week)
    assert overlap.status_code == 409 and overlap.json()["code"] == "DELEGATION_OVERLAP"
    assert (await async_client.post("/v1/role-change-delegations", json={**week, "to_user_id": str(HEAD_A)})).status_code == 422
    assert len((await async_client.get("/v1/role-change-delegations")).json()["data"]) == 1

    done = (await decide(async_client, change["id"], DELEGATE)).json()
    head_step = done["steps"][1]
    assert done["status"] == "applied" and head_step["decided_by"] == str(DELEGATE) and head_step["acted_for"] == str(HEAD_A)


@pytest.mark.asyncio
async def test_an_ended_or_expired_delegation_gives_no_power(async_client, identity):
    identity.heads = {UNIT_A: HEAD_A}
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    change = await new_post(async_client, worker_id, new_unit_id=str(UNIT_A))
    await decide(async_client, change["id"], APPROVER_ID)

    act_as(HEAD_A)
    past = {"to_user_id": str(DELEGATE), "valid_from": "2020-01-01", "valid_to": "2020-01-31"}
    assert (await async_client.post("/v1/role-change-delegations", json=past)).status_code == 201
    assert (await decide(async_client, change["id"], DELEGATE)).status_code == 403

    act_as(HEAD_A)
    current = (await async_client.post("/v1/role-change-delegations", json={**past, "valid_from": TODAY, "valid_to": TODAY})).json()
    assert (await async_client.delete(f"/v1/role-change-delegations/{current['id']}")).status_code == 204
    assert (await async_client.delete(f"/v1/role-change-delegations/{current['id']}")).status_code == 404
    assert (await decide(async_client, change["id"], DELEGATE)).status_code == 403


@pytest.mark.asyncio
async def test_a_stalled_step_escalates_to_anyone_who_may_approve(async_client, db_session, identity):
    identity.heads = {UNIT_A: HEAD_A}
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    change = await new_post(async_client, worker_id, new_unit_id=str(UNIT_A))
    await decide(async_client, change["id"], APPROVER_ID)

    now = datetime.now(timezone.utc)
    assert await role_changes.escalate_stalled_steps(db_session, now) == []  # only just activated

    step = (await db_session.execute(select(RoleChangeStep).where(RoleChangeStep.status == "active"))).scalar_one()
    step.activated_at = now - timedelta(days=4)
    await db_session.flush()
    escalated = await role_changes.escalate_stalled_steps(db_session, now)
    assert [s.id for _, s in escalated] == [step.id]
    assert await role_changes.escalate_stalled_steps(db_session, now) == []  # once only

    shown = (await async_client.get("/v1/role-changes", params={"status": "pending"})).json()["data"][0]["steps"][1]
    assert shown["escalated_at"] is not None and shown["open_to_pool"] is True
    done = await decide(async_client, change["id"], DELEGATE)  # not the head, but may approve role changes
    assert done.json()["status"] == "applied"


@pytest.mark.asyncio
async def test_a_rejection_at_any_step_ends_the_request(async_client, identity):
    identity.heads = {UNIT_A: HEAD_A, UNIT_B: HEAD_B}
    worker_id = await make_worker(async_client, unit_id=str(UNIT_A))
    change = await new_post(async_client, worker_id)
    await decide(async_client, change["id"], APPROVER_ID)

    assert (await decide(async_client, change["id"], HEAD_B, "reject")).status_code == 403  # not their step yet
    rejected = (await decide(async_client, change["id"], HEAD_A, "reject", note="Not now")).json()
    assert rejected["status"] == "rejected" and rejected["decision_note"] == "Not now"
    assert [s["status"] for s in rejected["steps"]] == ["approved", "rejected", "skipped"]
    assert (await decide(async_client, change["id"], HEAD_B)).status_code == 409


@pytest.mark.asyncio
async def test_only_those_who_set_up_approvals_can_choose_the_standing_approvers(async_client):
    assert (await async_client.put("/v1/role-change-approvers/cfo", json={"user_ids": []})).status_code == 422
    await async_client.put("/v1/role-change-approvers/finance", json={"user_ids": [str(FINANCE), str(FINANCE)]})
    listed = (await async_client.get("/v1/role-change-approvers")).json()["data"]
    assert {row["role_key"]: row["user_ids"] for row in listed} == {"hr_head": [], "finance": [str(FINANCE)]}
    await async_client.put("/v1/role-change-approvers/finance", json={"user_ids": []})
    assert (await async_client.get("/v1/role-change-approvers")).json()["data"][1]["user_ids"] == []

    act_as(APPROVER_ID, "people.role_change.approve")
    assert (await async_client.put("/v1/role-change-approvers/finance", json={"user_ids": []})).status_code == 403
    assert (await async_client.get("/v1/role-change-approvers")).status_code == 403
