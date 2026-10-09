import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.workflow_instances as instances
import services.workflow_templates as templates
import services.workflows as service
from dependencies import CurrentActor, DatabaseSession, OrgId, People, UserId, require_permission
from schemas.common import PageResponse
from schemas.workflows import (
    ApprovalDecision,
    ApprovalRejection,
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
    WorkflowTemplateInstall,
    WorkflowTemplateResponse,
    WorkflowVersionContent,
    WorkflowVersionResponse,
    WorkflowVersionSummary,
)

router = APIRouter(prefix="/workflow", tags=["workflow"])

CAN_READ = Depends(require_permission(permissions.WORKFLOW_READ))
CAN_DESIGN = Depends(require_permission(permissions.WORKFLOW_MANAGE))
CAN_OPERATE = Depends(require_permission(permissions.WORKFLOW_OPERATE))
CAN_APPROVE = Depends(require_permission(permissions.WORKFLOW_APPROVE))


# --- Ready-made task workflows ---------------------------------------------------


@router.get("/templates", response_model=list[WorkflowTemplateResponse], dependencies=[CAN_READ])
async def list_workflow_templates(
    discipline: Optional[str] = Query(None, description="general, software, creative, operations"),
) -> list[WorkflowTemplateResponse]:
    """Ready-made workflows for tasks, each ready for a task type to follow once installed."""
    return templates.list_templates(discipline)


@router.post(
    "/templates/{template_code}/install",
    response_model=WorkflowDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_DESIGN],
)
async def install_workflow_template(
    template_code: str,
    payload: WorkflowTemplateInstall,
    session: DatabaseSession,
    org_id: OrgId,
) -> WorkflowDefinitionResponse:
    """Make the template the company's own task workflow, published as version 1."""
    definition = await templates.install_template(session, org_id, template_code, payload)
    await session.commit()
    return definition


# --- Workflow definitions & versions ----------------------------------------


@router.get("/definitions", response_model=PageResponse[WorkflowDefinitionResponse], dependencies=[CAN_READ])
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
    "/definitions", response_model=WorkflowDefinitionResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_DESIGN]
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


@router.get("/definitions/{definition_code}/versions", response_model=list[WorkflowVersionSummary], dependencies=[CAN_READ])
async def list_workflow_versions(definition_code: str, session: DatabaseSession, org_id: OrgId) -> list[WorkflowVersionSummary]:
    """A workflow's versions, newest first, and which one new instances start on."""
    return await service.list_workflow_versions(session, org_id, definition_code)


@router.get(
    "/definitions/{definition_code}/versions/{version_no}", response_model=WorkflowVersionResponse, dependencies=[CAN_READ]
)
async def get_workflow_version(
    definition_code: str, version_no: int, session: DatabaseSession, org_id: OrgId
) -> WorkflowVersionResponse:
    """One version with its stages and steps."""
    return await service.get_workflow_version(session, org_id, definition_code, version_no)


@router.post(
    "/definitions/{definition_code}/versions",
    response_model=WorkflowVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_DESIGN],
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
    dependencies=[CAN_DESIGN],
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
    dependencies=[CAN_DESIGN],
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
    dependencies=[CAN_DESIGN],
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


@router.post("/instances", response_model=WorkflowInstanceResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_OPERATE])
async def start_workflow_instance(
    payload: WorkflowInstanceStart,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> WorkflowInstanceResponse:
    """Start a workflow instance."""
    instance = await instances.start_workflow_instance(session, org_id, user_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{instance.version}"'
    return instance


@router.get("/instances", response_model=PageResponse[WorkflowInstanceResponse], dependencies=[CAN_READ])
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
    return await instances.list_workflow_instances(
        session, org_id, subject_type, subject_id, status_, definition_code, limit, cursor
    )


@router.get("/instances/{instance_id}", response_model=WorkflowInstanceResponse, dependencies=[CAN_READ])
async def get_workflow_instance(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> WorkflowInstanceResponse:
    """Get a workflow instance."""
    instance = await instances.get_workflow_instance(session, org_id, instance_id)
    response.headers["ETag"] = f'"{instance.version}"'
    return instance


@router.get(
    "/instances/{instance_id}/transitions", response_model=PageResponse[AvailableTransitionResponse], dependencies=[CAN_READ]
)
async def list_available_transitions(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[AvailableTransitionResponse]:
    """List transitions available now, and whether the caller may perform each."""
    return await instances.list_available_transitions(session, org_id, actor, instance_id, limit, cursor)


@router.post("/instances/{instance_id}/transitions", response_model=TransitionResult, dependencies=[CAN_OPERATE])
async def perform_transition(
    instance_id: uuid.UUID,
    payload: TransitionRequest,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    people: People,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TransitionResult:
    """Perform a transition (plus the transition's own permission, when it names one)."""
    result = await instances.perform_transition(session, org_id, actor, instance_id, payload, if_match, people)
    await session.commit()
    return result


@router.post("/instances/{instance_id}/hold", response_model=WorkflowInstanceResponse, dependencies=[CAN_OPERATE])
async def hold_instance(
    instance_id: uuid.UUID,
    payload: HoldRequest,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Put an instance on hold."""
    instance = await instances.hold_instance(session, org_id, instance_id, payload, if_match)
    await session.commit()
    return instance


@router.post("/instances/{instance_id}/resume", response_model=WorkflowInstanceResponse, dependencies=[CAN_OPERATE])
async def resume_instance(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Resume an instance on hold."""
    instance = await instances.resume_instance(session, org_id, instance_id, if_match)
    await session.commit()
    return instance


@router.post("/instances/{instance_id}/cancel", response_model=WorkflowInstanceResponse, dependencies=[CAN_OPERATE])
async def cancel_instance(
    instance_id: uuid.UUID,
    payload: HoldRequest,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Cancel an instance (and the task it governs, if it governs one)."""
    instance = await instances.cancel_instance(session, org_id, instance_id, payload, if_match, user_id)
    await session.commit()
    return instance


@router.get(
    "/instances/{instance_id}/history", response_model=PageResponse[InstanceHistoryItemResponse], dependencies=[CAN_READ]
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
    return await instances.get_instance_history(session, org_id, instance_id, limit, cursor)


@router.post("/instances/{instance_id}/approve", response_model=WorkflowInstanceResponse, dependencies=[CAN_APPROVE])
async def approve_step(
    instance_id: uuid.UUID,
    payload: ApprovalDecision,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    people: People,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Approve the step the instance is waiting for; the transition is taken."""
    instance = await instances.approve_step(session, org_id, user_id, instance_id, payload.note, if_match, people)
    await session.commit()
    return instance


@router.post("/instances/{instance_id}/reject", response_model=WorkflowInstanceResponse, dependencies=[CAN_APPROVE])
async def reject_step(
    instance_id: uuid.UUID,
    payload: ApprovalRejection,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> WorkflowInstanceResponse:
    """Reject the step the instance is waiting for; it stays in its stage."""
    instance = await instances.reject_step(session, org_id, user_id, instance_id, payload.reason, if_match)
    await session.commit()
    return instance
