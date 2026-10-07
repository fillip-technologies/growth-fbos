import json
from datetime import datetime, timezone
from typing import AsyncGenerator, Any
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from models.lead import Lead
from services.website_lead_import import import_new_enquiries, is_sales_enquiry
from services.website_leads_client import (
    FBOS_STATUS_BY_WEBSITE_STATUS,
    WEBSITE_STATUS_BY_FBOS_STATUS,
    WebsiteLeadsClient,
    parse_website_lead,
    website_leads_client,
)
from tests.conftest import TEST_ORG_ID, TEST_USER_ID

BASE = "/api/revenue/v1"
LEADS_URL = "https://website.test/api/integrations/leads"
CONSENT = {"given": True, "text": "I agree to be contacted about my enquiry.", "channel": "web"}


def website_record(website_id: str, **overrides: Any) -> dict[str, Any]:
    record = {
        "id": website_id,
        "name": "Riya Verma",
        "email": "riya@example.com",
        "phone": "+91 98765 43210",
        "company": "Verma Exports",
        "budget": "50000",
        "message": "We need a new website.",
        "source": "Contact Page",
        "location": {"source": "ip", "label": "Patna, Bihar, India"},
        "packageCategory": "Website",
        "resume": None,
        "status": "new",
        "created_at": "2026-10-05T09:42:32.363Z",
        "deletedAt": None,
    }
    return {**record, **overrides}


# ---------------------------------------------------------------- decisions and mapping


def test_status_maps_are_exact_inverses():
    assert set(FBOS_STATUS_BY_WEBSITE_STATUS.values()) == {"new", "contacted", "qualified", "converted", "disqualified"}
    for website_status, fbos_status in FBOS_STATUS_BY_WEBSITE_STATUS.items():
        assert WEBSITE_STATUS_BY_FBOS_STATUS[fbos_status] == website_status


def test_a_website_record_maps_to_a_website_lead():
    website_lead = parse_website_lead(website_record("w1", status="in-progress"))

    assert website_lead.website_id == "w1"
    assert website_lead.form == "Contact Page"
    assert website_lead.location == "Patna, Bihar, India"
    assert website_lead.fbos_status == "qualified"
    assert website_lead.created_at == datetime(2026, 10, 5, 9, 42, 32, 363000, tzinfo=timezone.utc)
    assert website_lead.deleted is False


def test_an_unknown_website_status_imports_as_new():
    assert parse_website_lead(website_record("w1", status="archived")).fbos_status == "new"


def test_job_applications_and_binned_leads_are_not_sales_enquiries():
    assert is_sales_enquiry(parse_website_lead(website_record("w1")))
    assert not is_sales_enquiry(parse_website_lead(website_record("w2", source="Careers Application")))
    assert not is_sales_enquiry(parse_website_lead(website_record("w3", packageCategory="Careers")))
    assert not is_sales_enquiry(parse_website_lead(website_record("w4", deletedAt="2026-10-06T10:00:00Z")))


# ---------------------------------------------------------------- fetching


@pytest.mark.asyncio
async def test_fetch_all_reads_every_page_with_the_key():
    pages = {
        "1": {"leads": [website_record("w1"), {"name": "no id or date"}], "has_more": True},
        "2": {"leads": [website_record("w2")], "has_more": False},
    }
    seen: list[httpx.Request] = []

    def website(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params["page"]])

    client = WebsiteLeadsClient()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(website), headers={"Authorization": "Bearer test-key"}
    ) as http:
        client.start(http, LEADS_URL, TEST_ORG_ID)
        website_leads = await client.fetch_all()

    assert [lead.website_id for lead in website_leads] == ["w1", "w2"]  # the broken record is skipped
    assert [request.url.params["limit"] for request in seen] == ["500", "500"]
    assert all(request.headers["authorization"] == "Bearer test-key" for request in seen)
    assert seen[0].url.path == "/api/integrations/leads"


@pytest.mark.asyncio
async def test_a_website_error_raises_for_the_import_run_to_handle():
    client = WebsiteLeadsClient()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as http:
        client.start(http, LEADS_URL, TEST_ORG_ID)
        with pytest.raises(httpx.HTTPStatusError):
            await client.fetch_all()


# ---------------------------------------------------------------- importing


@pytest.mark.asyncio
async def test_only_new_sales_enquiries_are_imported_oldest_first(db_session):
    website_leads = [
        parse_website_lead(website_record("w-late", created_at="2026-10-06T08:00:00Z", status="in-progress")),
        parse_website_lead(website_record("w-early", created_at="2026-10-01T08:00:00Z")),
        parse_website_lead(website_record("w-job", source="Careers Application", packageCategory="Careers")),
    ]

    imported = await import_new_enquiries(db_session, website_leads, TEST_ORG_ID, TEST_USER_ID)
    await db_session.commit()

    assert [lead.attributes["website_lead_id"] for lead in imported] == ["w-early", "w-late"]
    year = datetime.now(timezone.utc).year
    assert [lead.name for lead in imported] == [f"LD-{year}-0001", f"LD-{year}-0002"]
    early, late = imported
    assert early.source == "website"
    assert early.owner_user_id == TEST_USER_ID
    assert early.contact_email == "riya@example.com"
    assert early.attributes["message"] == "We need a new website."
    assert early.attributes["location"] == "Patna, Bihar, India"
    assert late.status == "qualified"

    again = await import_new_enquiries(db_session, website_leads, TEST_ORG_ID, TEST_USER_ID)
    assert again == []
    rows = await db_session.execute(select(Lead).where(Lead.organization_id == TEST_ORG_ID))
    assert len(rows.scalars().all()) == 2


