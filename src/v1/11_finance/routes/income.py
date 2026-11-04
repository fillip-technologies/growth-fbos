from datetime import date
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from dependencies import DatabaseSession, OrgId, UserId, require_permission
from exceptions import ValidationFailedError
import permissions
from schemas.common import PageResponse
from schemas.finance import IncomeCreate, IncomeResponse, IncomeUpdate
from services import investment_service

router = APIRouter(prefix="/income-entries", tags=["income"])

# Income outside sales belongs with investments: the same people hold and record both.
CAN_READ = Depends(require_permission(permissions.INVESTMENT_READ))
CAN_WRITE = Depends(require_permission(permissions.INVESTMENT_WRITE))


@router.get("", response_model=PageResponse[IncomeResponse], dependencies=[CAN_READ])
async def list_income_entries(
    session: DatabaseSession,
    org_id: OrgId,
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    income_type: Optional[str] = None,
    investment_id: Optional[uuid.UUID] = None,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = None,
) -> PageResponse[IncomeResponse]:
    if from_date and to_date and to_date < from_date:
        raise ValidationFailedError("to", "must be on or after 'from'")
    rows, page = await investment_service.list_income(
        session,
        org_id,
        limit=limit,
        cursor=cursor,
        from_date=from_date,
        to_date=to_date,
        income_type=income_type,
        investment_id=investment_id,
    )
    return PageResponse(data=rows, page=page)


@router.post("", response_model=IncomeResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE])
async def create_income_entry(body: IncomeCreate, session: DatabaseSession, org_id: OrgId, user_id: UserId) -> IncomeResponse:
    """Income other than sales. Customer payments are recorded against invoices in revenue."""
    return await investment_service.create_income(session, org_id, user_id, body)


@router.get("/{entry_id}", response_model=IncomeResponse, dependencies=[CAN_READ])
async def get_income_entry(entry_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> IncomeResponse:
    return investment_service.income_response(await investment_service.get_income(session, org_id, entry_id))


@router.patch("/{entry_id}", response_model=IncomeResponse, dependencies=[CAN_WRITE])
async def update_income_entry(
    entry_id: uuid.UUID, body: IncomeUpdate, session: DatabaseSession, org_id: OrgId
) -> IncomeResponse:
    return await investment_service.update_income(session, org_id, entry_id, body)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_WRITE])
async def delete_income_entry(entry_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    await investment_service.delete_income(session, org_id, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
