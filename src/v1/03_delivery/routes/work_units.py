import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.work_units as service
from dependencies import DatabaseSession, OrgId, UserId, require_permission
from schemas.common import PageResponse
from schemas.work_units import (
    ChangeRequestApprove,
    ChangeRequestCreate,
    ChangeRequestReject,
    ChangeRequestResponse,
    MemberResponse,
    MembersReplace,
    MilestoneAccept,
    MilestoneCreate,
    MilestoneReject,
    MilestoneResponse,
    MilestoneSubmit,
    MilestoneUpdate,
    ProgressResponse,
    RiskCreate,
    RiskResponse,
    RiskUpdate,
    WorkTemplateCreate,
    WorkTemplateResponse,
    WorkTemplateVersionCreate,
    WorkTemplateVersionResponse,
    WorkUnitCreate,
    WorkUnitResponse,
    WorkUnitStatusChange,
    WorkUnitSummaryResponse,
    WorkUnitTypeCreate,
    WorkUnitTypeResponse,
    WorkUnitTypeUpdate,
    WorkUnitUpdate,
)

router = APIRouter(tags=["work-units"])

CAN_READ = Depends(require_permission(permissions.WORK_UNIT_READ))
CAN_WRITE = Depends(require_permission(permissions.WORK_UNIT_WRITE))
CAN_MANAGE_TEMPLATES = Depends(require_permission(permissions.TEMPLATE_MANAGE))
CAN_DECIDE_CHANGES = Depends(require_permission(permissions.CHANGE_REQUEST_APPROVE))


# --- Work unit types & templates -------------------------------------------


