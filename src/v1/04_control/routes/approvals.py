import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

import services.approvals as service
from dependencies import DatabaseSession, OrgId, UserId
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


# --- Approval requests -------------------------------------------------------


@router.post("/requests", response_model=ApprovalRequestResponse, status_code=status.HTTP_201_CREATED)
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


@router.get("/requests", response_model=PageResponse[ApprovalRequestResponse])
async def list_approval_requests(
    session: DatabaseSession,
    org_id: OrgId,
    caller_user_id: UserId,
    inbox: Optional[str] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    request_type: Optional[str] = Query(None),
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[ApprovalRequestResponse]:
    """List approval requests."""
    return await service.list_approval_requests(
        session, org_id, caller_user_id, inbox, status_, request_type, subject_type, subject_id, limit, cursor
    )


@router.get("/requests/{request_id}", response_model=ApprovalRequestResponse)
async def get_approval_request(
    request_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> ApprovalRequestResponse:
    """Get an approval request."""
    return await service.get_approval_request(session, org_id, request_id)


@router.post("/requests/{request_id}/decisions", response_model=DecisionResult)
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


@router.post("/requests/{request_id}/cancel", response_model=ApprovalRequestResponse)
async def cancel_approval_request(
    request_id: uuid.UUID,
    payload: ApprovalCancel,
    session: DatabaseSession,
    org_id: OrgId,
) -> ApprovalRequestResponse:
    """Cancel an approval request."""
    req = await service.cancel_approval_request(session, org_id, request_id, payload)
    await session.commit()
    return req


# --- Delegations -------------------------------------------------------------


@router.get("/delegations", response_model=PageResponse[DelegationResponse])
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


@router.post("/delegations", response_model=DelegationResponse, status_code=status.HTTP_201_CREATED)
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


@router.delete("/delegations/{delegation_id}", status_code=status.HTTP_204_NO_CONTENT)
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


@router.get("/policies", response_model=PageResponse[ApprovalPolicyResponse])
async def list_approval_policies(
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[ApprovalPolicyResponse]:
    """List approval policies."""
    return await service.list_approval_policies(session, org_id, limit, cursor)


@router.post("/policies", response_model=ApprovalPolicyResponse, status_code=status.HTTP_201_CREATED)
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
