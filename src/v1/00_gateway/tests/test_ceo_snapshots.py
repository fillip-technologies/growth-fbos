"""The nightly CEO snapshots: what one summary gives, what a night asks for, and the run end to end."""
from datetime import date, datetime
import json
from pathlib import Path
import re
import uuid

import httpx
import pytest

from config import settings
from services import ceo_snapshots as job
from services.ceo_snapshots import (
    DELIVERY,
    FINANCE,
    MANAGEMENT,
    PEOPLE,
    REVENUE,
    Read,
    SnapshotJob,
    backfill_reads,
    night_reads,
    rows_for,
    seconds_until,
)
from services.identity_client import IdentityClient

DAY = date(2026, 11, 2)
OWN, ASSOCIATE = uuid.uuid4(), uuid.uuid4()


def values(rows) -> dict[tuple[str, str], float]:
    return {(row["day"], row["metric_code"]): row["value"] for row in rows}


def test_a_day_gives_what_happened_and_where_things_stood():
    summary = {"revenue": {"amount": "1500.50", "currency": "INR"}, "receivables": {"amount": "900.00"},
               "overdue": {"amount": "100.00"}, "pipeline": 5000, "clients": {"total": 7}}
    assert values(rows_for(Read(REVENUE, DAY, with_stocks=True), summary)) == {
        ("2026-11-02", "ceo.revenue"): 1500.5,
        ("2026-11-02", "ceo.receivables"): 900.0,
        ("2026-11-02", "ceo.overdue"): 100.0,
        ("2026-11-02", "ceo.pipeline"): 5000.0,
        ("2026-11-02", "ceo.clients"): 7.0,
    }
    # An earlier day asked again: only what happened, positions can't be read back.
    assert values(rows_for(Read(REVENUE, DAY, with_stocks=False), summary)) == {("2026-11-02", "ceo.revenue"): 1500.5}


def test_payroll_lands_on_the_first_of_its_month():
    rows = rows_for(Read(PEOPLE, DAY, with_stocks=True), {"payroll": 250000, "headcount": 12})
    assert values(rows) == {("2026-11-01", "ceo.payroll"): 250000.0, ("2026-11-02", "ceo.headcount"): 12.0}


def test_no_scorecard_results_means_no_health_score_not_zero():
    assert rows_for(Read(MANAGEMENT, DAY, True), {"health": {"available": False, "score_pct": None}}) == []
    rows = rows_for(Read(MANAGEMENT, DAY, True), {"health": {"available": True, "score_pct": 72.5}})
    assert values(rows) == {("2026-11-02", "ceo.health_score"): 72.5}


def test_a_figure_the_summary_does_not_give_is_left_out():
    assert values(rows_for(Read(DELIVERY, DAY, True), {"costs": 10})) == {("2026-11-02", "ceo.project_costs"): 10.0}


def test_a_night_reads_the_day_in_full_the_days_before_again_and_last_months_payroll(monkeypatch):
    reads = night_reads((REVENUE, PEOPLE, MANAGEMENT), DAY, refresh_days=3)
    asked = {(read.source.name, read.day.isoformat(), read.with_stocks) for read in reads}
    assert asked == {
        ("revenue", "2026-11-02", True), ("people", "2026-11-02", True), ("management", "2026-11-02", True),
        ("revenue", "2026-11-01", False), ("revenue", "2026-10-31", False),
        ("people", "2026-10-01", False),
    }
    assert len(reads) == len(asked)


def test_a_backfill_reads_each_day_and_each_months_payroll():
    reads = backfill_reads((FINANCE, PEOPLE, MANAGEMENT), date(2026, 10, 30), date(2026, 11, 1))
    asked = sorted((read.source.name, read.day.isoformat()) for read in reads)
    assert asked == [
        ("finance", "2026-10-30"), ("finance", "2026-10-31"), ("finance", "2026-11-01"),
        ("people", "2026-10-01"), ("people", "2026-11-01"),
    ]
    assert not any(read.with_stocks for read in reads)


def test_the_next_run_is_today_at_the_hour_else_tomorrow():
    assert seconds_until(datetime(2026, 11, 3, 0, 30), 1) == 30 * 60
    assert seconds_until(datetime(2026, 11, 3, 1, 0), 1) == 24 * 3600
    assert seconds_until(datetime(2026, 11, 3, 23, 0), 1) == 2 * 3600


