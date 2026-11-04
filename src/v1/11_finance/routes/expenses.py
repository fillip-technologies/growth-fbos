from datetime import date
from typing import Literal, Optional
import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId, require_permission
from exceptions import ValidationFailedError
import permissions
from schemas.common import PageResponse
from schemas.finance import ExpenseCreate, ExpenseDecision, ExpenseResponse, ExpenseUpdate
from services import expense_service

router = APIRouter(prefix="/expenses", tags=["expenses"])

CAN_READ = Depends(require_permission(permissions.EXPENSE_READ))
CAN_WRITE = Depends(require_permission(permissions.EXPENSE_WRITE))
CAN_APPROVE = Depends(require_permission(permissions.EXPENSE_APPROVE))


@router.get("", response_model=PageResponse[ExpenseResponse], dependencies=[CAN_READ])
async def list_expenses(
    session: DatabaseSession,
    org_id: OrgId,
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    category_id: Optional[uuid.UUID] = None,
    approval_status: Optional[Literal["pending_approval", "approved", "rejected"]] = None,
    payment_status: Optional[Literal["unpaid", "paid"]] = None,
    work_unit_id: Optional[uuid.UUID] = None,
    org_unit_id: Optional[uuid.UUID] = None,
    q: Optional[str] = Query(None, max_length=100, description="Matches description or vendor"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = None,
) -> PageResponse[ExpenseResponse]:
    if from_date and to_date and to_date < from_date:
        raise ValidationFailedError("to", "must be on or after 'from'")
    rows, page = await expense_service.list_expenses(
        session,
        org_id,
        limit=limit,
        cursor=cursor,
        from_date=from_date,
        to_date=to_date,
        category_id=category_id,
        approval_status=approval_status,
        payment_status=payment_status,
        work_unit_id=work_unit_id,
        org_unit_id=org_unit_id,
        search=q,
    )
    return PageResponse(data=rows, page=page)


@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE])
async def create_expense(body: ExpenseCreate, session: DatabaseSession, org_id: OrgId, user_id: UserId) -> ExpenseResponse:
    """Hardware purchase orders, asset costs, salaries and project costs are recorded elsewhere, never here."""
    return await expense_service.create_expense(session, org_id, user_id, body)


@router.get("/{expense_id}", response_model=ExpenseResponse, dependencies=[CAN_READ])
async def get_expense(expense_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> ExpenseResponse:
    return await expense_service.read_expense(session, org_id, expense_id)


@router.patch("/{expense_id}", response_model=ExpenseResponse, dependencies=[CAN_WRITE])
async def update_expense(
    expense_id: uuid.UUID, body: ExpenseUpdate, session: DatabaseSession, org_id: OrgId
) -> ExpenseResponse:
    return await expense_service.update_expense(session, org_id, expense_id, body)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_WRITE])
async def delete_expense(expense_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    await expense_service.delete_expense(session, org_id, expense_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{expense_id}/decisions", response_model=ExpenseResponse, dependencies=[CAN_APPROVE])
async def decide_expense(
    expense_id: uuid.UUID, body: ExpenseDecision, session: DatabaseSession, actor: CurrentActor
) -> ExpenseResponse:
    """Approve or reject an expense waiting for approval. Nobody decides an expense they recorded."""
    return await expense_service.decide_expense(session, actor, expense_id, body)
