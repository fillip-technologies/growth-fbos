"""/internal/organizations: every active company of every active client, for jobs with no user (snapshots)."""
import uuid

import pytest

from config import settings
from models.client import Client
from models.organization import Organization
from services.permission_catalog import PERMISSION_CATALOG, member_permission_codes
from tests.conftest import TEST_CLIENT_ID, TEST_ORG_ID
from tests.test_internal_people import API

ORGANIZATIONS = f"{API}/internal/organizations"


def organization(name: str, client_id: uuid.UUID = TEST_CLIENT_ID, status: str = "active", relationship: str = "own") -> Organization:
    return Organization(
        id=uuid.uuid4(), client_id=client_id, name=name, email=f"{name.lower()}@example.com", base_currency="INR",
        fiscal_year_start="01-04", timezone="Asia/Kolkata", status=status, relationship=relationship,
    )


@pytest.mark.asyncio
async def test_lists_active_companies_of_active_clients_only(async_client, db_session):
    other_client = Client(id=uuid.uuid4(), name="Locked", code="LOCKED", contact_email="locked@example.com", status="suspended")
    db_session.add(other_client)
    associate = organization("Associate", relationship="associate")
    db_session.add_all([associate, organization("Closed", status="inactive"), organization("Hidden", client_id=other_client.id)])
    await db_session.commit()

    res = await async_client.get(ORGANIZATIONS)
    assert res.status_code == 200, res.text
    rows = {row["id"]: row for row in res.json()["data"]}
    assert set(rows) == {str(TEST_ORG_ID), str(associate.id)}
    assert rows[str(associate.id)] == {
        "id": str(associate.id), "client_id": str(TEST_CLIENT_ID), "name": "Associate", "relationship": "associate",
    }


@pytest.mark.asyncio
async def test_needs_the_internal_token(async_client, monkeypatch):
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    assert (await async_client.get(ORGANIZATIONS)).status_code == 403
    assert (await async_client.get(ORGANIZATIONS, headers={"X-FBOS-Internal-Token": "s3cret"})).status_code == 200


def test_insight_codes_are_in_the_catalog_and_members_do_not_get_them():
    codes = {"insight.audit.read", "insight.analytics.read", "insight.report.run"}
    assert codes <= {code for code, _, _ in PERMISSION_CATALOG}
    assert not codes & set(member_permission_codes([code for code, _, _ in PERMISSION_CATALOG]))
