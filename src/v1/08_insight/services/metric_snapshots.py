"""Writing and reading the CEO Command Center's daily snapshots (see services/ceo_metrics.py)."""
from collections import defaultdict
from datetime import date
from typing import Literal
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ValidationFailedError
from models.analytics import MetricDaily
from schemas.metric_snapshots import (
    SnapshotPoint,
    SnapshotSeries,
    SnapshotSeriesResponse,
    SnapshotWrite,
    SnapshotWriteResult,
)
from services.ceo_metrics import CEO_METRICS

GLOBAL = "global"
# Three years, as the live summaries allow.
MAX_PERIOD_DAYS = 3 * 366
Granularity = Literal["day", "month"]


def check_metric_codes(field: str, metric_codes: list[str]) -> None:
    unknown = sorted({code for code in metric_codes if code not in CEO_METRICS})
    if unknown:
        raise ValidationFailedError(
            [{"field": field, "code": "unknown_metric", "message": f"not a CEO snapshot metric: {', '.join(unknown)}"}]
        )


def check_period(from_date: date, to_date: date) -> None:
    if to_date < from_date:
        raise ValidationFailedError([{"field": "to", "code": "invalid_range", "message": "must be on or after 'from'"}])
    if (to_date - from_date).days >= MAX_PERIOD_DAYS:
        raise ValidationFailedError(
            [{"field": "from", "code": "invalid_range", "message": f"the period may cover at most {MAX_PERIOD_DAYS} days"}]
        )


async def write_snapshots(session: AsyncSession, payload: SnapshotWrite) -> SnapshotWriteResult:
    """Replace the given (day, metric) values of one company; asking again with the same rows changes nothing."""
    check_metric_codes("rows.metric_code", [row.metric_code for row in payload.rows])
    values = {(row.day, row.metric_code): row.value for row in payload.rows}  # a repeated pair: the last wins
    days_by_code: dict[str, set[date]] = defaultdict(set)
    for day, metric_code in values:
        days_by_code[metric_code].add(day)
    for metric_code, days in days_by_code.items():
        await session.execute(
            delete(MetricDaily).where(
                MetricDaily.organization_id == payload.organization_id,
                MetricDaily.metric_code == metric_code,
                MetricDaily.dimension_key == GLOBAL,
                MetricDaily.day.in_(days),
            )
        )
    session.add_all(
        MetricDaily(
            day=day, organization_id=payload.organization_id, metric_code=metric_code, dimension_key=GLOBAL, value=value
        )
        for (day, metric_code), value in values.items()
    )
    await session.flush()
    return SnapshotWriteResult(written=len(values))


async def read_series(
    session: AsyncSession,
    organization_id: uuid.UUID,
    metric_codes: list[str],
    from_date: date,
    to_date: date,
    granularity: Granularity,
) -> SnapshotSeriesResponse:
    check_metric_codes("metric_code", metric_codes)
    check_period(from_date, to_date)
    codes = list(dict.fromkeys(metric_codes))
    rows = (
        await session.execute(
            select(MetricDaily.metric_code, MetricDaily.day, MetricDaily.value)
            .where(
                MetricDaily.organization_id == organization_id,
                MetricDaily.metric_code.in_(codes),
                MetricDaily.dimension_key == GLOBAL,
                MetricDaily.day >= from_date,
                MetricDaily.day <= to_date,
            )
            .order_by(MetricDaily.metric_code, MetricDaily.day)
        )
    ).all()
    days_by_code: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for metric_code, day, value in rows:
        days_by_code[metric_code].append((day, float(value)))
    return SnapshotSeriesResponse(
        organization_id=organization_id,
        from_date=from_date,
        to_date=to_date,
        granularity=granularity,
        series=[
            SnapshotSeries(
                metric_code=code,
                kind=CEO_METRICS[code].kind,
                points=bucket_points(days_by_code[code], CEO_METRICS[code].kind, granularity),
            )
            for code in codes
        ],
    )


def bucket_points(days: list[tuple[date, float]], kind: str, granularity: Granularity) -> list[SnapshotPoint]:
    """`days` in date order -> one point per day or month: flows add up, stocks keep the last day."""
    buckets: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for day, value in days:
        buckets[_period_key(day, granularity)].append((day, value))
    points = []
    for period, entries in buckets.items():
        last_day, last_value = entries[-1]
        value = sum(v for _, v in entries) if kind == "flow" else last_value
        points.append(SnapshotPoint(period=period, value=round(value, 4), days=len(entries), last_day=last_day))
    return points


def _period_key(day: date, granularity: Granularity) -> str:
    return f"{day.year}-{day.month:02d}" if granularity == "month" else day.isoformat()
