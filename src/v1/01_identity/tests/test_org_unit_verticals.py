"""
Branch- and department-level verticals: own vs inherited, teams following their
department, and custom fields filtered to what applies in a unit.
"""
import httpx
import pytest
import pytest_asyncio

from tests.test_vertical_packs import make_vertical, section

API = "/api/identity/v1"


async def make_unit(client: httpx.AsyncClient, code: str, unit_type: str, parent_id: str | None = None) -> dict:
    body = {"code": code, "name": code.title(), "unit_type": unit_type}
    if parent_id:
        body["parent_id"] = parent_id
    res = await client.post(f"{API}/org-units", json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def set_verticals(client: httpx.AsyncClient, unit_id: str, *vertical_ids: str) -> httpx.Response:
    return await client.put(f"{API}/org-units/{unit_id}/verticals", json={"vertical_ids": list(vertical_ids)})


async def unit_verticals(client: httpx.AsyncClient, unit_id: str) -> dict:
    res = await client.get(f"{API}/org-units/{unit_id}/verticals")
    assert res.status_code == 200, res.text
    return res.json()


def names(refs: list[dict]) -> list[str]:
    return [r["name"] for r in refs]


@pytest_asyncio.fixture
async def structure(async_client):
    """software (vertical) on branch DEL; construction exists but is unused."""
    software = await make_vertical(async_client, "software")
    construction = await make_vertical(async_client, "construction")
    branch = await make_unit(async_client, "DEL", "branch")
    dept = await make_unit(async_client, "ENG", "department", branch["id"])
    team = await make_unit(async_client, "QA", "team", dept["id"])
    assert (await set_verticals(async_client, branch["id"], software["id"])).status_code == 200
    return {"software": software, "construction": construction, "branch": branch, "dept": dept, "team": team}


@pytest.mark.asyncio
async def test_departments_and_teams_inherit_until_they_set_their_own(async_client, structure):
    s = structure
    branch = await unit_verticals(async_client, s["branch"]["id"])
    assert names(branch["own"]) == names(branch["effective"]) == ["Software"]
    assert branch["inherited_from"] is None

    dept = await unit_verticals(async_client, s["dept"]["id"])
    assert dept["own"] == []
    assert names(dept["effective"]) == ["Software"]
    assert dept["inherited_from"]["id"] == s["branch"]["id"]

    # The department sets its own; its team follows the department, not the branch.
    res = await set_verticals(async_client, s["dept"]["id"], s["construction"]["id"], s["software"]["id"])
    assert res.status_code == 200
    assert names(res.json()["effective"]) == ["Construction", "Software"]
    team = await unit_verticals(async_client, s["team"]["id"])
    assert names(team["effective"]) == ["Construction", "Software"]
    assert team["inherited_from"]["id"] == s["dept"]["id"]

    # The structure list carries each unit's own verticals.
    units = {u["code"]: u for u in (await async_client.get(f"{API}/org-units")).json()["data"]}
    assert units["DEL"]["vertical_ids"] == [s["software"]["id"]]
    assert sorted(units["ENG"]["vertical_ids"]) == sorted([s["construction"]["id"], s["software"]["id"]])
    assert units["QA"]["vertical_ids"] == []

    # Clearing goes back to inheriting.
    assert (await set_verticals(async_client, s["dept"]["id"])).status_code == 200
    assert names((await unit_verticals(async_client, s["team"]["id"]))["effective"]) == ["Software"]


@pytest.mark.asyncio
async def test_teams_cannot_set_verticals_and_unknown_ones_are_rejected(async_client, structure):
    s = structure
    res = await set_verticals(async_client, s["team"]["id"], s["software"]["id"])
    assert res.status_code == 422
    assert res.json()["code"] == "VALIDATION_FAILED"

    res = await set_verticals(async_client, s["dept"]["id"], "00000000-0000-0000-0000-000000000000")
    assert res.status_code == 422

    assert (await async_client.get(f"{API}/org-units/00000000-0000-0000-0000-000000000000/verticals")).status_code == 404


@pytest.mark.asyncio
async def test_archived_verticals_stop_applying(async_client, structure):
    s = structure
    await async_client.patch(f"{API}/verticals/{s['construction']['id']}", json={"status": "archived"})
    assert (await set_verticals(async_client, s["dept"]["id"], s["construction"]["id"])).status_code == 422

    await async_client.patch(f"{API}/verticals/{s['software']['id']}", json={"status": "archived"})
    branch = await unit_verticals(async_client, s["branch"]["id"])
    assert names(branch["own"]) == ["Software"]  # still recorded
    assert branch["effective"] == []  # but no longer applies
    # Keeping an already-set archived vertical is allowed.
    assert (await set_verticals(async_client, s["branch"]["id"], s["software"]["id"])).status_code == 200


@pytest.mark.asyncio
async def test_moving_a_department_changes_what_it_inherits(async_client, structure):
    s = structure
    other_branch = await make_unit(async_client, "BOM", "branch")
    await set_verticals(async_client, other_branch["id"], s["construction"]["id"])

    res = await async_client.post(
        f"{API}/org-units/{s['dept']['id']}/move",
        json={"new_parent_id": other_branch["id"], "reason": "Reorg"},
        headers={"If-Match": f'"{s["dept"]["version"]}"'},
    )
    assert res.status_code == 200, res.text
    team = await unit_verticals(async_client, s["team"]["id"])
    assert names(team["effective"]) == ["Construction"]
    assert team["inherited_from"]["id"] == other_branch["id"]


@pytest.mark.asyncio
async def test_custom_fields_are_filtered_to_a_units_verticals(async_client, structure):
    s = structure
    # A construction-only pack, installed company-wide, plus a manual set for every vertical.
    res = await async_client.post(
        f"{API}/vertical-packs",
        json={"vertical_id": s["construction"]["id"], "code": "build", "name": "Build",
              "content": {"sections": [section("work.work_unit", {"key": "permit", "label": "Permit", "type": "text"})]}},
    )
    pack_id = res.json()["id"]
    await async_client.post(f"{API}/vertical-packs/{pack_id}/versions/1/publish")
    assert (await async_client.put(f"{API}/vertical-packs/{pack_id}/installation", json={"version_no": 1})).status_code == 200
    manual = await async_client.post(
        f"{API}/field-definitions",
        json={"object_type": "task.task", "json_schema": {"type": "object", "properties": {"note": {"type": "string"}}}},
    )
    assert manual.status_code == 201

    def object_types(res: httpx.Response) -> set[str]:
        assert res.status_code == 200, res.text
        return {d["object_type"] for d in res.json()["data"]}

    # The QA team inherits Software from the branch: construction fields don't apply there.
    in_team = await async_client.get(f"{API}/field-definitions", params={"org_unit_id": s["team"]["id"]})
    assert object_types(in_team) == {"task.task"}

    await set_verticals(async_client, s["dept"]["id"], s["construction"]["id"])
    in_team = await async_client.get(f"{API}/field-definitions", params={"org_unit_id": s["team"]["id"]})
    assert object_types(in_team) == {"task.task", "work.work_unit"}

    # Without a unit, everything is listed as before.
    assert object_types(await async_client.get(f"{API}/field-definitions")) == {"task.task", "work.work_unit"}
