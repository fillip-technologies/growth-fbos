"""Business logic for the Approvals module.

Approval request lifecycle:
  pending → in_progress (first step activated) → approved | rejected |
  revision_required | cancelled | expired

Policy matching: selects the highest-priority active policy whose
subject_type and request_type match; condition evaluation (JSON Logic) is
stored verbatim but not evaluated here — the highest-priority policy whose
type fields match is always applied. A production implementation would
evaluate condition against context using a JSON Logic library.

Decision quorum: "any" means first decision determines step outcome;
"all" means every assignee must decide the same way. For this pass, any
decision from a valid assignee completes the step immediately.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AlreadyDecidedError,
    ApprovalRequestNotFoundError,
    CommentRequiredError,
    DelegationNotFoundError,
    DelegationOverlapError,
    DuplicateOpenRequestError,
    InvalidStateTransitionError,
    NoApprovalPolicyError,
    NotAnApproverError,
    SelfApprovalNotAllowedError,
    StepNotActiveError,
)
from models.decision import ApprovalDecision, ApprovalDelegation
from models.policy import ApprovalPolicy, ApprovalPolicyStep
from models.request import ApprovalRequest, ApprovalStep, ApprovalStepAssignee
from schemas.approvals import (
    ApprovalCancel,
    ApprovalPolicyInput,
    ApprovalPolicyResponse,
    ApprovalPolicyStepResponse,
    ApprovalRequestCreate,
    ApprovalRequestResponse,
    ApprovalStepResponse,
    DecisionCreate,
    DecisionResult,
    DelegationCreate,
    DelegationResponse,
    PolicyRef,
    StepAssigneeResponse,
)
from schemas.common import PageMeta, PageResponse, SubjectRef
from services.pagination import paginate_by_id
from services.refs import user_ref

_OPEN_STATUSES = {"pending", "in_progress"}
_TERMINAL_STATUSES = {"approved", "rejected", "revision_required", "cancelled", "expired"}


# --- Response builders -------------------------------------------------------


async def _to_request_response(session: AsyncSession, req: ApprovalRequest) -> ApprovalRequestResponse:
    policy = await session.get(ApprovalPolicy, req.policy_id)
    policy_ref = PolicyRef(code=policy.code if policy else "", version_no=req.policy_version)

    steps_res = await session.execute(
        select(ApprovalStep).where(ApprovalStep.request_id == req.id).order_by(ApprovalStep.seq)
    )
    steps = list(steps_res.scalars().all())

    steps_out = []
    for step in steps:
        assignees_res = await session.execute(
            select(ApprovalStepAssignee).where(ApprovalStepAssignee.step_id == step.id)
        )
        assignees = list(assignees_res.scalars().all())
        steps_out.append(
            ApprovalStepResponse(
                seq=step.seq,
                name=step.name,
                mode=step.mode,
                quorum=step.quorum,
                status=step.status,
                assignees=[
                    StepAssigneeResponse(
                        user=user_ref(a.approver_user_id, "Approver"),
                        status=a.status,
                        delegated_from=user_ref(a.delegated_from_user_id, "Delegator")
                        if a.delegated_from_user_id
                        else None,
                        acted_at=a.acted_at,
                    )
                    for a in assignees
                ],
            )
        )

    return ApprovalRequestResponse(
        id=req.id,
        subject=SubjectRef(type=req.subject_type, id=req.subject_id),
        subject_version=req.subject_version,
        request_type=req.request_type,
        title=req.title,
        status=req.status,
        requested_by=user_ref(req.requested_by, "Requester"),
        reason=req.reason,
        priority=req.priority,
        context=req.context or {},
        policy=policy_ref,
        steps=steps_out,
        created_at=req.created_at,
        decided_at=req.decided_at,
    )


# --- Approval requests -------------------------------------------------------


async def create_approval_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ApprovalRequestCreate,
    idempotency_key: Optional[str],
) -> ApprovalRequestResponse:
    # Idempotency: return existing request if same key
    if idempotency_key:
        existing_res = await session.execute(
            select(ApprovalRequest).where(ApprovalRequest.idempotency_key == idempotency_key)
        )
        existing = existing_res.scalars().first()
        if existing:
            return await _to_request_response(session, existing)

    # Check for duplicate open request
    dup_res = await session.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.organization_id == org_id,
            ApprovalRequest.subject_type == data.subject.type,
            ApprovalRequest.subject_id == data.subject.id,
            ApprovalRequest.request_type == data.request_type,
            ApprovalRequest.status.in_(_OPEN_STATUSES),
        )
    )
    if dup_res.scalars().first():
        raise DuplicateOpenRequestError()

    # Find highest-priority matching policy
    policy_res = await session.execute(
        select(ApprovalPolicy).where(
            ApprovalPolicy.organization_id == org_id,
            ApprovalPolicy.subject_type == data.subject.type,
            ApprovalPolicy.request_type == data.request_type,
            ApprovalPolicy.status == "active",
        ).order_by(ApprovalPolicy.priority.desc())
    )
    policy = policy_res.scalars().first()
    if not policy:
        raise NoApprovalPolicyError()

    request_id = data.id if data.id else uuid.uuid4()
    req = ApprovalRequest(
        id=request_id,
        organization_id=org_id,
        policy_id=policy.id,
        subject_type=data.subject.type,
        subject_id=data.subject.id,
        subject_version=data.subject_version,
        request_type=data.request_type,
        title=data.title,
        context=data.context,
        requested_by=user_id,
        reason=data.reason,
        priority=data.priority,
        policy_version=policy.version_no,
        idempotency_key=idempotency_key,
        status="in_progress",
    )
    session.add(req)
    await session.flush()

    # Copy steps from policy and activate step 1
    policy_steps_res = await session.execute(
        select(ApprovalPolicyStep).where(ApprovalPolicyStep.policy_id == policy.id).order_by(ApprovalPolicyStep.seq)
    )
    policy_steps = list(policy_steps_res.scalars().all())

    for i, ps in enumerate(policy_steps):
        step_status = "active" if i == 0 else "pending"
        step = ApprovalStep(
            request_id=req.id,
            seq=ps.seq,
            name=ps.name,
            mode=ps.mode,
            quorum=ps.quorum,
            min_approvals=ps.min_approvals,
            status=step_status,
            activated_at=datetime.now(timezone.utc) if i == 0 else None,
        )
        session.add(step)
        await session.flush()

        # Add a single stub assignee from the selector (placeholder — real impl resolves via identity service)
        if i == 0:
            session.add(
                ApprovalStepAssignee(
                    step_id=step.id,
                    approver_user_id=user_id,
                    resolved_from="rule",
                    status="pending",
                )
            )

    await session.flush()
    return await _to_request_response(session, req)


async def list_approval_requests(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    inbox: Optional[str],
    status_filter: Optional[str],
    request_type: Optional[str],
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[ApprovalRequestResponse]:
    query = select(ApprovalRequest).where(ApprovalRequest.organization_id == org_id)

    if status_filter is not None:
        query = query.where(ApprovalRequest.status == status_filter)
    if request_type is not None:
        query = query.where(ApprovalRequest.request_type == request_type)
    if subject_type is not None:
        query = query.where(ApprovalRequest.subject_type == subject_type)
    if subject_id is not None:
        query = query.where(ApprovalRequest.subject_id == subject_id)
    if inbox == "requested_by_me":
        query = query.where(ApprovalRequest.requested_by == caller_user_id)

    rows, page = await paginate_by_id(session, query, ApprovalRequest, limit, cursor)
    data = [await _to_request_response(session, r) for r in rows]
    return PageResponse(data=data, page=page)


async def get_approval_request(
    session: AsyncSession, org_id: uuid.UUID, request_id: uuid.UUID
) -> ApprovalRequestResponse:
    req = await _get_request(session, org_id, request_id)
    return await _to_request_response(session, req)


async def _get_request(session: AsyncSession, org_id: uuid.UUID, request_id: uuid.UUID) -> ApprovalRequest:
    res = await session.execute(
        select(ApprovalRequest).where(ApprovalRequest.id == request_id, ApprovalRequest.organization_id == org_id)
    )
    req = res.scalars().first()
    if not req:
        raise ApprovalRequestNotFoundError(str(request_id))
    return req


async def make_decision(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    request_id: uuid.UUID,
    data: DecisionCreate,
    idempotency_key: Optional[str],
) -> DecisionResult:
    if data.decision in ("reject", "request_revision") and not data.comment:
        raise CommentRequiredError()

    req = await _get_request(session, org_id, request_id)

    # Find active step
    active_step_res = await session.execute(
        select(ApprovalStep).where(ApprovalStep.request_id == req.id, ApprovalStep.status == "active")
    )
    active_step = active_step_res.scalars().first()
    if not active_step:
        raise StepNotActiveError()

    # Caller must be self-approval check
    if caller_user_id == req.requested_by:
        raise SelfApprovalNotAllowedError()

    # Find assignee record for caller
    assignee_res = await session.execute(
        select(ApprovalStepAssignee).where(
            ApprovalStepAssignee.step_id == active_step.id,
            ApprovalStepAssignee.approver_user_id == caller_user_id,
            ApprovalStepAssignee.status == "pending",
        )
    )
    assignee = assignee_res.scalars().first()
    if not assignee:
        raise NotAnApproverError()

    # Check if already decided
    already_res = await session.execute(
        select(ApprovalDecision).where(
            ApprovalDecision.step_id == active_step.id,
            ApprovalDecision.actor_user_id == caller_user_id,
        )
    )
    if already_res.scalars().first():
        raise AlreadyDecidedError()

    now = datetime.now(timezone.utc)

    # Record decision
    session.add(
        ApprovalDecision(
            request_id=req.id,
            step_id=active_step.id,
            assignee_id=assignee.id,
            actor_user_id=caller_user_id,
            decision=data.decision,
            comment=data.comment,
            acted_at=now,
        )
    )

    assignee.status = data.decision
    assignee.acted_at = now

    step_completed = True
    request_completed = False

    if data.decision == "approve":
        active_step.status = "approved"
        active_step.completed_at = now

        # Activate next pending step, or mark request approved
        next_step_res = await session.execute(
            select(ApprovalStep).where(
                ApprovalStep.request_id == req.id, ApprovalStep.status == "pending"
            ).order_by(ApprovalStep.seq)
        )
        next_step = next_step_res.scalars().first()
        if next_step:
            next_step.status = "active"
            next_step.activated_at = now
        else:
            req.status = "approved"
            req.decided_at = now
            request_completed = True

    elif data.decision == "reject":
        active_step.status = "rejected"
        active_step.completed_at = now
        req.status = "rejected"
        req.decided_at = now
        request_completed = True

    else:  # request_revision
        active_step.status = "revision_required"
        active_step.completed_at = now
        req.status = "revision_required"
        req.decided_at = now
        request_completed = True

    await session.flush()
    return DecisionResult(
        request=await _to_request_response(session, req),
        step_completed=step_completed,
        request_completed=request_completed,
    )


async def cancel_approval_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    request_id: uuid.UUID,
    data: ApprovalCancel,
) -> ApprovalRequestResponse:
    req = await _get_request(session, org_id, request_id)
    if req.status not in _OPEN_STATUSES:
        raise InvalidStateTransitionError(req.status, "cancel")

    req.status = "cancelled"
    req.decided_at = datetime.now(timezone.utc)
    await session.flush()
    return await _to_request_response(session, req)


# --- Delegations -------------------------------------------------------------


def _parse_request_types(raw: str) -> list[str]:
    if raw == "*" or not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


async def _to_delegation_response(session: AsyncSession, delegation: ApprovalDelegation) -> DelegationResponse:
    return DelegationResponse(
        id=delegation.id,
        from_user=user_ref(delegation.from_user_id, "Delegator"),
        to_user=user_ref(delegation.to_user_id, "Delegate"),
        request_types=_parse_request_types(delegation.request_types),
        valid_from=delegation.valid_from,
        valid_to=delegation.valid_to,
        reason=delegation.reason,
    )


async def list_delegations(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
) -> PageResponse[DelegationResponse]:
    query = select(ApprovalDelegation).where(
        ApprovalDelegation.organization_id == org_id,
        ApprovalDelegation.from_user_id == caller_user_id,
    )
    rows, page = await paginate_by_id(session, query, ApprovalDelegation, limit, cursor)
    data = [await _to_delegation_response(session, d) for d in rows]
    return PageResponse(data=data, page=page)


async def create_delegation(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    data: DelegationCreate,
    idempotency_key: Optional[str],
) -> DelegationResponse:
    # Check for overlapping delegation from same user
    overlap_res = await session.execute(
        select(ApprovalDelegation).where(
            ApprovalDelegation.organization_id == org_id,
            ApprovalDelegation.from_user_id == caller_user_id,
            ApprovalDelegation.valid_from < data.valid_to,
            ApprovalDelegation.valid_to > data.valid_from,
        )
    )
    if overlap_res.scalars().first():
        raise DelegationOverlapError()

    if data.request_types is not None:
        raw_types = ",".join(data.request_types)
    else:
        raw_types = "*"

    delegation = ApprovalDelegation(
        organization_id=org_id,
        from_user_id=caller_user_id,
        to_user_id=data.to_user_id,
        request_types=raw_types,
        valid_from=data.valid_from,
        valid_to=data.valid_to,
        reason=data.reason,
        created_by=caller_user_id,
    )
    session.add(delegation)
    await session.flush()
    return await _to_delegation_response(session, delegation)


async def end_delegation(
    session: AsyncSession,
    org_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    delegation_id: uuid.UUID,
) -> None:
    res = await session.execute(
        select(ApprovalDelegation).where(
            ApprovalDelegation.id == delegation_id,
            ApprovalDelegation.organization_id == org_id,
            ApprovalDelegation.from_user_id == caller_user_id,
        )
    )
    delegation = res.scalars().first()
    if not delegation:
        raise DelegationNotFoundError(str(delegation_id))
    await session.delete(delegation)
    await session.flush()


# --- Approval policies -------------------------------------------------------


async def _to_policy_response(session: AsyncSession, policy: ApprovalPolicy) -> ApprovalPolicyResponse:
    steps_res = await session.execute(
        select(ApprovalPolicyStep).where(ApprovalPolicyStep.policy_id == policy.id).order_by(ApprovalPolicyStep.seq)
    )
    steps = list(steps_res.scalars().all())
    return ApprovalPolicyResponse(
        code=policy.code,
        name=policy.name,
        subject_type=policy.subject_type,
        request_type=policy.request_type,
        condition=policy.condition or {},
        priority=policy.priority,
        steps=[
            ApprovalPolicyStepResponse(
                seq=s.seq,
                name=s.name,
                mode=s.mode,
                approver_selector=s.approver_selector or {},
                quorum=s.quorum,
                skip_condition=s.skip_condition,
            )
            for s in steps
        ],
        version_no=policy.version_no,
        status=policy.status,
    )


async def list_approval_policies(
    session: AsyncSession,
    org_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
) -> PageResponse[ApprovalPolicyResponse]:
    query = select(ApprovalPolicy).where(ApprovalPolicy.organization_id == org_id)
    rows, page = await paginate_by_id(session, query, ApprovalPolicy, limit, cursor)
    data = [await _to_policy_response(session, p) for p in rows]
    return PageResponse(data=data, page=page)


async def create_approval_policy(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: ApprovalPolicyInput,
    idempotency_key: Optional[str],
) -> ApprovalPolicyResponse:
    policy = ApprovalPolicy(
        organization_id=org_id,
        code=data.code,
        name=data.name,
        subject_type=data.subject_type,
        request_type=data.request_type,
        condition=data.condition,
        priority=data.priority,
        version_no=data.version_no,
        status=data.status,
    )
    session.add(policy)
    await session.flush()

    for step_input in data.steps:
        session.add(
            ApprovalPolicyStep(
                policy_id=policy.id,
                seq=step_input.seq,
                name=step_input.name,
                mode=step_input.mode,
                approver_selector=step_input.approver_selector,
                quorum=step_input.quorum,
                min_approvals=step_input.min_approvals,
                skip_condition=step_input.skip_condition,
                allow_delegation=step_input.allow_delegation,
            )
        )
    await session.flush()
    return await _to_policy_response(session, policy)
