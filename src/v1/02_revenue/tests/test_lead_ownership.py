"""
Who handles a lead and what happened to it: claiming, passing it on, calls, qualifying,
disqualifying and reopening, each written to the lead's history.
"""

import uuid
from datetime import date, timedelta

import httpx
import pytest

from dependencies import get_actor
from main import app
from services.identity_client import Actor
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_sales_flow import ADDRESS, BASE, CONSENT

pytestmark = pytest.mark.asyncio

ASHA = uuid.UUID("0191f3a2-0000-7000-8000-00000000a5a1")
VIK = uuid.UUID("0191f3a2-0000-7000-8000-00000000b1c2")
SALES_REP = frozenset({"revenue.lead.read", "revenue.lead.write", "revenue.activity.read"})
SALES_MANAGER = SALES_REP | {"revenue.lead.assign"}


def act_as(user_id: uuid.UUID, permissions: frozenset[str] = SALES_REP) -> None:
    """The next requests come from this person (until the test client's fixture clears it)."""

    async def actor() -> Actor:
        return Actor(user_id=user_id, organization_id=TEST_ORG_ID, user_type="employee", name=str(user_id), permissions=permissions)

    app.dependency_overrides[get_actor] = actor


async def _lead(client: httpx.AsyncClient, **fields) -> dict:
    res = await client.post(f"{BASE}/leads", json={"vertical_id": str(uuid.uuid4()), "contact_name": "Ravi", "consent": CONSENT} | fields)
    assert res.status_code == 201, res.text
    return res.json()


def _if_match(lead: dict) -> dict:
    return {"If-Match": f'"{lead["version"]}"'}


async def _events(client: httpx.AsyncClient, lead_id: str) -> list[dict]:
    res = await client.get(f"{BASE}/leads/{lead_id}/events")
    assert res.status_code == 200, res.text
    return res.json()


async def _call(client: httpx.AsyncClient, lead_id: str, **fields) -> httpx.Response:
    return await client.post(f"{BASE}/leads/{lead_id}/calls", json={"summary": "Talked about a new website"} | fields)


def _qualify_body(**opportunity) -> dict:
    return {
        "new_client": {"name": "Ravi Traders", "legal_name": "Ravi Traders", "billing_address": ADDRESS, "owner_user_id": str(TEST_USER_ID)},
        "opportunity": {"name": "Website", "expected_close_date": "2026-12-31"} | opportunity,
    }


# ---------------------------------------------------------------- claiming


async def test_a_new_lead_waits_unclaimed(async_client):
    lead = await _lead(async_client)

    assert lead["owner"] is None
    unclaimed = (await async_client.get(f"{BASE}/leads", params={"unclaimed": True})).json()["data"]
    assert [row["id"] for row in unclaimed] == [lead["id"]]
    [created] = await _events(async_client, lead["id"])
    assert (created["event"], created["actor_user_id"], created["to_user_id"]) == ("created", str(TEST_USER_ID), None)


async def test_the_first_to_claim_wins(async_client):
    lead = await _lead(async_client)

    act_as(ASHA)
    first = await async_client.post(f"{BASE}/leads/{lead['id']}/claim")
    assert first.status_code == 200, first.text
    assert first.json()["owner"]["id"] == str(ASHA)
    again = await async_client.post(f"{BASE}/leads/{lead['id']}/claim")
    assert again.status_code == 200  # already hers: nothing changes

    act_as(VIK)
    late = await async_client.post(f"{BASE}/leads/{lead['id']}/claim")
    assert late.status_code == 409
    assert late.json()["detail"]["code"] == "LEAD_ALREADY_CLAIMED"

    events = await _events(async_client, lead["id"])
    assert [(e["event"], e["actor_user_id"], e["to_user_id"]) for e in events] == [
        ("created", str(TEST_USER_ID), None),
        ("claimed", str(ASHA), str(ASHA)),
    ]
    assert (await async_client.get(f"{BASE}/leads", params={"unclaimed": True})).json()["data"] == []


async def test_claiming_needs_lead_write(async_client):
    lead = await _lead(async_client)
    act_as(ASHA, frozenset({"revenue.lead.read"}))
    res = await async_client.post(f"{BASE}/leads/{lead['id']}/claim")
    assert res.status_code == 403
    assert res.json()["detail"]["meta"] == {"required_permission": "revenue.lead.write"}


async def test_adding_a_lead_for_someone_else_needs_assign(async_client):
    act_as(ASHA)
    res = await async_client.post(
        f"{BASE}/leads", json={"vertical_id": str(uuid.uuid4()), "contact_name": "Ravi", "consent": CONSENT, "owner_user_id": str(VIK)}
    )
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "NOT_LEAD_OWNER"

    mine = await async_client.post(
        f"{BASE}/leads", json={"vertical_id": str(uuid.uuid4()), "contact_name": "Ravi", "consent": CONSENT, "owner_user_id": str(ASHA)}
    )
    assert mine.status_code == 201
    assert mine.json()["owner"]["id"] == str(ASHA)


