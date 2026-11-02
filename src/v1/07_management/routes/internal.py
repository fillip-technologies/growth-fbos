"""Endpoints other FBOS services call (X-FBOS-Internal-Token), never the console."""

from fastapi import APIRouter, Depends, Response, status

import services.budget_service as budget_service
from dependencies import DatabaseSession, verify_internal_caller
from schemas.budget import BudgetActualResponse, InternalBudgetActualCreate

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_caller)])


@router.post("/budget-actuals", response_model=BudgetActualResponse, status_code=status.HTTP_201_CREATED)
async def mirror_budget_actual(
    payload: InternalBudgetActualCreate, session: DatabaseSession, response: Response
) -> BudgetActualResponse:
    """An actual from the service that owns the money. Posting the same `source_event_id` again changes nothing (200)."""
    actual, created = await budget_service.mirror_actual(session, payload)
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return actual
