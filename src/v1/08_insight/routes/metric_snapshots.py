"""
The CEO Command Center's daily snapshots: the gateway's nightly job writes them
(`PUT /internal/metric-snapshots`) and its screen reads them back per company
(`GET /metric-snapshots`) for the trend and the comparisons with an earlier day.
"""
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from dependencies import DatabaseSession, require_permission, verify_internal_caller
from exceptions import PermissionDeniedError
import permissions
from schemas.metric_snapshots import SnapshotSeriesResponse, SnapshotWrite, SnapshotWriteResult
from services import metric_snapshots
from services.ceo_metrics import CEO_METRICS
from services.identity_client import Actor

router = APIRouter(tags=["metric-snapshots"])

MAX_METRICS = len(CEO_METRICS)


@router.get("/metric-snapshots", response_model=SnapshotSeriesResponse)
async def read_metric_snapshots(
    session: DatabaseSession,
    actor: Annotated[Actor, Depends(require_permission(permissions.CEO_DASHBOARD_READ))],
    metric_code: list[str] = Query(..., max_length=MAX_METRICS, description="CEO snapshot metrics, e.g. ceo.revenue"),
    from_date: date = Query(..., alias="from", description="First day"),
    to_date: date = Query(..., alias="to", description="Last day"),
    granularity: Literal["day", "month"] = Query("day", description="One point per day or per calendar month"),
) -> SnapshotSeriesResponse:
    """One company's snapshots (the one the caller acts in). Payroll, costs, purchases, expenses
    and other income also need the dashboard's financials permission, as their cards do."""
    if any(CEO_METRICS[code].financial for code in metric_code if code in CEO_METRICS):
        if not actor.has(permissions.CEO_DASHBOARD_FINANCIALS):
            raise PermissionDeniedError(permissions.CEO_DASHBOARD_FINANCIALS)
    return await metric_snapshots.read_series(
        session, actor.organization_id, metric_code, from_date, to_date, granularity
    )


@router.put(
    "/internal/metric-snapshots",
    response_model=SnapshotWriteResult,
    tags=["internal"],
    dependencies=[Depends(verify_internal_caller)],
)
async def write_metric_snapshots(payload: SnapshotWrite, session: DatabaseSession) -> SnapshotWriteResult:
    """Store one company's snapshots (internal: the gateway's nightly job). Each (day, metric)
    replaces what was stored for it, so a night that is run again changes nothing."""
    result = await metric_snapshots.write_snapshots(session, payload)
    await session.commit()
    return result
