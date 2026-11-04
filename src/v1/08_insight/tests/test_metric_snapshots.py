"""The CEO Command Center's daily snapshots: written by the gateway's nightly job, read back per company."""
import pytest

from config import settings
import permissions
from tests.conftest import BASE, OTHER_ORG_ID, TEST_ORG_ID

pytestmark = pytest.mark.asyncio

WRITE = f"{BASE}/internal/metric-snapshots"
READ = f"{BASE}/metric-snapshots"
DASHBOARD = permissions.CEO_DASHBOARD_READ
FINANCIALS = permissions.CEO_DASHBOARD_FINANCIALS


async def write(client, rows, org_id=TEST_ORG_ID):
    res = await client.put(WRITE, json={"organization_id": str(org_id), "rows": rows})
    assert res.status_code == 200, res.text
    return res.json()


def row(day, code, value):
    return {"day": day, "metric_code": code, "value": value}


async def read(client, *codes, granularity="day", start="2026-09-01", end="2026-10-31"):
    res = await client.get(READ, params={"metric_code": list(codes), "from": start, "to": end, "granularity": granularity})
    assert res.status_code == 200, res.text
    return {s["metric_code"]: s for s in res.json()["series"]}


async def test_flows_add_up_by_month_and_stocks_keep_the_last_day(client_as):
    client = client_as(DASHBOARD)
    await write(client, [
        row("2026-09-30", "ceo.revenue", 100), row("2026-10-01", "ceo.revenue", 250), row("2026-10-02", "ceo.revenue", 50),
        row("2026-09-30", "ceo.receivables", 900), row("2026-10-01", "ceo.receivables", 1000), row("2026-10-02", "ceo.receivables", 800),
    ])
    series = await read(client, "ceo.revenue", "ceo.receivables", granularity="month")
    assert series["ceo.revenue"]["kind"] == "flow"
    assert [(p["period"], p["value"], p["days"]) for p in series["ceo.revenue"]["points"]] == [("2026-09", 100, 1), ("2026-10", 300, 2)]
    receivables = series["ceo.receivables"]["points"]
    assert [(p["period"], p["value"], p["last_day"]) for p in receivables] == [("2026-09", 900, "2026-09-30"), ("2026-10", 800, "2026-10-02")]


async def test_writing_a_day_again_replaces_it(client_as):
    client = client_as(DASHBOARD)
    await write(client, [row("2026-10-01", "ceo.revenue", 250), row("2026-10-02", "ceo.revenue", 50)])
    assert (await write(client, [row("2026-10-01", "ceo.revenue", 300)]))["written"] == 1
    points = (await read(client, "ceo.revenue"))["ceo.revenue"]["points"]
    assert [(p["period"], p["value"]) for p in points] == [("2026-10-01", 300), ("2026-10-02", 50)]


async def test_a_day_with_no_snapshot_is_missing_not_zero(client_as):
    client = client_as(DASHBOARD)
    await write(client, [row("2026-10-01", "ceo.headcount", 12)])
    series = await read(client, "ceo.headcount", "ceo.clients")
    assert len(series["ceo.headcount"]["points"]) == 1
    assert series["ceo.clients"]["points"] == []


async def test_each_company_reads_only_its_own(client_as):
    client = client_as(DASHBOARD)
    await write(client, [row("2026-10-01", "ceo.revenue", 250)], org_id=OTHER_ORG_ID)
    assert (await read(client, "ceo.revenue"))["ceo.revenue"]["points"] == []
    client_as(DASHBOARD, org_id=OTHER_ORG_ID)
    assert (await read(client, "ceo.revenue"))["ceo.revenue"]["points"][0]["value"] == 250


async def test_financial_figures_need_the_financials_permission(client_as):
    client = client_as(DASHBOARD)
    res = await client.get(READ, params={"metric_code": ["ceo.revenue", "ceo.payroll"], "from": "2026-10-01", "to": "2026-10-31"})
    assert res.status_code == 403
    assert res.json()["detail"]["meta"]["required_permission"] == FINANCIALS
    client_as(DASHBOARD, FINANCIALS)
    assert (await client.get(READ, params={"metric_code": "ceo.payroll", "from": "2026-10-01", "to": "2026-10-31"})).status_code == 200


async def test_unknown_metrics_and_bad_periods_are_refused(client_as):
    client = client_as(DASHBOARD)
    unknown = await client.get(READ, params={"metric_code": "tasks.done", "from": "2026-10-01", "to": "2026-10-31"})
    assert unknown.status_code == 422
    backwards = await client.get(READ, params={"metric_code": "ceo.revenue", "from": "2026-10-31", "to": "2026-10-01"})
    assert backwards.status_code == 422
    too_long = await client.get(READ, params={"metric_code": "ceo.revenue", "from": "2020-01-01", "to": "2026-10-01"})
    assert too_long.status_code == 422
    res = await client.put(WRITE, json={"organization_id": str(TEST_ORG_ID), "rows": [row("2026-10-01", "tasks.done", 1)]})
    assert res.status_code == 422


async def test_writing_needs_the_internal_token(client_as, monkeypatch):
    client = client_as()
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    body = {"organization_id": str(TEST_ORG_ID), "rows": [row("2026-10-01", "ceo.revenue", 1)]}
    assert (await client.put(WRITE, json=body)).status_code == 403
    assert (await client.put(WRITE, json=body, headers={"X-FBOS-Internal-Token": "s3cret"})).status_code == 200


async def test_the_generic_metric_series_does_not_show_ceo_snapshots(client_as):
    client = client_as(permissions.ANALYTICS_READ, DASHBOARD)
    await write(client, [row("2026-10-01", "ceo.payroll", 500000)])
    res = await client.get(f"{BASE}/metrics/ceo.payroll", params={"from": "2026-10-01", "to": "2026-10-31"})
    assert res.status_code == 404
