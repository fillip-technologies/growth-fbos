import uuid

from fastapi import APIRouter, Depends, Query, status

from dependencies import DatabaseSession, OrgId, require_permission
import permissions
from schemas.finance import CategoryCreate, CategoryResponse, CategoryUpdate
from services import categories

router = APIRouter(prefix="/expense-categories", tags=["expense categories"])

CAN_READ = Depends(require_permission(permissions.EXPENSE_READ))
CAN_MANAGE = Depends(require_permission(permissions.SETUP_MANAGE))


@router.get("", response_model=list[CategoryResponse], dependencies=[CAN_READ])
async def list_expense_categories(
    session: DatabaseSession,
    org_id: OrgId,
    include_inactive: bool = Query(False, description="Also list switched-off categories"),
) -> list[CategoryResponse]:
    rows = await categories.list_categories(session, org_id, active_only=not include_inactive)
    return [CategoryResponse.model_validate(row) for row in rows]


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_expense_category(body: CategoryCreate, session: DatabaseSession, org_id: OrgId) -> CategoryResponse:
    return CategoryResponse.model_validate(await categories.create_category(session, org_id, body))


@router.patch("/{category_id}", response_model=CategoryResponse, dependencies=[CAN_MANAGE])
async def update_expense_category(
    category_id: uuid.UUID, body: CategoryUpdate, session: DatabaseSession, org_id: OrgId
) -> CategoryResponse:
    return CategoryResponse.model_validate(await categories.update_category(session, org_id, category_id, body))