async def test_only_who_handles_it_edits_its_details(async_client):
    lead = await _lead(async_client, owner_user_id=str(ASHA))
    act_as(VIK)
    res = await async_client.patch(f"{BASE}/leads/{lead['id']}", json={"score": 10}, headers=_if_match(lead))
    assert res.status_code == 403
    act_as(ASHA)
    res = await async_client.patch(f"{BASE}/leads/{lead['id']}", json={"score": 10}, headers=_if_match(lead))
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------- passing it on


async def test_passing_a_lead_on_is_recorded_with_who_when_and_why(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))

    res = await async_client.post(
        f"{BASE}/leads/{lead['id']}/transfer", json={"to_user_id": str(ASHA), "reason": "She covers Bihar"}, headers=_if_match(lead)
    )
    assert res.status_code == 200, res.text
    assert res.json()["owner"]["id"] == str(ASHA)

    transferred = (await _events(async_client, lead["id"]))[-1]
    assert transferred["event"] == "transferred"
    assert (transferred["actor_user_id"], transferred["from_user_id"], transferred["to_user_id"]) == (
        str(TEST_USER_ID), str(TEST_USER_ID), str(ASHA)
    )
    assert transferred["note"] == "She covers Bihar"
    assert transferred["occurred_at"]


async def test_a_reason_is_required(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    res = await async_client.post(f"{BASE}/leads/{lead['id']}/transfer", json={"to_user_id": str(ASHA), "reason": ""}, headers=_if_match(lead))
    assert res.status_code == 422


async def test_only_who_handles_it_or_a_manager_passes_it_on(async_client, fake_identity):
    lead = await _lead(async_client, owner_user_id=str(ASHA))

    act_as(VIK)
    res = await async_client.post(f"{BASE}/leads/{lead['id']}/transfer", json={"to_user_id": str(VIK), "reason": "Mine now"}, headers=_if_match(lead))
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "NOT_LEAD_OWNER"

    act_as(TEST_USER_ID, SALES_MANAGER)
    res = await async_client.post(f"{BASE}/leads/{lead['id']}/transfer", json={"to_user_id": str(VIK), "reason": "Balancing load"}, headers=_if_match(lead))
    assert res.status_code == 200, res.text
    assert res.json()["owner"]["id"] == str(VIK)


async def test_leads_go_only_to_people_who_may_take_them(async_client, fake_identity):
    fake_identity.allowed = {ASHA: "Asha"}
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))

    res = await async_client.post(f"{BASE}/leads/{lead['id']}/transfer", json={"to_user_id": str(VIK), "reason": "x"}, headers=_if_match(lead))
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "LEAD_ASSIGNEE_NOT_ALLOWED"
    assert fake_identity.asked[-1] == ("revenue.lead.write", VIK)

    people = await async_client.get(f"{BASE}/leads/assignable-people")
    assert people.json() == [{"id": str(ASHA), "name": "Asha"}]


async def test_releasing_puts_it_back_with_the_unclaimed(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))

    res = await async_client.post(f"{BASE}/leads/{lead['id']}/transfer", json={"reason": "Too busy"}, headers=_if_match(lead))

    assert res.status_code == 200, res.text
    assert res.json()["owner"] is None
    released = (await _events(async_client, lead["id"]))[-1]
    assert (released["event"], released["from_user_id"], released["to_user_id"]) == ("released", str(TEST_USER_ID), None)


# ---------------------------------------------------------------- calls


async def test_a_call_needs_someone_handling_the_lead_and_a_summary(async_client):
    lead = await _lead(async_client)
    res = await _call(async_client, lead["id"])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "LEAD_NOT_CLAIMED"

    await async_client.post(f"{BASE}/leads/{lead['id']}/claim")
    res = await _call(async_client, lead["id"], summary="")
    assert res.status_code == 422


