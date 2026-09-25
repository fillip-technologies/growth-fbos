import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

import services.work_units as service
from dependencies import DatabaseSession, OrgId
from schemas.common import PageResponse
from schemas.work_units import (
    ChangeRequestCreate,
    ChangeRequestResponse,
    MembersReplace,
    MilestoneAccept,
    MilestoneReject,
    MilestoneResponse,
    MilestoneSubmit,
    MilestoneUpdate,
    ProgressResponse,
    RiskCreate,
    RiskResponse,
    WorkTemplateResponse,
    WorkTemplateVersionCreate,
    WorkTemplateVersionResponse,
    WorkUnitCreate,
    WorkUnitResponse,
    WorkUnitStatusChange,
    WorkUnitSummaryResponse,
    WorkUnitTypeResponse,
    WorkUnitUpdate,
)

router = APIRouter(tags=["work-units"])


# --- Work unit types & templates -------------------------------------------


@router.get("/work-unit-types", response_model=PageResponse[WorkUnitTypeResponse])
async def list_work_unit_types(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[WorkUnitTypeResponse]:
    """List work unit types."""
    return await service.list_work_unit_types(session, org_id, limit, cursor)


@router.get("/templates", response_model=PageResponse[WorkTemplateResponse])
async def list_templates(
    session: DatabaseSession,
    org_id: OrgId,
    vertical_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[WorkTemplateResponse]:
    """List work templates."""
    return await service.list_templates(session, org_id, vertical_id, status_, limit, cursor)


@router.post(
    "/templates/{template_code}/versions",
    response_model=WorkTemplateVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template_version(
    template_code: str,
    payload: WorkTemplateVersionCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WorkTemplateVersionResponse:
    """Create a draft template version."""
    version = await service.create_template_version(session, org_id, template_code, payload)
    await session.commit()
    return version


@router.post(
    "/templates/{template_code}/versions/{version_no}/publish",
    response_model=WorkTemplateVersionResponse,
)
async def publish_template_version(
    template_code: str,
    version_no: int,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkTemplateVersionResponse:
    """Publish a template version."""
    version = await service.publish_template_version(session, org_id, template_code, version_no, if_match)
    await session.commit()
    return version


# --- Work units --------------------------------------------------------


@router.get("/work-units", response_model=PageResponse[WorkUnitResponse])
async def list_work_units(
    session: DatabaseSession,
    org_id: OrgId,
    status_: Optional[str] = Query(None, alias="status"),
    owning_unit_id: Optional[uuid.UUID] = Query(None),
    vertical_id: Optional[uuid.UUID] = Query(None),
    client_id: Optional[uuid.UUID] = Query(None),
    manager_user_id: Optional[uuid.UUID] = Query(None),
    health: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[WorkUnitResponse]:
    """List work units."""
    return await service.list_work_units(
        session, org_id, status_, owning_unit_id, vertical_id, client_id, manager_user_id, health, q, limit, cursor
    )


@router.post("/work-units", response_model=WorkUnitResponse, status_code=status.HTTP_201_CREATED)
async def create_work_unit(
    payload: WorkUnitCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WorkUnitResponse:
    """Create a work unit from a template."""
    work_unit = await service.create_work_unit(session, org_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{work_unit.version}"'
    return work_unit


@router.get("/work-units/{work_unit_id}", response_model=WorkUnitResponse)
async def get_work_unit(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> WorkUnitResponse:
    """Get a work unit."""
    work_unit = await service.get_work_unit(session, org_id, work_unit_id)
    response.headers["ETag"] = f'"{work_unit.version}"'
    return work_unit


@router.patch("/work-units/{work_unit_id}", response_model=WorkUnitResponse)
async def update_work_unit(
    work_unit_id: uuid.UUID,
    payload: WorkUnitUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkUnitResponse:
    """Update a work unit."""
    work_unit = await service.update_work_unit(session, org_id, work_unit_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{work_unit.version}"'
    return work_unit


@router.post("/work-units/{work_unit_id}/status", response_model=WorkUnitResponse)
async def change_work_unit_status(
    work_unit_id: uuid.UUID,
    payload: WorkUnitStatusChange,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkUnitResponse:
    """Change a work unit's status."""
    work_unit = await service.change_work_unit_status(session, org_id, work_unit_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{work_unit.version}"'
    return work_unit


@router.get("/work-units/{work_unit_id}/summary", response_model=WorkUnitSummaryResponse)
async def get_work_unit_summary(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> WorkUnitSummaryResponse:
    """Get the work unit dashboard summary."""
    return await service.get_work_unit_summary(session, org_id, work_unit_id)


# --- Milestones ----------------------------------------------------------


@router.get("/work-units/{work_unit_id}/milestones", response_model=PageResponse[MilestoneResponse])
async def list_milestones(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[MilestoneResponse]:
    """List milestones."""
    return await service.list_milestones(session, org_id, work_unit_id, limit, cursor)


@router.patch("/milestones/{milestone_id}", response_model=MilestoneResponse)
async def update_milestone(
    milestone_id: uuid.UUID,
    payload: MilestoneUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> MilestoneResponse:
    """Update milestone dates."""
    milestone = await service.update_milestone(session, org_id, milestone_id, payload, if_match)
    await session.commit()
    return milestone


@router.post("/milestones/{milestone_id}/submit", response_model=MilestoneResponse)
async def submit_milestone(
    milestone_id: uuid.UUID,
    payload: MilestoneSubmit,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> MilestoneResponse:
    """Submit a milestone for client acceptance."""
    milestone = await service.submit_milestone(session, org_id, milestone_id, payload, if_match)
    await session.commit()
    return milestone


@router.post("/milestones/{milestone_id}/accept", response_model=MilestoneResponse)
async def accept_milestone(
    milestone_id: uuid.UUID,
    payload: MilestoneAccept,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> MilestoneResponse:
    """Record milestone acceptance."""
    milestone = await service.accept_milestone(session, org_id, milestone_id, payload, if_match)
    await session.commit()
    return milestone


@router.post("/milestones/{milestone_id}/reject", response_model=MilestoneResponse)
async def reject_milestone(
    milestone_id: uuid.UUID,
    payload: MilestoneReject,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> MilestoneResponse:
    """Record milestone rejection."""
    milestone = await service.reject_milestone(session, org_id, milestone_id, payload, if_match)
    await session.commit()
    return milestone


# --- Risks & change requests ------------------------------------------------


@router.post(
    "/work-units/{work_unit_id}/risks", response_model=RiskResponse, status_code=status.HTTP_201_CREATED
)
async def create_risk(
    work_unit_id: uuid.UUID,
    payload: RiskCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> RiskResponse:
    """Register a risk."""
    risk = await service.create_risk(session, org_id, work_unit_id, payload)
    await session.commit()
    return risk


@router.post(
    "/work-units/{work_unit_id}/change-requests",
    response_model=ChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_change_request(
    work_unit_id: uuid.UUID,
    payload: ChangeRequestCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ChangeRequestResponse:
    """Create a change request."""
    change_request = await service.create_change_request(session, org_id, work_unit_id, payload)
    await session.commit()
    return change_request


@router.post("/change-requests/{change_request_id}/submit", response_model=ChangeRequestResponse)
async def submit_change_request(
    change_request_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ChangeRequestResponse:
    """Submit a change request for approval."""
    change_request = await service.submit_change_request(session, org_id, change_request_id, if_match)
    await session.commit()
    return change_request


# --- Members & progress ------------------------------------------------------


@router.put("/work-units/{work_unit_id}/members", response_model=WorkUnitResponse)
async def replace_members(
    work_unit_id: uuid.UUID,
    payload: MembersReplace,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkUnitResponse:
    """Replace the work unit team."""
    work_unit = await service.replace_members(session, org_id, work_unit_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{work_unit.version}"'
    return work_unit


@router.get("/work-units/{work_unit_id}/progress", response_model=ProgressResponse)
async def get_progress(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> ProgressResponse:
    """Get progress and health trend."""
    return await service.get_progress(session, org_id, work_unit_id)