@pytest.mark.asyncio
async def test_a_hand_made_website_lead_does_not_hide_an_enquiry(async_client, db_session):
    res = await async_client.post(
        f"{BASE}/leads",
        json={"vertical_id": str(uuid.uuid4()), "contact_name": "Walk-in", "source": "website", "consent": CONSENT},
    )
    assert res.status_code == 201, res.text

    imported = await import_new_enquiries(
        db_session, [parse_website_lead(website_record("w1"))], TEST_ORG_ID, TEST_USER_ID
    )

    assert len(imported) == 1
    year = datetime.now(timezone.utc).year
    assert imported[0].name == f"LD-{year}-0002"


# ---------------------------------------------------------------- sending status back


@pytest_asyncio.fixture
async def website_patches() -> AsyncGenerator[list[tuple[str, dict]], None]:
    """Status changes revenue sends back, captured by a stand-in website."""
    captured: list[tuple[str, dict]] = []

    def website(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        captured.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(website)) as http:
        website_leads_client.start(http, LEADS_URL, TEST_ORG_ID)
        yield captured
        await website_leads_client.drain()
        website_leads_client.stop()


async def _import_one(db_session, website_id: str) -> Lead:
    [lead] = await import_new_enquiries(
        db_session, [parse_website_lead(website_record(website_id))], TEST_ORG_ID, TEST_USER_ID
    )
    await db_session.commit()
    return lead


@pytest.mark.asyncio
async def test_a_status_change_goes_back_to_the_website(async_client, db_session, website_patches):
    lead = await _import_one(db_session, "w1")

    res = await async_client.patch(
        f"{BASE}/leads/{lead.id}", json={"status": "qualified"}, headers={"If-Match": f'"{lead.version}"'}
    )
    assert res.status_code == 200, res.text
    res = await async_client.post(
        f"{BASE}/leads/{lead.id}/disqualify",
        json={"reason": "no_budget"},
        headers={"If-Match": f'"{res.json()["version"]}"'},
    )
    assert res.status_code == 200, res.text
    await website_leads_client.drain()

    assert website_patches == [
        ("/api/integrations/leads/w1", {"status": "in-progress"}),
        ("/api/integrations/leads/w1", {"status": "disqualified"}),
    ]


@pytest.mark.asyncio
async def test_changes_that_leave_the_status_alone_are_not_sent(async_client, db_session, website_patches):
    lead = await _import_one(db_session, "w1")

    res = await async_client.patch(
        f"{BASE}/leads/{lead.id}", json={"score": 70}, headers={"If-Match": f'"{lead.version}"'}
    )
    assert res.status_code == 200, res.text
    await website_leads_client.drain()

    assert website_patches == []


@pytest.mark.asyncio
async def test_leads_not_from_the_website_are_not_sent(async_client, website_patches):
    res = await async_client.post(
        f"{BASE}/leads",
        json={"vertical_id": str(uuid.uuid4()), "contact_name": "Walk-in", "source": "website", "consent": CONSENT},
    )
    lead = res.json()
    res = await async_client.patch(
        f"{BASE}/leads/{lead['id']}", json={"status": "contacted"}, headers={"If-Match": f'"{lead["version"]}"'}
    )
    assert res.status_code == 200, res.text
    await website_leads_client.drain()

    assert website_patches == []


@pytest.mark.asyncio
async def test_leads_of_another_organization_are_not_sent(async_client, db_session, website_patches):
    other_org = uuid.uuid4()
    [lead] = await import_new_enquiries(
        db_session, [parse_website_lead(website_record("w1"))], other_org, TEST_USER_ID
    )
    await db_session.commit()

    res = await async_client.patch(
        f"{BASE}/leads/{lead.id}",
        json={"status": "contacted"},
        headers={"If-Match": f'"{lead.version}"', "X-Organization-Id": str(other_org)},
    )
    assert res.status_code == 200, res.text
    await website_leads_client.drain()

    assert website_patches == []


@pytest.mark.asyncio
async def test_the_website_being_down_does_not_fail_the_request(async_client, db_session):
    def website(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    lead = await _import_one(db_session, "w1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(website)) as http:
        website_leads_client.start(http, LEADS_URL, TEST_ORG_ID)
        try:
            res = await async_client.patch(
                f"{BASE}/leads/{lead.id}", json={"status": "contacted"}, headers={"If-Match": f'"{lead.version}"'}
            )
            await website_leads_client.drain()
        finally:
            website_leads_client.stop()

    assert res.status_code == 200, res.text
