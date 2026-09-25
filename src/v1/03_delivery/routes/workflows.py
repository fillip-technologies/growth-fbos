import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

import services.workflows as service
from dependencies import DatabaseSession, OrgId, UserId
from schemas.common import PageResponse
from schemas.workflows import (
    AvailableTransitionResponse,
    HoldRequest,
    InstanceHistoryItemResponse,
    TransitionRequest,
    TransitionResult,
    ValidationResult,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowInstanceResponse,
    WorkflowInstanceStart,
    WorkflowVersionContent,
    WorkflowVersionResponse,
)

router = APIRouter(prefix="/workflow", tags=["workflow"])


# --- Workflow definitions & versions ----------------------------------------


@router.get("/definitions", response_model=PageResponse[WorkflowDefinitionResponse])
async def list_workflow_definitions(
    session: DatabaseSession,
    org_id: OrgId,
    subject_type: Optional[str] = Query(None),
    vertical_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[WorkflowDefinitionResponse]:
    """List workflow definitions."""
    return await service.list_workflow_definitions(session, org_id, subject_type, vertical_id, limit, cursor)


@router.post(
    "/definitions", response_model=WorkflowDefinitionResponse, status_code=status.HTTP_201_CREATED
)
async def create_workflow_definition(
    payload: WorkflowDefinitionCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WorkflowDefinitionResponse:
    """Create a workflow definition."""
    definition = await service.create_workflow_definition(session, org_id, payload)
    await session.commit()
    return definition


@router.post(
    "/definitions/{definition_code}/versions",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_version(
    definition_code: str,
    payload: WorkflowVersionContent,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WorkflowVersionResponse:
    """Create a draft version."""
    version = await service.create_workflow_version(session, org_id, definition_code, payload)
    await session.commit()
    return version


@router.put(
    "/definitions/{definition_code}/versions/{version_no}",
    response_model=WorkflowVersionResponse,
)
async def replace_workflow_version(
    definition_code: str,
    version_no: int,
    payload: WorkflowVersionContent,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowVersionResponse:
    """Replace draft version content."""
    version = await service.replace_workflow_version(session, org_id, definition_code, version_no, payload, if_match)
    await session.commit()
    return version


@router.post(
    "/definitions/{definition_code}/versions/{version_no}/validate",
    response_model=ValidationResult,
)
async def validate_workflow_version(
    definition_code: str,
    version_no: int,
    session: DatabaseSession,
    org_id: OrgId,
) -> ValidationResult:
    """Validate a version."""
    return await service.validate_workflow_version(session, org_id, definition_code, version_no)


@router.post(
    "/definitions/{definition_code}/versions/{version_no}/publish",
    response_model=WorkflowVersionResponse,
)
async def publish_workflow_version(
    definition_code: str,
    version_no: int,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowVersionResponse:
    """Publish a version."""
    version = await service.publish_workflow_version(session, org_id, definition_code, version_no, if_match)
    await session.commit()
    return version


# --- Workflow instances ------------------------------------------------------


@router.post("/instances", response_model=WorkflowInstanceResponse, status_code=status.HTTP_201_CREATED)
async def start_workflow_instance(
    payload: WorkflowInstanceStart,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WorkflowInstanceResponse:
    """Start a workflow instance."""
    instance = await service.start_workflow_instance(session, org_id, user_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{instance.version}"'
    return instance


@router.get("/instances", response_model=PageResponse[WorkflowInstanceResponse])
async def list_workflow_instances(
    session: DatabaseSession,
    org_id: OrgId,
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    definition_code: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[WorkflowInstanceResponse]:
    """List workflow instances."""
    return await service.list_workflow_instances(
        session, org_id, subject_type, subject_id, status_, definition_code, limit, cursor
    )


@router.get("/instances/{instance_id}", response_model=WorkflowInstanceResponse)
async def get_workflow_instance(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> WorkflowInstanceResponse:
    """Get a workflow instance."""
    instance = await service.get_workflow_instance(session, org_id, instance_id)
    response.headers["ETag"] = f'"{instance.version}"'
    return instance


@router.get(
    "/instances/{instance_id}/transitions", response_model=PageResponse[AvailableTransitionResponse]
)
async def list_available_transitions(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[AvailableTransitionResponse]:
    """List transitions available now."""
    return await service.list_available_transitions(session, org_id, instance_id, limit, cursor)


@router.post("/instances/{instance_id}/transitions", response_model=TransitionResult)
async def perform_transition(
    instance_id: uuid.UUID,
    payload: TransitionRequest,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TransitionResult:
    """Perform a transition."""
    result = await service.perform_transition(session, org_id, instance_id, payload, if_match)
    await session.commit()
    return result


@router.post("/instances/{instance_id}/hold", response_model=WorkflowInstanceResponse)
async def hold_instance(
    instance_id: uuid.UUID,
    payload: HoldRequest,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Put an instance on hold."""
    instance = await service.hold_instance(session, org_id, instance_id, payload, if_match)
    await session.commit()
    return instance


@router.post("/instances/{instance_id}/resume", response_model=WorkflowInstanceResponse)
async def resume_instance(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Resume an instance on hold."""
    instance = await service.resume_instance(session, org_id, instance_id, if_match)
    await session.commit()
    return instance


@router.post("/instances/{instance_id}/cancel", response_model=WorkflowInstanceResponse)
async def cancel_instance(
    instance_id: uuid.UUID,
    payload: HoldRequest,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Cancel an instance."""
    instance = await service.cancel_instance(session, org_id, instance_id, payload, if_match)
    await session.commit()
    return instance


@router.get(
    "/instances/{instance_id}/history", response_model=PageResponse[InstanceHistoryItemResponse]
)
async def get_instance_history(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[InstanceHistoryItemResponse]:
    """Get the instance timeline."""
    return await service.get_instance_history(session, org_id, instance_id, limit, cursor)