@router.get("/work-unit-types", response_model=PageResponse[WorkUnitTypeResponse], dependencies=[CAN_READ])
async def list_work_unit_types(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[WorkUnitTypeResponse]:
    """List work unit types."""
    return await service.list_work_unit_types(session, org_id, limit, cursor)


@router.get("/templates", response_model=PageResponse[WorkTemplateResponse], dependencies=[CAN_READ])
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
    dependencies=[CAN_MANAGE_TEMPLATES],
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
    dependencies=[CAN_MANAGE_TEMPLATES],
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


@router.get("/work-units", response_model=PageResponse[WorkUnitResponse], dependencies=[CAN_READ])
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


@router.post("/work-units", response_model=WorkUnitResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE])
async def create_work_unit(
    payload: WorkUnitCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WorkUnitResponse:
    """Create a work unit, from a template or of a given type."""
    work_unit = await service.create_work_unit(session, org_id, user_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{work_unit.version}"'
    return work_unit


@router.get("/work-units/{work_unit_id}", response_model=WorkUnitResponse, dependencies=[CAN_READ])
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


@router.patch("/work-units/{work_unit_id}", response_model=WorkUnitResponse, dependencies=[CAN_WRITE])
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


@router.post("/work-units/{work_unit_id}/status", response_model=WorkUnitResponse, dependencies=[CAN_WRITE])
async def change_work_unit_status(
    work_unit_id: uuid.UUID,
    payload: WorkUnitStatusChange,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkUnitResponse:
    """Change a work unit's status."""
    work_unit = await service.change_work_unit_status(session, org_id, user_id, work_unit_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{work_unit.version}"'
    return work_unit


@router.get("/work-units/{work_unit_id}/summary", response_model=WorkUnitSummaryResponse, dependencies=[CAN_READ])
async def get_work_unit_summary(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> WorkUnitSummaryResponse:
    """Get the work unit dashboard summary."""
    return await service.get_work_unit_summary(session, org_id, work_unit_id)


# --- Milestones ----------------------------------------------------------


@router.get("/work-units/{work_unit_id}/milestones", response_model=PageResponse[MilestoneResponse], dependencies=[CAN_READ])
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


@router.patch("/milestones/{milestone_id}", response_model=MilestoneResponse, dependencies=[CAN_WRITE])
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


@router.post("/milestones/{milestone_id}/submit", response_model=MilestoneResponse, dependencies=[CAN_WRITE])
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


@router.post("/milestones/{milestone_id}/accept", response_model=MilestoneResponse, dependencies=[CAN_WRITE])
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


@router.post("/milestones/{milestone_id}/reject", response_model=MilestoneResponse, dependencies=[CAN_WRITE])
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
    "/work-units/{work_unit_id}/risks", response_model=RiskResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE]
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
    dependencies=[CAN_WRITE],
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


@router.post("/change-requests/{change_request_id}/submit", response_model=ChangeRequestResponse, dependencies=[CAN_WRITE])
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


@router.put("/work-units/{work_unit_id}/members", response_model=WorkUnitResponse, dependencies=[CAN_WRITE])
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


@router.get("/work-units/{work_unit_id}/progress", response_model=ProgressResponse, dependencies=[CAN_READ])
async def get_progress(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> ProgressResponse:
    """Get progress and health trend."""
    return await service.get_progress(session, org_id, work_unit_id)


# --- Setup: project types and templates ---------------------------------------


@router.post(
    "/work-unit-types", response_model=WorkUnitTypeResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_TEMPLATES],
)
async def create_work_unit_type(
    payload: WorkUnitTypeCreate, session: DatabaseSession, org_id: OrgId
) -> WorkUnitTypeResponse:
    """Add a project type of the organization's own."""
    unit_type = await service.create_work_unit_type(session, org_id, payload)
    await session.commit()
    return unit_type


@router.patch("/work-unit-types/{type_id}", response_model=WorkUnitTypeResponse, dependencies=[CAN_MANAGE_TEMPLATES])
async def update_work_unit_type(
    type_id: uuid.UUID, payload: WorkUnitTypeUpdate, session: DatabaseSession, org_id: OrgId
) -> WorkUnitTypeResponse:
    """Change one of the organization's project types (built-in types can't be changed)."""
    unit_type = await service.update_work_unit_type(session, org_id, type_id, payload)
    await session.commit()
    return unit_type


@router.post(
    "/templates", response_model=WorkTemplateResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_TEMPLATES],
)
async def create_template(payload: WorkTemplateCreate, session: DatabaseSession, org_id: OrgId) -> WorkTemplateResponse:
    """Add a project template; its content goes in versions."""
    template = await service.create_template(session, org_id, payload)
    await session.commit()
    return template


@router.get(
    "/templates/{template_code}/versions", response_model=PageResponse[WorkTemplateVersionResponse],
    dependencies=[CAN_READ],
)
async def list_template_versions(
    template_code: str,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[WorkTemplateVersionResponse]:
    """A template's versions, newest first."""
    return await service.list_template_versions(session, org_id, template_code, limit, cursor)


# --- Project parts: team, milestones, risks, change requests ---------------------


@router.get("/work-units/{work_unit_id}/members", response_model=list[MemberResponse], dependencies=[CAN_READ])
async def list_members(work_unit_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> list[MemberResponse]:
    """The work unit's team."""
    return await service.list_members(session, org_id, work_unit_id)


@router.post(
    "/work-units/{work_unit_id}/milestones", response_model=MilestoneResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_milestone(
    work_unit_id: uuid.UUID, payload: MilestoneCreate, session: DatabaseSession, org_id: OrgId
) -> MilestoneResponse:
    """Add a milestone after the existing ones."""
    milestone = await service.create_milestone(session, org_id, work_unit_id, payload)
    await session.commit()
    return milestone


@router.get("/work-units/{work_unit_id}/risks", response_model=PageResponse[RiskResponse], dependencies=[CAN_READ])
async def list_risks(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[RiskResponse]:
    """The risk register, highest score first."""
    return await service.list_risks(session, org_id, work_unit_id, limit, cursor)


@router.patch("/risks/{risk_id}", response_model=RiskResponse, dependencies=[CAN_WRITE])
async def update_risk(risk_id: uuid.UUID, payload: RiskUpdate, session: DatabaseSession, org_id: OrgId) -> RiskResponse:
    """Re-assess, re-assign or close a risk."""
    risk = await service.update_risk(session, org_id, risk_id, payload)
    await session.commit()
    return risk


@router.get(
    "/work-units/{work_unit_id}/change-requests", response_model=PageResponse[ChangeRequestResponse],
    dependencies=[CAN_READ],
)
async def list_change_requests(
    work_unit_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[ChangeRequestResponse]:
    """The work unit's change requests, by number."""
    return await service.list_change_requests(session, org_id, work_unit_id, limit, cursor)


@router.post(
    "/change-requests/{change_request_id}/approve", response_model=ChangeRequestResponse,
    dependencies=[CAN_DECIDE_CHANGES],
)
async def approve_change_request(
    change_request_id: uuid.UUID,
    payload: ChangeRequestApprove,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ChangeRequestResponse:
    """Approve a submitted change request."""
    change_request = await service.decide_change_request(
        session, org_id, user_id, change_request_id, "approved", payload.note, if_match
    )
    await session.commit()
    return change_request


@router.post(
    "/change-requests/{change_request_id}/reject", response_model=ChangeRequestResponse,
    dependencies=[CAN_DECIDE_CHANGES],
)
async def reject_change_request(
    change_request_id: uuid.UUID,
    payload: ChangeRequestReject,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ChangeRequestResponse:
    """Reject a submitted change request, with the reason."""
    change_request = await service.decide_change_request(
        session, org_id, user_id, change_request_id, "rejected", payload.reason, if_match
    )
    await session.commit()
    return change_request
