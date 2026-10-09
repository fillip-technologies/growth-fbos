"""TDS withheld by customers, and the GST-vs-cash report."""

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response

from dependencies import DatabaseSession, OrgId, require_permission
import permissions
from schemas.tax import GstVsCashReport, TdsReceivableResponse, TdsReceivableUpdate
from services.receivables_service import ReceivablesService

router = APIRouter(tags=["receivables"])

CAN_READ_TDS = Depends(require_permission(permissions.TDS_RECEIVABLE_READ))
CAN_WRITE_TDS = Depends(require_permission(permissions.TDS_RECEIVABLE_WRITE))
CAN_READ_TAX = Depends(require_permission(permissions.TAX_READ))


@router.get("/tds-receivables", response_model=List[TdsReceivableResponse], dependencies=[CAN_READ_TDS])
async def list_tds_receivables(
    session: DatabaseSession,
    org_id: OrgId,
    client_id: Optional[uuid.UUID] = Query(None),
    status: Optional[str] = Query(None, description="expected, reflected, certificate_received, claimed, mismatch, written_off"),
    fiscal_year: Optional[str] = Query(None, description="e.g. 2026-27"),
) -> List[TdsReceivableResponse]:
    """TDS customers withheld from payments: owed by the government until it shows in 26AS and is claimed."""
    return await ReceivablesService.list_tds(session, org_id, client_id, status, fiscal_year)


@router.patch("/tds-receivables/{receivable_id}", response_model=TdsReceivableResponse, dependencies=[CAN_WRITE_TDS])
async def update_tds_receivable(
    receivable_id: uuid.UUID,
    payload: TdsReceivableUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TdsReceivableResponse:
    """Record reconciliation: seen in 26AS, certificate received, claimed, or a mismatch."""
    receivable = await ReceivablesService.update_tds(session, org_id, receivable_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{receivable.version}"'
    return receivable


@router.get("/reports/gst-vs-cash", response_model=GstVsCashReport, dependencies=[CAN_READ_TAX])
async def gst_vs_cash(
    session: DatabaseSession,
    org_id: OrgId,
    period: str = Query(..., description="Month, e.g. 2026-09"),
    currency: str = Query("INR"),
) -> GstVsCashReport:
    return await ReceivablesService.gst_vs_cash(session, org_id, period, currency)
