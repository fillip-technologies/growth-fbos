import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId, UserId, require_idempotency_key, require_permission
from schemas.common import PageResponse
from schemas.payment import (
    AllocationBatch,
    PaymentCreate,
    PaymentResponse,
)
from services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])

CAN_READ = Depends(require_permission("revenue.payment.read"))
CAN_WRITE = Depends(require_permission("revenue.payment.write"))


@router.get(
    "", response_model=PageResponse[PaymentResponse],
    dependencies=[CAN_READ],
)
async def list_payments(
    session: DatabaseSession,
    org_id: OrgId,
    client_id: Optional[uuid.UUID] = Query(None, description="Filter by client id"),
    received_from: Optional[date] = Query(None, description="Payment receipt date start"),
    received_to: Optional[date] = Query(None, description="Payment receipt date end"),
    unallocated: Optional[bool] = Query(None, description="Only payments with unallocated funds"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[PaymentResponse]:
    """List inbound client payments with keyset pagination."""
    return await PaymentService.list_payments(
        session=session,
        org_id=org_id,
        client_id=client_id,
        received_from=received_from,
        received_to=received_to,
        unallocated=unallocated,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def record_payment(
    payload: PaymentCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> PaymentResponse:
    """Record a received payment and optionally allocate funds immediately."""
    require_idempotency_key(idempotency_key)

    payment = await PaymentService.record_payment(
        session=session,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
    )
    await session.commit()
    response.headers["ETag"] = f'"{payment.version}"'
    response.headers["Location"] = f"/api/revenue/v1/payments/{payment.id}"
    return payment


@router.post(
    "/{payment_id}/allocations", response_model=PaymentResponse,
    dependencies=[CAN_WRITE],
)
async def allocate_payment(
    payment_id: uuid.UUID,
    payload: AllocationBatch,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> PaymentResponse:
    """Allocate unapplied payment amounts to outstanding invoices."""
    require_idempotency_key(idempotency_key)

    payment = await PaymentService.allocate_payment(
        session=session,
        payment_id=payment_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{payment.version}"'
    return payment


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    dependencies=[CAN_READ],
)
async def get_payment(payment_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, response: Response) -> PaymentResponse:
    """Retrieve one payment with its allocations."""
    payment = await PaymentService.get_payment(session=session, payment_id=payment_id, org_id=org_id)
    response.headers["ETag"] = f'"{payment.version}"'
    return payment
