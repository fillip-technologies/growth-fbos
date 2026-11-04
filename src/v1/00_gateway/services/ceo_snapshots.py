"""
The nightly snapshot of the CEO Command Center (CEO plan B4).

Once a night (CEO_SNAPSHOT_ENABLED, one gateway only) every active company's totals for the day
before are written to Insight's `metric_daily`, so the screen's trend and its comparisons with an
earlier day read stored numbers instead of asking every service for a year of data.

What is written (codes and how they add up: Insight's services/ceo_metrics.py):
- what happened that day (revenue, project costs, asset costs, purchases, operating expenses,
  other income): asked again for the `CEO_SNAPSHOT_REFRESH_DAYS` days before, so an entry
  recorded late still lands on its own day;
- payroll, which belongs to a month: written on the month's 1st, for this month and the last;
- where things stood (receivables, pipeline, clients, projects, headcount, health): as of the run,
  for the day before. A position can't be read for a past day, so a missed night stays missing.

No one is signed in at night, so each service is asked through its `/internal/summaries/...`
route with the internal service token. A service that doesn't answer writes nothing for that
company and day: Insight then has no row, which the screen shows as a gap, never as zero.

Backfill what happened over past days (positions can't be backfilled):
    python -m services.ceo_snapshots --from 2026-04-01 --to 2026-11-02
"""
import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
from typing import Any, Optional
import uuid

import httpx

from config import settings
from exceptions import GatewayServiceError
from services.ceo_screen import money
from services.identity_client import IdentityClient, Organization

logger = logging.getLogger("gateway.ceo_snapshots")

SNAPSHOTS_PATH = "/api/insight/v1/internal/metric-snapshots"
# Insight's most rows per write.
SNAPSHOT_BATCH = 5000

FieldPath = tuple[str, ...]


@dataclass(frozen=True)
class SnapshotSource:
    """One service's summary and which of its figures are snapshotted."""

    name: str
    url_setting: str  # the config attribute with the service's base URL
    path: str
    flows: dict[str, FieldPath] = field(default_factory=dict)  # what happened on the day asked
    monthly_flows: dict[str, FieldPath] = field(default_factory=dict)  # a month's figure, on its 1st
    stocks: dict[str, FieldPath] = field(default_factory=dict)  # where things stood: the run's day only
    only_if: Optional[FieldPath] = None  # write nothing unless this field is true

    @property
    def base_url(self) -> str:
        return getattr(settings, self.url_setting).rstrip("/")


REVENUE = SnapshotSource(
    "revenue", "revenue_service_url", "/api/revenue/v1/internal/summaries/revenue",
    flows={"ceo.revenue": ("revenue",)},
    stocks={
        "ceo.receivables": ("receivables",),
        "ceo.overdue": ("overdue",),
        "ceo.pipeline": ("pipeline",),
        "ceo.clients": ("clients", "total"),
    },
)
DELIVERY = SnapshotSource(
    "delivery", "delivery_service_url", "/api/delivery/v1/internal/summaries/delivery",
    flows={"ceo.project_costs": ("costs",)},
    stocks={"ceo.active_work_units": ("projects", "running"), "ceo.at_risk_work_units": ("projects", "at_risk")},
)
PEOPLE = SnapshotSource(
    "people", "people_service_url", "/api/people/v1/internal/summaries/people",
    monthly_flows={"ceo.payroll": ("payroll",)},  # People counts a payroll run in its whole month
    stocks={"ceo.headcount": ("headcount",)},
)
MANAGEMENT = SnapshotSource(
    "management", "management_service_url", "/api/management/v1/internal/summaries/health",
    stocks={"ceo.health_score": ("health", "score_pct")},
    only_if=("health", "available"),  # no scorecard results that day: no score, not 0%
)
ASSETS = SnapshotSource(
    "assets", "assets_service_url", "/api/assets/v1/internal/summaries/costs",
    flows={"ceo.asset_costs": ("costs",)},
)
FINANCE = SnapshotSource(
    "finance", "finance_service_url", "/api/finance/v1/internal/summaries/finance",
    flows={"ceo.operating_expenses": ("expenses",), "ceo.other_income": ("income",)},
)
# Fixly serves one organization (INVENTORY_ORGANIZATION_ID); it is read for that company only.
INVENTORY = SnapshotSource(
    "inventory", "inventory_service_url", "/api/inventory/v1/internal/reports/summary",
    flows={"ceo.procurement": ("purchase_orders", "committed")},
)
COMPANY_SOURCES = (REVENUE, DELIVERY, PEOPLE, MANAGEMENT, ASSETS, FINANCE)


