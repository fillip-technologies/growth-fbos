"""
A form's custom fields as one list: GET and PUT /field-definitions/forms/{object_type}.

The default `async_client` acts as TEST_USER, who holds the whole permission catalog.
"""
import uuid

import httpx
import pytest

from tests.test_user_access import act_as, make_user
from tests.test_vertical_packs import make_published_pack, make_vertical, section

API = "/api/identity/v1"
LEAD_FORM = f"{API}/field-definitions/forms/revenue.lead"
PROJECT_FORM = f"{API}/field-definitions/forms/work.work_unit"

REFERRAL = {
    "key": "referral_name",
    "label": "Referral name",
    "show_when": {"input": "source", "values": ["referral", "partner"]},
}
TIER = {"key": "tier", "label": "Tier", "type": "choice", "options": ["Gold", "Silver"], "required": True}
VISIT_NOTES = {"key": "visit_notes", "label": "Visit notes", "type": "long_text", "help": "What happened on site"}


def as_answered(field: dict) -> dict:
    """A field as the API answers it: every attribute present."""
    return {
        "type": "text", "required": False, "options": [], "help": None, "vertical_ids": [], "show_when": None,
        **field,
    }


async def save(client: httpx.AsyncClient, url: str, fields: list[dict], revision: int) -> httpx.Response:
    return await client.put(url, json={"fields": fields}, headers={"If-Match": f'"{revision}"'})


async def stored(client: httpx.AsyncClient, object_type: str, status: str = "published") -> list[dict]:
    res = await client.get(f"{API}/field-definitions", params={"object_type": object_type, "status": status})
    assert res.status_code == 200
    return res.json()["data"]


@pytest.mark.asyncio
async def test_a_form_starts_with_no_fields(async_client):
    res = await async_client.get(LEAD_FORM)
    assert res.status_code == 200
    assert res.json() == {"object_type": "revenue.lead", "revision": 0, "fields": [], "notes": []}
    assert res.headers["etag"] == '"0"'


@pytest.mark.asyncio
async def test_saving_makes_the_fields_live_at_once(async_client):
    res = await save(async_client, LEAD_FORM, [REFERRAL, TIER, VISIT_NOTES], 0)
    assert res.status_code == 200, res.text
    assert res.headers["etag"] == '"1"'
    assert res.json()["revision"] == 1
    assert res.json()["fields"] == [as_answered(REFERRAL), as_answered(TIER), as_answered(VISIT_NOTES)]

    # Stored as one published list for every vertical, which forms read as they do today.
    [definition] = await stored(async_client, "revenue.lead")
    assert definition["vertical_id"] is None
    assert definition["json_schema"] == {
        "type": "object",
        "properties": {
            "referral_name": {"title": "Referral name", "type": "string"},
            "tier": {"title": "Tier", "type": "string", "enum": ["Gold", "Silver"]},
            "visit_notes": {"title": "Visit notes", "type": "string", "description": "What happened on site"},
        },
        "required": ["tier"],
    }
    assert definition["ui_schema"] == {
        "ui:order": ["referral_name", "tier", "visit_notes"],
        "referral_name": {"ui:show_when": {"input": "source", "values": ["referral", "partner"]}},
        "visit_notes": {"ui:widget": "textarea"},
    }
    assert (await async_client.get(LEAD_FORM)).json()["fields"] == res.json()["fields"]


@pytest.mark.asyncio
async def test_every_field_type_is_stored_and_read_back(async_client):
    fields = [
        {"key": "t_text", "label": "Text"},
        {"key": "t_long_text", "label": "Long text", "type": "long_text"},
        {"key": "t_number", "label": "Number", "type": "number"},
        {"key": "t_integer", "label": "Whole number", "type": "integer"},
        {"key": "t_boolean", "label": "Yes or no", "type": "boolean"},
        {"key": "t_date", "label": "Date", "type": "date"},
        {"key": "t_datetime", "label": "Date and time", "type": "datetime"},
        {"key": "t_choice", "label": "Choice", "type": "choice", "options": ["A", "B"]},
        {"key": "t_multi_choice", "label": "Several choices", "type": "multi_choice", "options": ["A", "B", "C"]},
        {"key": "t_url", "label": "Web link", "type": "url"},
        {"key": "t_email", "label": "Email", "type": "email"},
        {"key": "t_phone", "label": "Phone", "type": "phone"},
    ]
    res = await save(async_client, PROJECT_FORM, fields, 0)
    assert res.status_code == 200, res.text
    assert res.json()["fields"] == [as_answered(f) for f in fields]

    [definition] = await stored(async_client, "work.work_unit")
    properties = definition["json_schema"]["properties"]
    assert properties["t_multi_choice"] == {
        "title": "Several choices", "type": "array", "items": {"type": "string", "enum": ["A", "B", "C"]},
        "uniqueItems": True,
    }
    assert properties["t_integer"] == {"title": "Whole number", "type": "integer"}
    assert properties["t_datetime"] == {"title": "Date and time", "type": "string", "format": "date-time"}
    assert properties["t_url"]["format"] == "uri"
    assert properties["t_phone"]["format"] == "phone"


