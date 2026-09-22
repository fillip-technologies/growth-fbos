import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, status

from dependencies import DatabaseSession, OrgId, UserId
from schemas.collection import (
    CollectionCaseResponse,
    CollectionFollowUpCreate,
)
from schemas.common import PageResponse
from services.collection_service import CollectionService

router = APIRouter(prefix="/collection-cases", tags=["collections"])


@router.get("", response_model=PageResponse[CollectionCaseResponse])
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


@router.post("/{case_id}/follow-ups", response_model=CollectionCaseResponse, status_code=status.HTTP_201_CREATED)
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
