import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

import permissions
import services.approvals as service
from dependencies import CurrentActor, DatabaseSession, OrgId, UserId, require_permission
from schemas.approvals import (
    ApprovalCancel,
    ApprovalPolicyInput,
    ApprovalPolicyResponse,
    ApprovalRequestCreate,
    ApprovalRequestResponse,
    DecisionCreate,
    DecisionResult,
    DelegationCreate,
    DelegationResponse,
)
from schemas.common import PageResponse

router = APIRouter(prefix="/approvals", tags=["approvals"])

CAN_READ = Depends(require_permission(permissions.APPROVAL_READ))
CAN_WRITE = Depends(require_permission(permissions.APPROVAL_WRITE))
CAN_MANAGE = Depends(require_permission(permissions.APPROVAL_MANAGE))


async def _request_in_view(request_id: uuid.UUID, actor: CurrentActor, session: DatabaseSession) -> None:
    """Someone who may see only their own approval requests gets "not found" for anyone else's."""
    if actor.only_own(permissions.APPROVAL_READ):
        await service.ensure_own_request(session, actor.organization_id, request_id, actor.user_id)


# On every /requests/{request_id} route, after the permission check.
IN_VIEW = Depends(_request_in_view)


# --- Approval requests -------------------------------------------------------


@router.post("/requests", response_model=ApprovalRequestResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE])
async def create_approval_request(
    payload: ApprovalRequestCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ApprovalRequestResponse:
    """Create an approval request."""
    req = await service.create_approval_request(session, org_id, user_id, payload, idempotency_key)
    await session.commit()
    return req


@router.get("/requests", response_model=PageResponse[ApprovalRequestResponse], dependencies=[CAN_READ])
async def list_approval_requests(
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    inbox: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    request_type: Optional[str] = Query(None),
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[ApprovalRequestResponse]:
    """List approval requests: only the caller's own when they may see no others."""
    return await service.list_approval_requests(
        session, org_id, actor.user_id, inbox, status_, request_type, subject_type, subject_id, limit, cursor,
        own_records_of=actor.user_id if actor.only_own(permissions.APPROVAL_READ) else None,
    )


@router.get("/requests/{request_id}", response_model=ApprovalRequestResponse, dependencies=[CAN_READ, IN_VIEW])
async def get_approval_request(
    request_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> ApprovalRequestResponse:
    """Get an approval request."""
    return await service.get_approval_request(session, org_id, request_id)


@router.post("/requests/{request_id}/decisions", response_model=DecisionResult, dependencies=[CAN_READ, IN_VIEW])
async def make_decision(
    request_id: uuid.UUID,
    payload: DecisionCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> DecisionResult:
    """Approve, reject or request revision."""
    result = await service.make_decision(session, org_id, user_id, request_id, payload, idempotency_key)
    await session.commit()
    return result


@router.post("/requests/{request_id}/cancel", response_model=ApprovalRequestResponse, dependencies=[CAN_WRITE, IN_VIEW])
async def cancel_approval_request(
    request_id: uuid.UUID,
    payload: ApprovalCancel,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
) -> ApprovalRequestResponse:
    """Cancel an approval request: whoever raised it, or someone who manages approvals."""
    req = await service.cancel_approval_request(session, org_id, actor, request_id, payload)
    await session.commit()
    return req


# --- Delegations -------------------------------------------------------------


@router.get("/delegations", response_model=PageResponse[DelegationResponse], dependencies=[CAN_READ])
async def list_delegations(
    session: DatabaseSession,
    org_id: OrgId,
    caller_user_id: UserId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[DelegationResponse]:
    """List my delegations."""
    return await service.list_delegations(session, org_id, caller_user_id, limit, cursor)


@router.post("/delegations", response_model=DelegationResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_READ])
async def create_delegation(
    payload: DelegationCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> DelegationResponse:
    """Delegate my approvals."""
    delegation = await service.create_delegation(session, org_id, user_id, payload, idempotency_key)
    await session.commit()
    return delegation


@router.delete("/delegations/{delegation_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_READ])
async def end_delegation(
    delegation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
) -> None:
    """End a delegation."""
    await service.end_delegation(session, org_id, user_id, delegation_id)
    await session.commit()


# --- Approval policies -------------------------------------------------------


@router.get("/policies", response_model=PageResponse[ApprovalPolicyResponse], dependencies=[CAN_READ])
async def list_approval_policies(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[ApprovalPolicyResponse]:
    """List approval policies."""
    return await service.list_approval_policies(session, org_id, limit, cursor)


@router.post("/policies", response_model=ApprovalPolicyResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_approval_policy(
    payload: ApprovalPolicyInput,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ApprovalPolicyResponse:
    """Create or version an approval policy."""
    policy = await service.create_approval_policy(session, org_id, payload, idempotency_key)
    await session.commit()
    return policy