@pytest.mark.asyncio
async def test_vertical_fields_are_stored_per_vertical_and_read_as_today(async_client):
    construction = await make_vertical(async_client, "construction")
    interiors = await make_vertical(async_client, "interiors")
    fields = [
        {"key": "site_code", "label": "Site code"},
        {"key": "permit_number", "label": "Permit number", "vertical_ids": [construction["id"]]},
        {
            "key": "finish", "label": "Finish", "type": "choice", "options": ["Matte", "Gloss"],
            "vertical_ids": [construction["id"], interiors["id"]],
        },
    ]
    res = await save(async_client, PROJECT_FORM, fields, 0)
    assert res.status_code == 200, res.text
    assert res.json()["fields"] == [as_answered(f) for f in fields]

    live = await stored(async_client, "work.work_unit")
    assert {d["vertical_id"]: set(d["json_schema"]["properties"]) for d in live} == {
        None: {"site_code"},
        construction["id"]: {"permit_number", "finish"},
        interiors["id"]: {"finish"},
    }
    assert {d["version_no"] for d in live} == {1}

    async def keys_shown(vertical_id: str | None = None) -> set[str]:
        params = {"object_type": "work.work_unit", "status": "published", "scoped": "true"}
        if vertical_id:
            params["vertical_id"] = vertical_id
        data = (await async_client.get(f"{API}/field-definitions", params=params)).json()["data"]
        return {key for d in data for key in d["json_schema"]["properties"]}

    assert await keys_shown(construction["id"]) == {"site_code", "permit_number", "finish"}
    assert await keys_shown(interiors["id"]) == {"site_code", "finish"}
    assert await keys_shown() == {"site_code"}


@pytest.mark.asyncio
async def test_saving_again_retires_the_old_lists_without_deleting_them(async_client):
    assert (await save(async_client, LEAD_FORM, [REFERRAL, TIER], 0)).status_code == 200
    res = await save(async_client, LEAD_FORM, [TIER], 1)
    assert res.status_code == 200, res.text
    assert res.json()["revision"] == 2
    assert [f["key"] for f in res.json()["fields"]] == ["tier"]

    retired = await stored(async_client, "revenue.lead", status="retired")
    assert [set(d["json_schema"]["properties"]) for d in retired] == [{"referral_name", "tier"}]
    assert len(await stored(async_client, "revenue.lead")) == 1

    # A save quoting an older revision is refused: someone else saved in between.
    stale = await save(async_client, LEAD_FORM, [REFERRAL], 1)
    assert stale.status_code == 412
    assert stale.json()["code"] == "PRECONDITION_FAILED"


