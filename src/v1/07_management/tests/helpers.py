"""Builders the test modules share: a fiscal year with its periods, KPIs, approved targets, resources."""

from typing import Optional
import uuid

import httpx

from tests.conftest import BASE, TEST_USER_ID, FakeControl


async def ok(response: httpx.Response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


async def fiscal_year(client: httpx.AsyncClient, code: str = "FY30", start: str = "2030-01-01", end: str = "2030-12-31") -> dict:
    """A year with quarters holding months; returns {"year", "periods": {name: period}}."""
    year = await ok(await client.post(f"{BASE}/fiscal-years", json={
        "code": code, "start_date": start, "end_date": end, "period_types": ["quarter", "month"],
    }), 201)
    periods = await ok(await client.get(f"{BASE}/planning-periods", params={"fiscal_year_id": year["id"], "limit": 100}))
    return {"year": year, "periods": {p["name"]: p for p in periods["data"]}}


async def kpi(client: httpx.AsyncClient, code: str, **fields) -> dict:
    body = {"code": code, "name": code.title(), "unit": "count", "owner_user_id": str(TEST_USER_ID), **fields}
    return await ok(await client.post(f"{BASE}/kpi-definitions", json=body), 201)


async def measure(client: httpx.AsyncClient, code: str, day: str, value: float, **dimensions) -> dict:
    body = {"kpi_code": code, "measured_on": day, "value": value, "dimensions": {k: str(v) for k, v in dimensions.items()}}
    return await ok(await client.post(f"{BASE}/measurements", json=body), 201)


async def approved_target(
    client: httpx.AsyncClient, control: FakeControl, code: str, period_id: str, value: float,
    scope: Optional[dict] = None, goal_id: Optional[str] = None,
) -> dict:
    """A target submitted to control, approved there, and picked up by management."""
    body = {"kpi_code": code, "period_id": period_id, "target_value": value, "scope": scope or {}}
    if goal_id:
        body["goal_id"] = goal_id
    target = await ok(await client.post(f"{BASE}/kpi-targets", json=body), 201)
    submitted = await ok(await client.post(
        f"{BASE}/kpi-targets/{target['id']}/submit", headers={"If-Match": str(target["version"])}
    ))
    control.decide(uuid.UUID(submitted["approval_request_id"]), "approved")
    approved = await ok(await client.get(f"{BASE}/kpi-targets/{target['id']}"))
    assert approved["status"] == "approved", approved
    return approved


async def results(client: httpx.AsyncClient, period_id: str, **params) -> list[dict]:
    body = await ok(await client.get(f"{BASE}/kpi-results", params={"period_id": period_id, "limit": 100, **params}))
    return body["data"]


async def resource(client: httpx.AsyncClient, user_id: Optional[uuid.UUID] = None, **fields) -> dict:
    body = {
        "resource_type": "employee", "user_id": str(user_id or uuid.uuid4()), "effective_from": "2030-01-01", **fields,
    }
    return await ok(await client.post(f"{BASE}/resources", json=body), 201)


async def rebuild(client: httpx.AsyncClient, start: str, end: str) -> dict:
    return await ok(await client.post(f"{BASE}/capacity-ledger/rebuilds", json={"from": start, "to": end}))