def test_every_code_written_is_one_insight_knows():
    insight = (Path(__file__).resolve().parents[2] / "08_insight" / "services" / "ceo_metrics.py").read_text()
    known = set(re.findall(r'"(ceo\.[a-z_]+)"', insight))
    sources = (*job.COMPANY_SOURCES, job.INVENTORY)
    written = {code for s in sources for code in (*s.flows, *s.monthly_flows, *s.stocks)}
    assert written <= known


# --------------------------------------------------------------------------- end to end


class Services:
    """Identity, every summary and Insight, as the job meets them; records what it was asked."""

    def __init__(self, down: set[str] = frozenset()) -> None:
        self.down = down
        self.calls: list[httpx.Request] = []
        self.stored: dict[str, list[dict]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/internal/organizations"):
            return httpx.Response(200, json={"data": [
                {"id": str(OWN), "client_id": str(uuid.uuid4()), "name": "Fillip", "relationship": "own"},
                {"id": str(ASSOCIATE), "client_id": str(uuid.uuid4()), "name": "Associate", "relationship": "associate"},
            ]})
        if path.endswith("/internal/metric-snapshots"):
            body = json.loads(request.content)
            self.stored.setdefault(body["organization_id"], []).extend(body["rows"])
            return httpx.Response(200, json={"written": len(body["rows"])})
        service = path.split("/")[2]
        if service in self.down:
            return httpx.Response(503)
        day = request.url.params["from"]
        return httpx.Response(200, json={
            "revenue": {"amount": "100.00"}, "receivables": 50, "overdue": 0, "pipeline": 10, "clients": {"total": 1},
            "projects": {"running": 2, "at_risk": 1}, "costs": 5, "headcount": 3, "payroll": 1000,
            "health": {"available": True, "score_pct": 80}, "expenses": 7, "income": 1,
            "purchase_orders": {"committed": {"amount": "40.00"}}, "day": day,
        })


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setattr(settings, "internal_service_token", "s3cret")
    monkeypatch.setattr(settings, "ceo_snapshot_refresh_days", 2)
    monkeypatch.setattr(settings, "inventory_organization_id", str(OWN))

    async def run(down: set[str] = frozenset()) -> tuple[Services, job.NightResult]:
        fake = Services(down)
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake)) as http:
            identity = IdentityClient(http, "http://identity", "s3cret", 5)
            result = await SnapshotJob(http, identity).night(DAY)
        return fake, result

    return run


@pytest.mark.asyncio
async def test_a_night_stores_every_companys_snapshots(services):
    fake, result = await services()
    assert result.organizations == 2 and result.failed_reads == 0 and result.failed_writes == 0
    own, associate = values(fake.stored[str(OWN)]), values(fake.stored[str(ASSOCIATE)])
    assert own[("2026-11-02", "ceo.receivables")] == 50
    assert own[("2026-11-01", "ceo.revenue")] == 100  # the day before, asked again
    assert own[("2026-10-01", "ceo.payroll")] == 1000  # last month's payroll
    assert own[("2026-11-02", "ceo.procurement")] == 40  # the inventory serves this company
    assert ("2026-11-02", "ceo.procurement") not in associate
    assert result.rows == len(fake.stored[str(OWN)]) + len(fake.stored[str(ASSOCIATE)])


@pytest.mark.asyncio
async def test_every_call_carries_the_internal_token_and_the_company(services):
    fake, _ = await services()
    for call in fake.calls:
        assert call.headers["x-fbos-internal-token"] == "s3cret"
        if "/internal/summaries/" in call.url.path or "/internal/reports/" in call.url.path:
            assert call.url.params["organization_id"] in {str(OWN), str(ASSOCIATE)}
            assert call.url.params["from"] == call.url.params["to"]


@pytest.mark.asyncio
async def test_a_service_that_does_not_answer_writes_nothing_for_its_figures(services):
    fake, result = await services(down={"people"})
    stored = values(fake.stored[str(OWN)])
    assert not any(code in ("ceo.headcount", "ceo.payroll") for _, code in stored)
    assert stored[("2026-11-02", "ceo.revenue")] == 100
    assert result.failed_reads == 4  # this month's and last month's people summary, for two companies
