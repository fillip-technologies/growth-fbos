import uuid

from fastapi import APIRouter, Depends, Response, status

from dependencies import CurrentCaller, DatabaseSession, require_permission
from schemas.category import CategoryCreate, CategoryListResponse, CategoryResponse, CategoryUpdate
from services.access import PERM_MANAGE_CATEGORIES, PERM_READ
from services.category_service import category_service

router = APIRouter(prefix="/document-categories", tags=["categories"])


@router.get(
    "",
    response_model=CategoryListResponse,
    summary="List the organization's document categories",
    description="An upload must name one of these. A new organization starts with a default set.",
    dependencies=[Depends(require_permission(PERM_READ))],
)
async def list_categories(session: DatabaseSession, caller: CurrentCaller) -> CategoryListResponse:
    data = await category_service.list_categories(session, caller.organization_id)
    await session.commit()  # keeps a freshly created default set
    return CategoryListResponse(data=data)


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a document category",
    dependencies=[Depends(require_permission(PERM_MANAGE_CATEGORIES))],
)
async def create_category(
    data: CategoryCreate, response: Response, session: DatabaseSession, caller: CurrentCaller
) -> CategoryResponse:
    category = await category_service.create_category(session, caller.organization_id, data)
    response.headers["Location"] = f"/api/documents/v1/document-categories/{category.id}"
    return category


@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
    summary="Rename a category or change its limits",
    description="The code can't change: uploads and integrations refer to it.",
    dependencies=[Depends(require_permission(PERM_MANAGE_CATEGORIES))],
)
async def update_category(
    category_id: uuid.UUID, data: CategoryUpdate, session: DatabaseSession, caller: CurrentCaller
) -> CategoryResponse:
    return await category_service.update_category(session, caller.organization_id, category_id, data)
