"""Business logic for the SLA module.

SLA clock lifecycle: pending → running → paused | at_risk | breached →
met | breached_closed | cancelled.

SLA exception effects: pause (pauses the clock), extend (pushes due_at
forward by extend_minutes), excuse_breach (marks breach as excused in KPIs).
For this implementation, exceptions are stored in requested state and their
effect is applied on create since there is no async approval loop wired up
here (the approval request id is left null).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    InvalidStateTransitionError,
    SlaEscalationNotFoundError,
    SlaInstanceNotFoundError,
    ValidationFailedError,
)
from models.policy import ApprovalPolicy
from models.sla import SlaEscalation, SlaException, SlaInstance, SlaPolicy
from schemas.common import PageResponse, SubjectRef
from schemas.sla import (
    EscalationAck,
    EscalationResponse,
    SlaPolicyInput,
    SlaPolicyResponse,
    SlaPolicySummary,
    SlaExceptionCreate,
    SlaExceptionResponse,
    SlaInstanceResponse,
)
from services.pagination import paginate_by_id
from services.refs import user_ref


# --- Response builders -------------------------------------------------------


async def _to_policy_response(policy: SlaPolicy) -> SlaPolicyResponse:
    return SlaPolicyResponse(
        code=policy.code,
        name=policy.name,
        subject_type=policy.subject_type,
        metric=policy.metric,
        condition=policy.condition or {},
        priority=policy.priority,
        target_minutes=policy.target_minutes,
        calendar_mode=policy.calendar_mode,
        start_on=policy.start_on,
        stop_on=list(policy.stop_on) if policy.stop_on else [],
        pause_on=policy.pause_on,
        thresholds=list(policy.thresholds) if policy.thresholds else [],
        escalation_levels=list(policy.escalation_levels) if policy.escalation_levels else [],
        version_no=policy.version_no,
        status=policy.status,
    )


async def _to_instance_response(session: AsyncSession, instance: SlaInstance) -> SlaInstanceResponse:
    policy = await session.get(SlaPolicy, instance.policy_id)
    policy_summary = SlaPolicySummary(
        code=policy.code if policy else "",
        name=policy.name if policy else "",
        version_no=policy.version_no if policy else 0,
    )
    return SlaInstanceResponse(
        id=instance.id,
        policy=policy_summary,
        subject=SubjectRef(type=instance.subject_type, id=instance.subject_id),
        metric=instance.metric,
        state=instance.state,
        started_at=instance.started_at,
        due_at=instance.due_at,
        target_minutes=instance.target_minutes,
        paused_minutes=instance.paused_minutes,
        consumed_pct=float(instance.consumed_pct),
        elapsed_business_minutes=instance.elapsed_business_minutes,
        current_escalation_level=instance.current_escalation_level,
        breached_at=instance.breached_at,
        met_at=instance.met_at,
        pauses=list(instance.pauses) if instance.pauses else [],
    )


async def _to_escalation_response(session: AsyncSession, esc: SlaEscalation) -> EscalationResponse:
    return EscalationResponse(
        id=esc.id,
        instance_id=esc.instance_id,
        subject=SubjectRef(type=esc.subject_type, id=esc.subject_id),
        level=esc.level,
        status=esc.status,
        target=user_ref(esc.target_user_id, "Target User") if esc.target_user_id else None,
        triggered_at=esc.triggered_at,
        acknowledged_at=esc.acknowledged_at,
    )


# --- SLA policies ------------------------------------------------------------


async def list_sla_policies(
    session: AsyncSession,
    org_id: uuid.UUID,
    subject_type: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[SlaPolicyResponse]:
    query = select(SlaPolicy).where(SlaPolicy.organization_id == org_id)
    if subject_type is not None:
        query = query.where(SlaPolicy.subject_type == subject_type)
    rows, page = await paginate_by_id(session, query, SlaPolicy, limit, cursor)
    data = [await _to_policy_response(p) for p in rows]
    return PageResponse(data=data, page=page)


async def create_sla_policy(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: SlaPolicyInput,
    idempotency_key: Optional[str],
) -> SlaPolicyResponse:
    valid_metrics = {"response", "resolution", "stage_duration", "approval_turnaround"}
    if data.metric not in valid_metrics:
        raise ValidationFailedError([{"field": "metric", "code": "invalid_enum", "message": f"metric must be one of {valid_metrics}"}])

    valid_calendar_modes = {"business_hours", "calendar_24x7"}
    if data.calendar_mode not in valid_calendar_modes:
        raise ValidationFailedError([{"field": "calendar_mode", "code": "invalid_enum", "message": f"calendar_mode must be one of {valid_calendar_modes}"}])

    policy = SlaPolicy(
        organization_id=org_id,
        code=data.code,
        name=data.name,
        subject_type=data.subject_type,
        metric=data.metric,
        condition=data.condition,
        priority=data.priority,
        target_minutes=data.target_minutes,
        calendar_mode=data.calendar_mode,
        start_on=data.start_on,
        stop_on=data.stop_on,
        pause_on=data.pause_on,
        thresholds=data.thresholds,
        escalation_levels=data.escalation_levels,
        version_no=data.version_no,
        status=data.status,
    )
    session.add(policy)
    await session.flush()
    return await _to_policy_response(policy)


# --- SLA instances -----------------------------------------------------------


async def list_sla_instances(
    session: AsyncSession,
    org_id: uuid.UUID,
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    state: Optional[str],
    due_before: Optional[datetime],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[SlaInstanceResponse]:
    query = select(SlaInstance).where(SlaInstance.organization_id == org_id)
    if subject_type is not None:
        query = query.where(SlaInstance.subject_type == subject_type)
    if subject_id is not None:
        query = query.where(SlaInstance.subject_id == subject_id)
    if state is not None:
        query = query.where(SlaInstance.state == state)
    if due_before is not None:
        query = query.where(SlaInstance.due_at < due_before)
    rows, page = await paginate_by_id(session, query, SlaInstance, limit, cursor)
    data = [await _to_instance_response(session, i) for i in rows]
    return PageResponse(data=data, page=page)


async def get_sla_instance(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID
) -> SlaInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id)
    return await _to_instance_response(session, instance)


async def _get_instance(session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID) -> SlaInstance:
    res = await session.execute(
        select(SlaInstance).where(SlaInstance.id == instance_id, SlaInstance.organization_id == org_id)
    )
    instance = res.scalars().first()
    if not instance:
        raise SlaInstanceNotFoundError(str(instance_id))
    return instance


async def create_sla_exception(
    session: AsyncSession,
    org_id: uuid.UUID,
    instance_id: uuid.UUID,
    data: SlaExceptionCreate,
    idempotency_key: Optional[str],
) -> SlaExceptionResponse:
    instance = await _get_instance(session, org_id, instance_id)

    terminal_states = {"met", "breached_closed", "cancelled"}
    if instance.state in terminal_states:
        raise InvalidStateTransitionError(instance.state, "request_exception")

    if data.effect == "extend" and data.extend_minutes is None:
        raise ValidationFailedError([{"field": "extend_minutes", "code": "required", "message": "extend_minutes is required when effect is extend"}])

    exc = SlaException(
        instance_id=instance.id,
        reason_code=data.reason_code,
        description=data.description,
        effect=data.effect,
        extend_minutes=data.extend_minutes,
        evidence_document_id=data.evidence_document_id,
        status="requested",
    )
    session.add(exc)

    # Apply effect immediately (no async approval loop in this pass)
    now = datetime.now(timezone.utc)
    if data.effect == "extend" and data.extend_minutes:
        instance.due_at = instance.due_at + timedelta(minutes=data.extend_minutes)
    elif data.effect == "pause":
        instance.state = "paused"
    # excuse_breach keeps the breach but marks exception as approved
    if data.effect == "excuse_breach":
        exc.status = "approved"

    await session.flush()
    return SlaExceptionResponse(
        id=exc.id,
        instance_id=exc.instance_id,
        reason_code=exc.reason_code,
        effect=exc.effect,
        extend_minutes=exc.extend_minutes,
        status=exc.status,
        approval_request_id=exc.approval_request_id,
    )


# --- SLA escalations ---------------------------------------------------------


async def list_sla_escalations(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    target: Optional[str],
    status_filter: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[EscalationResponse]:
    query = select(SlaEscalation).join(SlaInstance, SlaEscalation.instance_id == SlaInstance.id).where(
        SlaInstance.organization_id == org_id
    )
    if target == "me":
        query = query.where(SlaEscalation.target_user_id == caller_user_id)
    if status_filter is not None:
        query = query.where(SlaEscalation.status == status_filter)
    rows, page = await paginate_by_id(session, query, SlaEscalation, limit, cursor)
    data = [await _to_escalation_response(session, e) for e in rows]
    return PageResponse(data=data, page=page)


async def acknowledge_escalation(
    session: AsyncSession,
    org_id: uuid.UUID,
    escalation_id: uuid.UUID,
    data: EscalationAck,
) -> EscalationResponse:
    res = await session.execute(
        select(SlaEscalation)
        .join(SlaInstance, SlaEscalation.instance_id == SlaInstance.id)
        .where(SlaEscalation.id == escalation_id, SlaInstance.organization_id == org_id)
    )
    esc = res.scalars().first()
    if not esc:
        raise SlaEscalationNotFoundError(str(escalation_id))

    if esc.status != "open":
        raise InvalidStateTransitionError(esc.status, "acknowledge")

    esc.status = "acknowledged"
    esc.acknowledged_at = datetime.now(timezone.utc)
    await session.flush()
    return await _to_escalation_response(session, esc)
