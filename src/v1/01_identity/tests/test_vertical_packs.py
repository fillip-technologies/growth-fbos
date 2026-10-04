"""
Client-designed verticals and vertical packs: design (versions), preview and install.

The default `async_client` acts as TEST_USER, who holds the whole permission catalog.
"""
from datetime import date, timedelta
import uuid

import httpx
import pytest

from models.client import Client
from models.organization import Organization
from tests.conftest import TEST_ORG_ID, TEST_USER_ID
from tests.test_user_access import act_as, make_user

API = "/api/identity/v1"

TIER = {"key": "tier", "label": "Tier", "type": "choice", "options": ["Free", "Pro"], "required": True}
GO_LIVE = {"key": "go_live", "label": "Go live", "type": "date"}
SITE = {"key": "site_code", "label": "Site code", "type": "text"}


def section(object_type: str, *fields: dict) -> dict:
    return {"type": "custom_fields", "object_type": object_type, "fields": list(fields)}


async def make_vertical(client: httpx.AsyncClient, code: str = "construction") -> dict:
    res = await client.post(f"{API}/verticals", json={"name": code.title(), "code": code})
    assert res.status_code == 201, res.text
    return res.json()


async def make_published_pack(client: httpx.AsyncClient, sections: list[dict], code: str = "house") -> dict:
    vertical = await make_vertical(client)
    res = await client.post(
        f"{API}/vertical-packs",
        json={"vertical_id": vertical["id"], "code": code, "name": "House pack", "content": {"sections": sections}},
    )
    assert res.status_code == 201, res.text
    pack = res.json()
    res = await client.post(f"{API}/vertical-packs/{pack['id']}/versions/1/publish")
    assert res.status_code == 200, res.text
    return res.json()


async def live_definitions(client: httpx.AsyncClient) -> list[dict]:
    res = await client.get(f"{API}/field-definitions", params={"status": "published"})
    assert res.status_code == 200
    return res.json()["data"]


# --------------------------------------------------------------------------- verticals

@pytest.mark.asyncio
async def test_client_creates_renames_and_archives_its_own_verticals(async_client):
    res = await async_client.get(f"{API}/verticals")
    assert res.status_code == 200
    assert res.json()["data"] == []  # nothing is predefined

    vertical = await make_vertical(async_client, "construction")
    dup = await async_client.post(f"{API}/verticals", json={"name": "Again", "code": "construction"})
    assert dup.status_code == 409

    res = await async_client.patch(f"{API}/verticals/{vertical['id']}", json={"name": "Building", "status": "archived"})
    assert res.status_code == 200
    assert res.json()["name"] == "Building"
    assert res.json()["status"] == "archived"

    active = await async_client.get(f"{API}/verticals", params={"status": "active"})
    assert active.json()["data"] == []

    # A pack can't be started on an archived vertical.
    res = await async_client.post(
        f"{API}/vertical-packs", json={"vertical_id": vertical["id"], "code": "p", "name": "P"}
    )
    assert res.status_code == 422
    assert res.json()["code"] == "VERTICAL_PACK_INVALID"


# --------------------------------------------------------------------------- design

@pytest.mark.asyncio
async def test_pack_content_is_validated(async_client):
    vertical = await make_vertical(async_client)
    base = {"vertical_id": vertical["id"], "code": "p", "name": "P"}

    two_keys = {"sections": [section("work.work_unit", SITE, {**SITE, "label": "Again"})]}
    assert (await async_client.post(f"{API}/vertical-packs", json={**base, "content": two_keys})).status_code == 422

    one_option = {"sections": [section("work.work_unit", {**TIER, "options": ["Free"]})]}
    assert (await async_client.post(f"{API}/vertical-packs", json={**base, "content": one_option})).status_code == 422

    same_type_twice = {"sections": [section("work.work_unit", SITE), section("work.work_unit", GO_LIVE)]}
    assert (await async_client.post(f"{API}/vertical-packs", json={**base, "content": same_type_twice})).status_code == 422

    unknown_type = {"sections": [section("nope.thing", SITE)]}
    res = await async_client.post(f"{API}/vertical-packs", json={**base, "content": unknown_type})
    assert res.status_code == 422
    assert res.json()["code"] == "VERTICAL_PACK_INVALID"


