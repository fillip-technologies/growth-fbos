import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    DashboardNotFoundError,
    MetricNotFoundError,
    ReportNotFoundError,
    ReportRunNotFoundError,
    ValidationFailedError,
)
from models.analytics import Dashboard, MetricDaily, ReportDefinition, ReportRun
from schemas.analytics import (
    DashboardResponse,
    MetricPoint,
    MetricSeriesResponse,
    ReportRunCreate,
    ReportRunOutput,
    ReportRunResponse,
    WidgetResponse,
)
from schemas.audit import JobResponse


# --- Dashboard ---------------------------------------------------------------


async def get_dashboard(
    session: AsyncSession,
    org_id: uuid.UUID,
    dashboard_code: str,
    period_id: Optional[uuid.UUID],
    vertical_id: Optional[uuid.UUID],
) -> DashboardResponse:
    result = await session.execute(
        select(Dashboard).where(
            Dashboard.organization_id == org_id,
            Dashboard.code == dashboard_code,
        )
    )
    dashboard = result.scalars().first()
    if not dashboard:
        raise DashboardNotFoundError(dashboard_code)

    layout = dashboard.layout or {}
    title = layout.get("title", dashboard.code)
    raw_widgets = layout.get("widgets", [])

    widgets = [
        WidgetResponse(
            id=w.get("id", ""),
            type=w.get("type", ""),
            title=w.get("title", ""),
            metric_code=w.get("metric_code"),
            data=w.get("data"),
        )
        for w in raw_widgets
        if isinstance(w, dict)
    ]

    return DashboardResponse(
        code=dashboard.code,
        title=title,
        refreshed_at=datetime.now(timezone.utc),
        widgets=widgets,
    )


# --- Metric series ------------------------------------------------------------


async def get_metric_series(
    session: AsyncSession,
    org_id: uuid.UUID,
    metric_code: str,
    from_: date,
    to: date,
    granularity: str,
    dimension: Optional[str],
    unit_id: Optional[uuid.UUID],
) -> MetricSeriesResponse:
    query = select(MetricDaily).where(
        MetricDaily.organization_id == org_id,
        MetricDaily.metric_code == metric_code,
        MetricDaily.day >= from_,
        MetricDaily.day <= to,
    )

    if unit_id is not None:
        query = query.where(MetricDaily.dimension_key == str(unit_id))

    query = query.order_by(MetricDaily.day.asc())
    result = await session.execute(query)
    rows = list(result.scalars().all())

    if not rows and not await _metric_exists(session, org_id, metric_code):
        raise MetricNotFoundError(metric_code)

    points = _aggregate_metric_points(rows, granularity)

    return MetricSeriesResponse(
        metric_code=metric_code,
        from_=from_,
        to=to,
        granularity=granularity or "day",
        dimension=dimension,
        points=points,
    )


async def _metric_exists(session: AsyncSession, org_id: uuid.UUID, metric_code: str) -> bool:
    result = await session.execute(
        select(MetricDaily.metric_code).where(
            MetricDaily.organization_id == org_id,
            MetricDaily.metric_code == metric_code,
        ).limit(1)
    )
    return result.scalars().first() is not None


def _aggregate_metric_points(rows: list[MetricDaily], granularity: Optional[str]) -> list[MetricPoint]:
    if not rows:
        return []

    gran = granularity or "day"

    if gran == "day":
        return [
            MetricPoint(
                period=str(row.day),
                value=float(row.value),
                dimension_value=row.dimension_key if row.dimension_key != "global" else None,
            )
            for row in rows
        ]

    # Group by period bucket then average values
    buckets: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for row in rows:
        period = _period_key(row.day, gran)
        dim_val = row.dimension_key if row.dimension_key != "global" else None
        buckets[period].append((float(row.value), dim_val or ""))

    points = []
    for period in sorted(buckets):
        values = [v for v, _ in buckets[period]]
        dim_values = {d for _, d in buckets[period] if d}
        avg_value = sum(values) / len(values)
        dimension_value = next(iter(dim_values)) if len(dim_values) == 1 else None
        points.append(MetricPoint(period=period, value=avg_value, dimension_value=dimension_value))

    return points


def _period_key(day: date, granularity: str) -> str:
    if granularity == "week":
        iso = day.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if granularity == "month":
        return f"{day.year}-{day.month:02d}"
    return str(day)


# --- Reports -----------------------------------------------------------------


async def run_report(
    session: AsyncSession,
    org_id: uuid.UUID,
    report_code: str,
    payload: ReportRunCreate,
    caller_user_id: uuid.UUID,
    idempotency_key: Optional[str],
) -> JobResponse:
    valid_formats = {"pdf", "xlsx", "csv"}
    if payload.format not in valid_formats:
        raise ValidationFailedError([{"field": "format", "code": "invalid_enum", "message": "format must be pdf, xlsx or csv"}])

    report_result = await session.execute(
        select(ReportDefinition).where(
            ReportDefinition.organization_id == org_id,
            ReportDefinition.code == report_code,
        )
    )
    report = report_result.scalars().first()
    if not report:
        raise ReportNotFoundError(report_code)

    run = ReportRun(
        report_id=report.id,
        requested_by=caller_user_id,
        parameters=payload.parameters,
        status="queued",
    )
    session.add(run)
    await session.flush()

    status_url = f"/api/insight/v1/report-runs/{run.id}"
    return JobResponse(
        id=run.id,
        status=run.status,
        status_url=status_url,
        created_at=datetime.now(timezone.utc),
    )


async def get_report_run(
    session: AsyncSession,
    org_id: uuid.UUID,
    run_id: uuid.UUID,
) -> ReportRunResponse:
    result = await session.execute(
        select(ReportRun, ReportDefinition.code)
        .join(ReportDefinition, ReportRun.report_id == ReportDefinition.id)
        .where(
            ReportRun.id == run_id,
            ReportDefinition.organization_id == org_id,
        )
    )
    row = result.first()
    if not row:
        raise ReportRunNotFoundError(str(run_id))

    run, report_code = row

    output = None
    if run.output_document_id:
        output = ReportRunOutput(document_id=run.output_document_id, file_name=None)

    requested_by = None
    if run.requested_by:
        requested_by = {"id": str(run.requested_by), "name": "User"}

    return ReportRunResponse(
        id=run.id,
        report_code=report_code,
        status=run.status,
        requested_by=requested_by,
        parameters=run.parameters,
        output=output,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=None,
    )