async def test_the_first_call_makes_the_lead_contacted_and_every_call_is_kept(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    soon = date.today() + timedelta(days=3)

    first = await _call(
        async_client, lead["id"], requirements="Five-page site", expectations="Live by March",
        next_action="Send examples", follow_up_on=soon.isoformat(),
    )
    assert first.status_code == 201, first.text
    assert first.json()["lead"]["status"] == "contacted"
    assert first.json()["lead"]["next_follow_up_on"] == soon.isoformat()
    assert first.json()["activity"]["requirements"] == "Five-page site"

    second = await _call(async_client, lead["id"], summary="Sent examples; they liked the second")
    assert second.status_code == 201
    assert second.json()["lead"]["next_follow_up_on"] is None  # the latest call set none

    calls = (await async_client.get(f"{BASE}/activities", params={"subject_id": lead["id"]})).json()["data"]
    assert sorted(c["summary"] for c in calls) == ["Sent examples; they liked the second", "Talked about a new website"]
    assert [e["event"] for e in await _events(async_client, lead["id"])] == ["created", "contacted"]


async def test_follow_ups_due_are_listed(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    await _call(async_client, lead["id"], follow_up_on=date.today().isoformat())
    later = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    await _call(async_client, later["id"], follow_up_on=(date.today() + timedelta(days=9)).isoformat())

    due = (await async_client.get(f"{BASE}/leads", params={"follow_up_due": date.today().isoformat()})).json()["data"]
    assert [row["id"] for row in due] == [lead["id"]]


async def test_an_activity_keeps_its_follow_up(async_client):
    """POST /activities used to accept a follow-up and drop it."""
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    res = await async_client.post(
        f"{BASE}/activities",
        json={
            "subject": {"type": "commercial.lead", "id": lead["id"]},
            "activity_type": "meeting",
            "occurred_at": "2026-11-12T10:00:00Z",
            "summary": "Met at the expo",
            "follow_up": {"title": "Send the brochure", "due_at": "2026-11-15T09:00:00Z"},
        },
    )
    assert res.status_code == 201, res.text
    assert (res.json()["next_action"], res.json()["follow_up_on"]) == ("Send the brochure", "2026-11-15")


# ---------------------------------------------------------------- qualify, disqualify, reopen


async def test_a_lead_is_called_before_it_is_qualified(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    res = await async_client.post(f"{BASE}/leads/{lead['id']}/qualify", json=_qualify_body(), headers=_if_match(lead))
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "LEAD_CALL_REQUIRED"


async def test_qualifying_makes_the_customer_and_opportunity_without_a_value(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    called = await _call(async_client, lead["id"])

    res = await async_client.post(f"{BASE}/leads/{lead['id']}/qualify", json=_qualify_body(), headers={"If-Match": called.headers["ETag"]})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["lead"]["status"] == "qualified"
    assert (body["client"]["status"], body["opportunity"]["stage"]) == ("prospect", "qualification")
    assert body["opportunity"]["owner"]["id"] == str(TEST_USER_ID)
    assert [e["event"] for e in await _events(async_client, lead["id"])] == ["created", "contacted", "qualified"]


async def test_someone_elses_lead_is_not_qualified_by_a_colleague(async_client):
    lead = await _lead(async_client, owner_user_id=str(ASHA))
    act_as(ASHA)
    called = await _call(async_client, lead["id"])
    act_as(VIK, SALES_REP | {"revenue.client.write"})
    res = await async_client.post(f"{BASE}/leads/{lead['id']}/qualify", json=_qualify_body(), headers={"If-Match": called.headers["ETag"]})
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "NOT_LEAD_OWNER"


async def test_disqualifying_a_qualified_lead_loses_its_opportunity_and_it_stays_closed(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    called = await _call(async_client, lead["id"])
    qualified = (
        await async_client.post(f"{BASE}/leads/{lead['id']}/qualify", json=_qualify_body(), headers={"If-Match": called.headers["ETag"]})
    ).json()

    res = await async_client.post(
        f"{BASE}/leads/{lead['id']}/disqualify", json={"reason": "no_budget"}, headers=_if_match(qualified["lead"])
    )
    assert res.status_code == 200, res.text
    opportunity = (await async_client.get(f"{BASE}/opportunities/{qualified['opportunity']['id']}")).json()
    assert opportunity["stage"] == "lost"

    reopened = await async_client.post(f"{BASE}/leads/{lead['id']}/reopen", headers=_if_match(res.json()))
    assert reopened.status_code == 409
    assert reopened.json()["detail"]["code"] == "LEAD_REOPEN_NOT_ALLOWED"


async def test_a_reopened_lead_that_was_called_is_contacted_again(async_client):
    lead = await _lead(async_client, owner_user_id=str(TEST_USER_ID))
    called = await _call(async_client, lead["id"])
    disqualified = await async_client.post(
        f"{BASE}/leads/{lead['id']}/disqualify", json={"reason": "unreachable"}, headers={"If-Match": called.headers["ETag"]}
    )

    res = await async_client.post(f"{BASE}/leads/{lead['id']}/reopen", headers=_if_match(disqualified.json()))

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "contacted"
    assert [e["event"] for e in await _events(async_client, lead["id"])][-2:] == ["disqualified", "reopened"]


async def test_an_unclaimed_lead_can_be_disqualified_by_anyone_who_works_leads(async_client):
    lead = await _lead(async_client)
    act_as(VIK)
    res = await async_client.post(f"{BASE}/leads/{lead['id']}/disqualify", json={"reason": "duplicate"}, headers=_if_match(lead))
    assert res.status_code == 200, res.text


async def test_history_of_another_organizations_lead_is_not_found(async_client):
    lead = await _lead(async_client)
    res = await async_client.get(f"{BASE}/leads/{lead['id']}/events", headers={"X-Organization-Id": str(uuid.uuid4())})
    assert res.status_code == 404
