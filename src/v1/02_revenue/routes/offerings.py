import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, status

from dependencies import DatabaseSession, OrgId
from schemas.common import PageResponse
from schemas.offering import OfferingCreate, OfferingResponse
from services.offering_service import OfferingService

router = APIRouter(prefix="/offerings", tags=["offerings"])


@router.get("", response_model=PageResponse[OfferingResponse])
async def list_offerings(
    session: DatabaseSession,
    org_id: OrgId,
    vertical_id: Optional[uuid.UUID] = Query(None, description="Filter by vertical id"),
    status: Optional[str] = Query(None, description="Filter by status: active, deprecated"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[OfferingResponse]:
    """List service offerings catalog with cursor pagination."""
    return await OfferingService.list_offerings(
        session=session,
        org_id=org_id,
        vertical_id=vertical_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@router.post("", response_model=OfferingResponse, status_code=status.HTTP_201_CREATED)
async def create_offering(
    payload: OfferingCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> OfferingResponse:
    """Create a new service catalog offering."""
    offering = await OfferingService.create_offering(
        session=session,
        org_id=org_id,
        payload=payload,
    )
    await session.commit()
    return offering