@pytest.mark.asyncio
async def test_draft_is_edited_then_frozen_by_publishing(async_client):
    vertical = await make_vertical(async_client)
    res = await async_client.post(
        f"{API}/vertical-packs", json={"vertical_id": vertical["id"], "code": "house", "name": "House"}
    )
    assert res.status_code == 201
    pack = res.json()
    assert pack["draft_version"] == 1
    assert pack["latest_published_version"] is None
    url = f"{API}/vertical-packs/{pack['id']}"

    # An empty draft can't be published.
    assert (await async_client.post(f"{url}/versions/1/publish")).json()["code"] == "VERTICAL_PACK_INVALID"

    content = {"sections": [section("work.work_unit", SITE)]}
    res = await async_client.put(f"{url}/versions/1", json={"content": content}, headers={"If-Match": '"1"'})
    assert res.status_code == 200
    assert res.json()["versions"][0]["revision"] == 2

    stale = await async_client.put(f"{url}/versions/1", json={"content": content}, headers={"If-Match": '"1"'})
    assert stale.status_code == 412

    res = await async_client.post(f"{url}/versions/1/publish", headers={"If-Match": '"2"'})
    assert res.status_code == 200
    assert res.json()["latest_published_version"] == 1
    assert res.json()["draft_version"] is None

    frozen = await async_client.put(f"{url}/versions/1", json={"content": content})
    assert frozen.status_code == 409
    assert frozen.json()["code"] == "PACK_VERSION_CONFLICT"

    # The next draft starts as a copy of v1; only one draft at a time.
    res = await async_client.post(f"{url}/versions")
    assert res.status_code == 201
    v2 = res.json()["versions"][1]
    assert (v2["version_no"], v2["status"]) == (2, "draft")
    assert v2["content"] == res.json()["versions"][0]["content"]
    assert (await async_client.post(f"{url}/versions")).status_code == 409


# --------------------------------------------------------------------------- install

@pytest.mark.asyncio
async def test_install_creates_fields_and_is_idempotent(async_client):
    pack = await make_published_pack(async_client, [section("work.work_unit", TIER, GO_LIVE), section("revenue.deal", SITE)])
    url = f"{API}/vertical-packs/{pack['id']}"

    # A draft can't be installed; a published version can be previewed first.
    preview = await async_client.get(f"{url}/versions/1/preview")
    assert preview.status_code == 200
    assert preview.json()["installed_version_no"] is None
    assert {(i["object_type"], i["action"]) for i in preview.json()["items"]} == {
        ("work.work_unit", "create"), ("revenue.deal", "create"),
    }
    assert await live_definitions(async_client) == []  # preview changes nothing

    res = await async_client.put(f"{url}/installation", json={"version_no": 1})
    assert res.status_code == 200, res.text
    assert res.json()["version_no"] == 1

    live = await live_definitions(async_client)
    assert len(live) == 2
    work = next(d for d in live if d["object_type"] == "work.work_unit")
    assert work["source_pack_id"] == pack["id"]
    assert work["source_pack_version"] == 1
    assert work["vertical_id"] == pack["vertical"]["id"]
    assert work["json_schema"] == {
        "type": "object",
        "properties": {
            "tier": {"title": "Tier", "type": "string", "enum": ["Free", "Pro"]},
            "go_live": {"title": "Go live", "type": "string", "format": "date"},
        },
        "required": ["tier"],
    }

    # Installing the same version again creates nothing.
    again = await async_client.put(f"{url}/installation", json={"version_no": 1})
    assert {i["action"] for i in again.json()["results"]} == {"unchanged"}
    assert len(await live_definitions(async_client)) == 2

    listed = (await async_client.get(f"{API}/vertical-packs")).json()["data"]
    assert listed[0]["installation"]["version_no"] == 1


@pytest.mark.asyncio
async def test_upgrade_updates_and_retires_without_deleting(async_client):
    pack = await make_published_pack(async_client, [section("work.work_unit", TIER, GO_LIVE), section("revenue.deal", SITE)])
    url = f"{API}/vertical-packs/{pack['id']}"
    await async_client.put(f"{url}/installation", json={"version_no": 1})
    v1_work = next(d for d in await live_definitions(async_client) if d["object_type"] == "work.work_unit")

    # v2: work units drop go_live, make tier optional and add site_code; deals are dropped.
    await async_client.post(f"{url}/versions")
    v2_content = {"sections": [section("work.work_unit", {**TIER, "required": False}, SITE)]}
    assert (await async_client.put(f"{url}/versions/2", json={"content": v2_content})).status_code == 200
    assert (await async_client.post(f"{url}/versions/2/publish")).status_code == 200

    preview = (await async_client.get(f"{url}/versions/2/preview")).json()
    assert preview["installed_version_no"] == 1
    items = {i["object_type"]: i for i in preview["items"]}
    assert items["work.work_unit"]["action"] == "update"
    assert items["work.work_unit"]["added_fields"] == ["site_code"]
    assert items["work.work_unit"]["removed_fields"] == ["go_live"]
    assert items["work.work_unit"]["changed_fields"] == ["tier"]
    assert items["revenue.deal"]["action"] == "retire"

    res = await async_client.put(f"{url}/installation", json={"version_no": 2})
    assert res.status_code == 200
    assert res.json()["version_no"] == 2

    live = await live_definitions(async_client)
    assert [d["object_type"] for d in live] == ["work.work_unit"]
    assert live[0]["source_pack_version"] == 2
    assert live[0]["version_no"] == v1_work["version_no"] + 1

    retired = (await async_client.get(f"{API}/field-definitions", params={"status": "retired"})).json()["data"]
    assert {d["object_type"] for d in retired} == {"work.work_unit", "revenue.deal"}

    # Going back to v1 is an explicit choice and works the same way.
    res = await async_client.put(f"{url}/installation", json={"version_no": 1})
    assert res.status_code == 200
    assert {d["object_type"] for d in await live_definitions(async_client)} == {"work.work_unit", "revenue.deal"}


