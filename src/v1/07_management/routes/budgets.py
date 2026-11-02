import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status

import permissions
import services.budget_service as service
from dependencies import Control, CurrentActor, DatabaseSession, OrgId, require_permission
from schemas.budget import (
    BudgetActualCreate,
    BudgetActualResponse,
    BudgetAllocationCreate,
    BudgetAllocationResponse,
    BudgetCreate,
    BudgetLineCreate,
    BudgetLineUpdate,
    BudgetResponse,
    BudgetUpdate,
    VarianceResponse,
)
from schemas.common import ListResponse, PageResponse

router = APIRouter(tags=["budgets"])

CAN_READ = Depends(require_permission(permissions.BUDGET_READ))
CAN_MANAGE = Depends(require_permission(permissions.BUDGET_MANAGE))


@router.get("/budgets", response_model=PageResponse[BudgetResponse], dependencies=[CAN_READ])
async def list_budgets(
    session: DatabaseSession,
    org_id: OrgId,
    fiscal_year_id: Optional[uuid.UUID] = Query(None),
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[BudgetResponse]:
    return await service.list_budgets(session, org_id, fiscal_year_id, status_, limit, cursor)


@router.post("/budgets", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_budget(payload: BudgetCreate, session: DatabaseSession, org_id: OrgId) -> BudgetResponse:
    budget = await service.create_budget(session, org_id, payload)
    await session.commit()
    return budget


@router.get("/budgets/{budget_id}", response_model=BudgetResponse, dependencies=[CAN_READ])
async def get_budget(budget_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor, control: Control) -> BudgetResponse:
    """The budget; one waiting for approval picks up control's decision."""
    budget = await service.get_budget_response(session, actor, control, budget_id)
    await session.commit()
    return budget


@router.patch("/budgets/{budget_id}", response_model=BudgetResponse, dependencies=[CAN_MANAGE])
async def update_budget(budget_id: uuid.UUID, payload: BudgetUpdate, session: DatabaseSession, org_id: OrgId) -> BudgetResponse:
    budget = await service.update_budget(session, org_id, budget_id, payload)
    await session.commit()
    return budget


@router.post("/budgets/{budget_id}/lines", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def add_budget_line(budget_id: uuid.UUID, payload: BudgetLineCreate, session: DatabaseSession, org_id: OrgId) -> BudgetResponse:
    budget = await service.add_line(session, org_id, budget_id, payload)
    await session.commit()
    return budget


@router.patch("/budget-lines/{line_id}", response_model=BudgetResponse, dependencies=[CAN_MANAGE])
async def update_budget_line(line_id: uuid.UUID, payload: BudgetLineUpdate, session: DatabaseSession, org_id: OrgId) -> BudgetResponse:
    budget = await service.update_line(session, org_id, line_id, payload)
    await session.commit()
    return budget


@router.delete("/budget-lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_MANAGE])
async def delete_budget_line(line_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    await service.delete_line(session, org_id, line_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/budgets/{budget_id}/submit", response_model=BudgetResponse, dependencies=[CAN_MANAGE])
async def submit_budget(budget_id: uuid.UUID, session: DatabaseSession, actor: CurrentActor, control: Control) -> BudgetResponse:
    """Submit a draft budget for approval: raises a control approval request."""
    budget = await service.submit_budget(session, actor, control, budget_id)
    await session.commit()
    return budget


@router.post("/budgets/{budget_id}/revisions", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def revise_budget(budget_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> BudgetResponse:
    """Reopen an approved budget as the next revision's draft; approved amounts stand until it is approved."""
    budget = await service.revise_budget(session, org_id, budget_id)
    await session.commit()
    return budget


@router.get("/budgets/{budget_id}/variance", response_model=VarianceResponse, dependencies=[CAN_READ])
async def get_budget_variance(
    budget_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, as_of: Optional[date] = Query(None)
) -> VarianceResponse:
    """Budget vs actual vs committed, and last year's actuals for the same categories."""
    return await service.variance(session, org_id, budget_id, as_of or date.today())


@router.get("/budget-lines/{line_id}/allocations", response_model=ListResponse[BudgetAllocationResponse], dependencies=[CAN_READ])
async def list_budget_allocations(line_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> ListResponse[BudgetAllocationResponse]:
    return ListResponse(data=await service.list_line_allocations(session, org_id, line_id))


@router.post(
    "/budget-lines/{line_id}/allocations", response_model=BudgetAllocationResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE],
)
async def allocate_budget(
    line_id: uuid.UUID, payload: BudgetAllocationCreate, session: DatabaseSession, org_id: OrgId
) -> BudgetAllocationResponse:
    """Appropriate part of an approved line to an initiative."""
    allocation = await service.allocate(session, org_id, line_id, payload)
    await session.commit()
    return allocation


@router.get("/budget-lines/{line_id}/actuals", response_model=ListResponse[BudgetActualResponse], dependencies=[CAN_READ])
async def list_budget_actuals(line_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> ListResponse[BudgetActualResponse]:
    return ListResponse(data=await service.list_actuals(session, org_id, line_id))


@router.post(
    "/budget-lines/{line_id}/actuals", response_model=BudgetActualResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE],
)
async def record_budget_actual(
    line_id: uuid.UUID, payload: BudgetActualCreate, session: DatabaseSession, org_id: OrgId
) -> BudgetActualResponse:
    """Enter an actual by hand (marked `manual`)."""
    actual = await service.record_actual(session, org_id, line_id, payload)
    await session.commit()
    return actual
