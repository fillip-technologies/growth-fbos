"""Endpoints only other FBOS services call (guarded by the internal service token)."""
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query

from dependencies import CurrentActor, DatabaseSession, verify_internal_caller
from exceptions import ExpenseNotFoundError, PermissionDeniedError
import permissions
from schemas.finance import SubjectAccessResponse
from services import expense_service, investment_service

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_caller)])

EXPENSE_SUBJECT = "finance.expense"
INVESTMENT_SUBJECT = "finance.investment"
# subject type -> (permission to see its documents, permission to attach one)
SUBJECT_PERMISSIONS = {
    EXPENSE_SUBJECT: (permissions.EXPENSE_READ, permissions.EXPENSE_WRITE),
    INVESTMENT_SUBJECT: (permissions.INVESTMENT_READ, permissions.INVESTMENT_WRITE),
}


@router.get(
    "/subject-access/{subject_type}/{subject_id}",
    response_model=SubjectAccessResponse,
    summary="May the caller see / attach documents to this expense or investment? (internal)",
    description=(
        "Asked by the documents service with the user's forwarded credentials (bills, receipts, "
        "FD certificates). 200 when allowed; 404 for an unknown or other-organization record, "
        "403 without the permission."
    ),
)
async def get_subject_access(
    subject_type: str,
    subject_id: uuid.UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    action: Literal["read", "attach"] = Query("read"),
) -> SubjectAccessResponse:
    codes = SUBJECT_PERMISSIONS.get(subject_type)
    if codes is None:
        raise ExpenseNotFoundError()
    required = codes[1] if action == "attach" else codes[0]
    if not actor.has(required):
        raise PermissionDeniedError(required)

    if subject_type == EXPENSE_SUBJECT:
        expense = await expense_service.get_expense(session, actor.organization_id, subject_id)
        organization_id, label = expense.organization_id, expense.description
    else:
        investment = await investment_service.get_investment(session, actor.organization_id, subject_id)
        organization_id, label = investment.organization_id, investment.name
    return SubjectAccessResponse(type=subject_type, id=subject_id, organization_id=organization_id, label=label)
