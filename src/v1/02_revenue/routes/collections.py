import uuid
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, Query, status

from dependencies import DatabaseSession, OrgId, UserId, require_permission
from schemas.collection import (
    CollectionCaseResponse,
    CollectionFollowUpCreate,
    CollectionFollowUpResponse,
    CollectionRefreshResult,
)
from schemas.common import PageResponse
from services.collection_service import CollectionService

router = APIRouter(prefix="/collection-cases", tags=["collections"])

CAN_READ = Depends(require_permission("revenue.collection.read"))
CAN_WRITE = Depends(require_permission("revenue.collection.write"))


@router.get(
    "", response_model=PageResponse[CollectionCaseResponse],
    dependencies=[CAN_READ],
)
async def list_collection_cases(
    session: DatabaseSession,
    org_id: OrgId,
    status: Optional[str] = Query(None, description="Filter by status: open, promised, escalated, resolved, written_off"),
    owner_user_id: Optional[uuid.UUID] = Query(None, description="Filter by collection case owner"),
    client_id: Optional[uuid.UUID] = Query(None, description="Filter by client id"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[CollectionCaseResponse]:
    """List collection cases for overdue invoices with keyset pagination."""
    return await CollectionService.list_collection_cases(
        session=session,
        org_id=org_id,
        status=status,
        owner_user_id=owner_user_id,
        client_id=client_id,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/{case_id}/follow-ups", response_model=CollectionCaseResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def log_collection_follow_up(
    case_id: uuid.UUID,
    payload: CollectionFollowUpCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> CollectionCaseResponse:
    """Log a collection follow-up touchpoint and update case status."""
    case = await CollectionService.log_collection_follow_up(
        session=session,
        case_id=case_id,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
    )
    await session.commit()
    return case


@router.get(
    "/{case_id}/follow-ups",
    response_model=List[CollectionFollowUpResponse],
    dependencies=[CAN_READ],
)
async def list_follow_ups(case_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> List[CollectionFollowUpResponse]:
    """The case's follow-ups, newest first."""
    return await CollectionService.list_follow_ups(session=session, case_id=case_id, org_id=org_id)


@router.post(
    "/refresh",
    response_model=CollectionRefreshResult,
    dependencies=[CAN_WRITE],
)
async def refresh_collections(session: DatabaseSession, org_id: OrgId) -> CollectionRefreshResult:
    """Mark invoices past due as overdue, open a case per client owing overdue money and
    resolve cases that are fully paid. Idempotent; run on demand or from a daily job."""
    result = await CollectionService.refresh(session=session, org_id=org_id, today=date.today())
    await session.commit()
    return result