@dataclass(frozen=True)
class Read:
    """One summary to ask for: a source, for one company, on one day."""

    source: SnapshotSource
    day: date
    with_stocks: bool


@dataclass
class NightResult:
    organizations: int = 0
    rows: int = 0
    failed_reads: int = 0
    failed_writes: int = 0


# --------------------------------------------------------------------------- pure rules


def field_value(summary: dict[str, Any], path: FieldPath) -> Any:
    value: Any = summary
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def rows_for(read: Read, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """The snapshot rows one summary gives."""
    source = read.source
    if source.only_if and not field_value(summary, source.only_if):
        return []
    wanted = [(read.day, code, path) for code, path in source.flows.items()]
    wanted += [(read.day.replace(day=1), code, path) for code, path in source.monthly_flows.items()]
    if read.with_stocks:
        wanted += [(read.day, code, path) for code, path in source.stocks.items()]
    rows = []
    for day, metric_code, path in wanted:
        value = field_value(summary, path)
        if value is None:  # a service that doesn't give this figure (yet): a gap, not a zero
            continue
        rows.append({"day": day.isoformat(), "metric_code": metric_code, "value": round(money(value), 4)})
    return rows


def night_reads(sources: tuple[SnapshotSource, ...], day: date, refresh_days: int) -> list[Read]:
    """Everything one night asks for a company: the day itself in full, what happened on the days
    before it again, and last month's payroll (runs are approved after the month ends)."""
    reads = [Read(source, day, with_stocks=True) for source in sources]
    for back in range(1, refresh_days):
        reads += [Read(source, day - timedelta(days=back), with_stocks=False) for source in sources if source.flows]
    last_month = (day.replace(day=1) - timedelta(days=1)).replace(day=1)
    reads += [Read(source, last_month, with_stocks=False) for source in sources if source.monthly_flows]
    return reads


def backfill_reads(sources: tuple[SnapshotSource, ...], from_date: date, to_date: date) -> list[Read]:
    """What happened on each past day, and each month's payroll; positions can't be read back."""
    days = [from_date + timedelta(days=n) for n in range((to_date - from_date).days + 1)]
    month_starts = sorted({day.replace(day=1) for day in days})
    reads = [Read(source, day, with_stocks=False) for source in sources if source.flows for day in days]
    reads += [Read(source, month, with_stocks=False) for source in sources if source.monthly_flows for month in month_starts]
    return reads


def seconds_until(now: datetime, hour: int) -> float:
    """From `now` to the next `hour`:00 (tomorrow's when that hour has passed today)."""
    run_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    return (run_at - now).total_seconds()


# --------------------------------------------------------------------------- the job


class SnapshotJob:
    def __init__(self, http: httpx.AsyncClient, identity: IdentityClient) -> None:
        self._http = http
        self._identity = identity
        self._slots = asyncio.Semaphore(settings.ceo_max_parallel_calls)
        self._headers = {"X-FBOS-Internal-Token": settings.internal_service_token} if settings.internal_service_token else {}

    async def night(self, day: date) -> NightResult:
        """Snapshot every company for `day`. Raises GatewayServiceError when identity can't list them."""
        organizations = await self._identity.active_organizations()
        return await self._run(organizations, lambda sources: night_reads(sources, day, settings.ceo_snapshot_refresh_days))

    async def backfill(self, from_date: date, to_date: date) -> NightResult:
        organizations = await self._identity.active_organizations()
        return await self._run(organizations, lambda sources: backfill_reads(sources, from_date, to_date))

    async def _run(self, organizations: list[Organization], plan) -> NightResult:
        result = NightResult(organizations=len(organizations))
        inventory_org = _inventory_organization()
        for organization in organizations:
            sources = COMPANY_SOURCES + ((INVENTORY,) if organization.id == inventory_org else ())
            reads = plan(sources)
            summaries = await asyncio.gather(*(self._summary(organization.id, read) for read in reads))
            rows = [row for read, summary in zip(reads, summaries) if summary is not None for row in rows_for(read, summary)]
            result.failed_reads += sum(1 for summary in summaries if summary is None)
            if await self._store(organization.id, rows):
                result.rows += len(rows)
            else:
                result.failed_writes += 1
        return result

    async def _summary(self, organization_id: uuid.UUID, read: Read) -> Optional[dict[str, Any]]:
        day = read.day.isoformat()
        params = {"organization_id": str(organization_id), "from": day, "to": day}
        async with self._slots:
            try:
                response = await self._http.get(
                    f"{read.source.base_url}{read.source.path}", params=params, headers=self._headers,
                    timeout=settings.ceo_timeout_seconds,
                )
            except httpx.HTTPError as exc:
                logger.warning("%s unreachable for %s on %s: %s", read.source.name, organization_id, day, exc)
                return None
        if response.status_code != 200:
            logger.warning("%s answered %s for %s on %s", read.source.name, response.status_code, organization_id, day)
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    async def _store(self, organization_id: uuid.UUID, rows: list[dict[str, Any]]) -> bool:
        url = f"{settings.insight_service_url.rstrip('/')}{SNAPSHOTS_PATH}"
        for start in range(0, len(rows), SNAPSHOT_BATCH):
            body = {"organization_id": str(organization_id), "rows": rows[start : start + SNAPSHOT_BATCH]}
            try:
                response = await self._http.put(url, json=body, headers=self._headers, timeout=settings.ceo_timeout_seconds)
            except httpx.HTTPError as exc:
                logger.warning("Insight unreachable storing snapshots of %s: %s", organization_id, exc)
                return False
            if response.status_code != 200:
                logger.warning("Insight answered %s storing snapshots of %s: %s", response.status_code, organization_id, response.text[:300])
                return False
        return True


def _inventory_organization() -> Optional[uuid.UUID]:
    configured = settings.inventory_organization_id
    return uuid.UUID(configured) if configured else None


def identity_client(http: httpx.AsyncClient) -> IdentityClient:
    return IdentityClient(http, settings.identity_service_url, settings.internal_service_token, settings.identity_timeout_seconds)


async def run_forever(http: httpx.AsyncClient) -> None:
    """Snapshot yesterday now (a restart heals a missed night; running a day again changes nothing),
    then every night at CEO_SNAPSHOT_HOUR."""
    job = SnapshotJob(http, identity_client(http))
    done: Optional[date] = None
    while True:
        day = date.today() - timedelta(days=1)
        if done != day:
            try:
                result = await job.night(day)
            except GatewayServiceError as exc:
                logger.warning("CEO snapshots for %s not taken (identity: %s); trying again later", day, exc.detail)
                await asyncio.sleep(settings.ceo_snapshot_retry_seconds)
                continue
            done = day
            logger.info(
                "CEO snapshots for %s: %d companies, %d rows, %d reads failed, %d companies not stored",
                day, result.organizations, result.rows, result.failed_reads, result.failed_writes,
            )
        await asyncio.sleep(seconds_until(datetime.now(), settings.ceo_snapshot_hour))


async def _backfill(from_date: date, to_date: date) -> NightResult:
    async with httpx.AsyncClient() as http:
        return await SnapshotJob(http, identity_client(http)).backfill(from_date, to_date)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill the CEO Command Center's daily snapshots of what happened.")
    parser.add_argument("--from", dest="from_date", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="to_date", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    args = parser.parse_args()
    if args.to_date < args.from_date:
        parser.error("--to must be on or after --from")
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(_backfill(args.from_date, args.to_date))
    print(
        f"{result.organizations} companies, {result.rows} rows written, "
        f"{result.failed_reads} reads failed, {result.failed_writes} companies not stored"
    )


if __name__ == "__main__":
    main()
