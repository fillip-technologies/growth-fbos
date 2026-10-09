"""Contract billing schedules: what each contract will be invoiced in, what is due, and billing a line."""

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId, UserId, require_idempotency_key, require_permission
import permissions
from schemas.billing import BillingScheduleLineResponse, BillingScheduleLineUpdate, BillingScheduleResponse
from schemas.invoice import InvoiceResponse
from services.billing_schedule_service import BillingScheduleService

router = APIRouter(tags=["billing schedules"])

CAN_READ = Depends(require_permission(permissions.BILLING_SCHEDULE_READ))
CAN_WRITE = Depends(require_permission(permissions.BILLING_SCHEDULE_WRITE))


@router.get("/billing-schedules", response_model=List[BillingScheduleResponse], dependencies=[CAN_READ])
async def list_billing_schedules(
    session: DatabaseSession, org_id: OrgId, contract_id: Optional[uuid.UUID] = Query(None)
) -> List[BillingScheduleResponse]:
    return await BillingScheduleService.list_schedules(session, org_id, contract_id)


@router.get("/billing-schedules/{schedule_id}", response_model=BillingScheduleResponse, dependencies=[CAN_READ])
async def get_billing_schedule(schedule_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> BillingScheduleResponse:
    return await BillingScheduleService.get_schedule(session, org_id, schedule_id)


@router.get("/billing-schedule-lines", response_model=List[BillingScheduleLineResponse], dependencies=[CAN_READ])
async def list_billing_schedule_lines(
    session: DatabaseSession,
    org_id: OrgId,
    status: Optional[str] = Query(None, description="planned, ready, invoiced, cancelled"),
    billable: Optional[bool] = Query(None, description="true: ready to invoice now (the 'ready to bill' list)"),
    contract_id: Optional[uuid.UUID] = Query(None),
) -> List[BillingScheduleLineResponse]:
    return await BillingScheduleService.list_lines(session, org_id, status, billable, contract_id)


@router.patch(
    "/billing-schedules/{schedule_id}/lines/{line_id}", response_model=BillingScheduleLineResponse, dependencies=[CAN_WRITE]
)
async def update_billing_schedule_line(
    schedule_id: uuid.UUID,
    line_id: uuid.UUID,
    payload: BillingScheduleLineUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> BillingScheduleLineResponse:
    """Mark a milestone reached (ready), cancel a line, or put it back to planned."""
    line = await BillingScheduleService.update_line(session, org_id, schedule_id, line_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{line.version}"'
    return line


@router.post(
    "/billing-schedules/{schedule_id}/lines/{line_id}/invoices",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def bill_schedule_line(
    schedule_id: uuid.UUID,
    line_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> InvoiceResponse:
    """Draft the invoice for this line. A line is billed once; issuing the draft works out its GST."""
    require_idempotency_key(idempotency_key)
    invoice = await BillingScheduleService.bill_line(session, org_id, user_id, schedule_id, line_id)
    await session.commit()
    response.headers["ETag"] = f'"{invoice.version}"'
    response.headers["Location"] = f"/api/revenue/v1/invoices/{invoice.id}"
    return invoice
