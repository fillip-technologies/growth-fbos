import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, Query, status

import services.sla as service
from dependencies import DatabaseSession, OrgId, UserId
from schemas.common import PageResponse
from schemas.sla import (
    EscalationAck,
    EscalationResponse,
    SlaPolicyInput,
    SlaPolicyResponse,
    SlaExceptionCreate,
    SlaExceptionResponse,
    SlaInstanceResponse,
)

router = APIRouter(prefix="/sla", tags=["sla"])


# --- SLA policies ------------------------------------------------------------


@router.get("/policies", response_model=PageResponse[SlaPolicyResponse])
async def list_sla_policies(
    session: DatabaseSession,
    org_id: OrgId,
    subject_type: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[SlaPolicyResponse]:
    """List SLA policies."""
    return await service.list_sla_policies(session, org_id, subject_type, limit, cursor)


@router.post("/policies", response_model=SlaPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_sla_policy(
    payload: SlaPolicyInput,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> SlaPolicyResponse:
    """Create or version an SLA policy."""
    policy = await service.create_sla_policy(session, org_id, payload, idempotency_key)
    await session.commit()
    return policy


# --- SLA instances -----------------------------------------------------------


@router.get("/instances", response_model=PageResponse[SlaInstanceResponse])
async def list_sla_instances(
    session: DatabaseSession,
    org_id: OrgId,
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    state: Optional[str] = Query(None),
    due_before: Optional[datetime] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[SlaInstanceResponse]:
    """List SLA clocks."""
    return await service.list_sla_instances(session, org_id, subject_type, subject_id, state, due_before, limit, cursor)


@router.get("/instances/{instance_id}", response_model=SlaInstanceResponse)
async def get_sla_instance(
    instance_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> SlaInstanceResponse:
    """Get an SLA clock."""
    return await service.get_sla_instance(session, org_id, instance_id)


@router.post(
    "/instances/{instance_id}/exceptions",
    response_model=SlaExceptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_sla_exception(
    instance_id: uuid.UUID,
    payload: SlaExceptionCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> SlaExceptionResponse:
    """Request an SLA exception."""
    exc = await service.create_sla_exception(session, org_id, instance_id, payload, idempotency_key)
    await session.commit()
    return exc


# --- SLA escalations ---------------------------------------------------------


@router.get("/escalations", response_model=PageResponse[EscalationResponse])
async def list_sla_escalations(
    session: DatabaseSession,
    org_id: OrgId,
    caller_user_id: UserId,
    target: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[EscalationResponse]:
    """List escalations."""
    return await service.list_sla_escalations(session, org_id, caller_user_id, target, status_, limit, cursor)


@router.post("/escalations/{escalation_id}/acknowledge", response_model=EscalationResponse)
async def acknowledge_escalation(
    escalation_id: uuid.UUID,
    payload: EscalationAck,
    session: DatabaseSession,
    org_id: OrgId,
) -> EscalationResponse:
    """Acknowledge an escalation."""
    esc = await service.acknowledge_escalation(session, org_id, escalation_id, payload)
    await session.commit()
    return esc
