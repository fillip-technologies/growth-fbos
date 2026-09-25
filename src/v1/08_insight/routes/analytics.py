import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Header, Query, status

import services.analytics as service
from dependencies import DatabaseSession, OrgId, UserId
from schemas.analytics import (
    DashboardResponse,
    MetricSeriesResponse,
    ReportRunCreate,
    ReportRunResponse,
)
from schemas.audit import JobResponse

router = APIRouter(tags=["analytics"])


@router.get("/dashboards/{dashboard_code}", response_model=DashboardResponse)
async def get_dashboard(
    dashboard_code: str,
    session: DatabaseSession,
    org_id: OrgId,
    period_id: Optional[uuid.UUID] = Query(None),
    vertical_id: Optional[uuid.UUID] = Query(None),
) -> DashboardResponse:
    """Get a dashboard."""
    return await service.get_dashboard(session, org_id, dashboard_code, period_id, vertical_id)


@router.get("/metrics/{metric_code}", response_model=MetricSeriesResponse)
async def get_metric_series(
    metric_code: str,
    session: DatabaseSession,
    org_id: OrgId,
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
    granularity: Optional[str] = Query(None),
    dimension: Optional[str] = Query(None),
    unit_id: Optional[uuid.UUID] = Query(None),
) -> MetricSeriesResponse:
    """Get a metric time series."""
    return await service.get_metric_series(
        session, org_id, metric_code, from_, to, granularity, dimension, unit_id
    )


@router.post(
    "/reports/{report_code}/runs",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_report(
    report_code: str,
    payload: ReportRunCreate,
    session: DatabaseSession,
    org_id: OrgId,
    caller_user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> JobResponse:
    """Run a report asynchronously."""
    job = await service.run_report(session, org_id, report_code, payload, caller_user_id, idempotency_key)
    await session.commit()
    return job


@router.get("/report-runs/{run_id}", response_model=ReportRunResponse)
async def get_report_run(
    run_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> ReportRunResponse:
    """Get a report run."""
    return await service.get_report_run(session, org_id, run_id)