@pytest.mark.asyncio
async def test_draft_versions_cannot_be_installed(async_client):
    pack = await make_published_pack(async_client, [section("work.work_unit", SITE)])
    url = f"{API}/vertical-packs/{pack['id']}"
    await async_client.post(f"{url}/versions")

    res = await async_client.put(f"{url}/installation", json={"version_no": 2})
    assert res.status_code == 409
    assert (await async_client.get(f"{url}/versions/2/preview")).status_code == 409
    assert (await async_client.put(f"{url}/installation", json={"version_no": 9})).status_code == 404


# --------------------------------------------------------------------------- access

@pytest.mark.asyncio
async def test_installers_cannot_design_and_designers_cannot_install(async_client, db_session):
    pack = await make_published_pack(async_client, [section("work.work_unit", SITE)])
    url = f"{API}/vertical-packs/{pack['id']}"

    installer = await make_user(db_session, "installer@example.com", grants=[("identity.vertical_pack.install", None, False)])
    act_as(installer.id)
    assert (await async_client.get(f"{API}/vertical-packs")).status_code == 200
    assert (await async_client.post(f"{url}/versions")).status_code == 403
    assert (await async_client.post(f"{API}/verticals", json={"name": "X", "code": "x"})).status_code == 403
    assert (await async_client.put(f"{url}/installation", json={"version_no": 1})).status_code == 200

    designer = await make_user(db_session, "designer@example.com", grants=[("identity.vertical_pack.manage", None, False)])
    act_as(designer.id)
    assert (await async_client.get(url)).status_code == 200
    assert (await async_client.put(f"{url}/installation", json={"version_no": 1})).status_code == 403

    nobody = await make_user(db_session, "nobody@example.com")
    act_as(nobody.id)
    assert (await async_client.get(f"{API}/vertical-packs")).status_code == 403
    assert (await async_client.get(f"{API}/verticals")).status_code == 200  # pickers need the list


@pytest.mark.asyncio
async def test_packs_are_shared_across_a_clients_organizations_only(async_client, db_session):
    pack = await make_published_pack(async_client, [section("work.work_unit", SITE)])
    url = f"{API}/vertical-packs/{pack['id']}"

    # Another organization of the same client sees the pack and installs it independently.
    sister = Organization(
        id=uuid.uuid4(), client_id=(await db_session.get(Organization, TEST_ORG_ID)).client_id,
        name="Sister", code="SISTER", email="s@example.com", base_currency="USD",
        fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(sister)
    await db_session.commit()
    sister_admin = await make_user(
        db_session, "sister@example.com", org_id=sister.id,
        grants=[("identity.vertical_pack.install", None, False), ("identity.field_definition.read", None, False)],
    )
    act_as(sister_admin.id, org_id=sister.id)
    res = await async_client.get(url)
    assert res.status_code == 200
    assert res.json()["installation"] is None
    assert (await async_client.put(f"{url}/installation", json={"version_no": 1})).status_code == 200
    assert len(await live_definitions(async_client)) == 1

    act_as(TEST_USER_ID)
    assert (await async_client.get(url)).json()["installation"] is None  # not installed here yet
    assert await live_definitions(async_client) == []

    # A different client can't see or install it.
    other_client = Client(
        id=uuid.uuid4(), name="Other", code="OTHER", contact_email="o@example.com",
        subscription_start=date.today() - timedelta(days=1), subscription_end=date.today() + timedelta(days=30),
    )
    db_session.add(other_client)
    await db_session.flush()
    other_org = Organization(
        id=uuid.uuid4(), client_id=other_client.id, name="Other Co", code="OTHERCO", email="oc@example.com",
        base_currency="USD", fiscal_year_start="01-04", timezone="UTC", status="active",
    )
    db_session.add(other_org)
    await db_session.commit()
    outsider = await make_user(
        db_session, "outsider@example.com", org_id=other_org.id,
        grants=[("identity.vertical_pack.install", None, False), ("identity.vertical_pack.manage", None, False)],
    )
    act_as(outsider.id, org_id=other_org.id)
    assert (await async_client.get(url)).status_code == 404
    assert (await async_client.put(f"{url}/installation", json={"version_no": 1})).status_code == 404
    assert (await async_client.get(f"{API}/vertical-packs")).json()["data"] == []
    assert (await async_client.get(f"{API}/verticals")).json()["data"] == []