@pytest.mark.asyncio
async def test_hand_made_and_pack_lists_merge_into_one_and_saving_replaces_them(async_client):
    # A hand-made list for every vertical, made and published the old way (it ends at version 2).
    res = await async_client.post(f"{API}/field-definitions", json={
        "object_type": "work.work_unit",
        "json_schema": {
            "type": "object",
            "properties": {"tier": {"title": "Tier", "type": "string", "enum": ["Free", "Pro"]}},
            "required": ["tier"],
        },
        "ui_schema": {"ui:order": ["tier"]},
    })
    assert res.status_code == 201, res.text
    hand_made = res.json()
    assert (await async_client.post(f"{API}/field-definitions/{hand_made['id']}/publish")).status_code == 200

    # A pack for one vertical installs site_code, and a different field under the same key.
    site_code = {"key": "site_code", "label": "Site code", "type": "text"}
    other_tier = {"key": "tier", "label": "Tier", "type": "text"}
    pack = await make_published_pack(async_client, [section("work.work_unit", site_code, other_tier)])
    res = await async_client.put(f"{API}/vertical-packs/{pack['id']}/installation", json={"version_no": 1})
    assert res.status_code == 200, res.text
    vertical_id = pack["vertical"]["id"]

    form = (await async_client.get(PROJECT_FORM)).json()
    assert form["revision"] == 2
    assert [(f["key"], f["type"], f["vertical_ids"]) for f in form["fields"]] == [
        ("tier", "choice", []),  # the list for every vertical wins
        ("site_code", "text", [vertical_id]),
    ]
    assert len(form["notes"]) == 1
    assert "(tier)" in form["notes"][0]

    # Saving what the editor shows makes it the form's one list; the old lists are retired.
    res = await save(async_client, PROJECT_FORM, form["fields"], form["revision"])
    assert res.status_code == 200, res.text
    assert res.json()["revision"] == 3
    assert res.json()["fields"] == form["fields"]
    assert res.json()["notes"] == []

    live = await stored(async_client, "work.work_unit")
    assert {d["vertical_id"] for d in live} == {None, vertical_id}
    assert all(d["source_pack_id"] is None for d in live)
    retired = await stored(async_client, "work.work_unit", status="retired")
    assert hand_made["id"] in {d["id"] for d in retired}
    assert any(d["source_pack_id"] == pack["id"] for d in retired)


@pytest.mark.asyncio
async def test_keys_the_system_uses_and_wrong_fields_are_refused(async_client):
    budget = await save(async_client, LEAD_FORM, [{"key": "budget", "label": "Budget"}], 0)
    assert budget.status_code == 422
    assert budget.json()["code"] == "FIELD_SCHEMA_INVALID"
    assert "budget" in budget.json()["detail"]

    task_form = f"{API}/field-definitions/forms/task.task"
    outcome = await save(async_client, task_form, [{"key": "outcome", "label": "Outcome"}], 0)
    assert outcome.status_code == 422
    assert outcome.json()["code"] == "FIELD_SCHEMA_INVALID"

    elsewhere = [{"key": "permit", "label": "Permit", "vertical_ids": [str(uuid.uuid4())]}]
    unknown_vertical = await save(async_client, LEAD_FORM, elsewhere, 0)
    assert unknown_vertical.status_code == 422
    assert unknown_vertical.json()["code"] == "FIELD_SCHEMA_INVALID"

    wrong_lists = [
        [{"key": "tier", "label": "Tier", "type": "choice", "options": ["Only one"]}],
        [{"key": "note", "label": "Note", "options": ["A", "B"]}],
        [{"key": "tier", "label": "Tier"}, {"key": "tier", "label": "Again"}],
        [{"key": "Bad Key", "label": "Bad"}],
        [{"key": "note", "label": "   "}],
        [{"key": "note", "label": "Note", "show_when": {"input": "source", "values": []}}],
        [{"key": "note", "label": "Note", "show_when": {"input": "note", "values": ["x"]}}],
        [{
            "key": "note", "label": "Note", "vertical_ids": [str(uuid.uuid4())],
            "show_when": {"input": "source", "values": ["referral"]},
        }],
    ]
    for wrong in wrong_lists:
        res = await save(async_client, LEAD_FORM, wrong, 0)
        assert res.status_code == 422, wrong

    assert (await async_client.get(f"{API}/field-definitions/forms/nope.thing")).status_code == 404
    assert (await save(async_client, f"{API}/field-definitions/forms/nope.thing", [], 0)).status_code == 404
    assert await stored(async_client, "revenue.lead") == []


@pytest.mark.asyncio
async def test_reading_needs_read_and_saving_needs_publish(async_client, db_session):
    reader = await make_user(db_session, "reader@example.com", grants=[("identity.field_definition.read", None, False)])
    act_as(reader.id)
    assert (await async_client.get(LEAD_FORM)).status_code == 200
    assert (await save(async_client, LEAD_FORM, [TIER], 0)).status_code == 403

    publisher = await make_user(
        db_session, "publisher@example.com", grants=[("identity.field_definition.publish", None, False)]
    )
    act_as(publisher.id)
    assert (await async_client.get(LEAD_FORM)).status_code == 403
    assert (await save(async_client, LEAD_FORM, [TIER], 0)).status_code == 200

    nobody = await make_user(db_session, "nobody@example.com")
    act_as(nobody.id)
    assert (await async_client.get(LEAD_FORM)).status_code == 403
    assert (await save(async_client, LEAD_FORM, [TIER], 1)).status_code == 403
