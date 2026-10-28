import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

import permissions
import services.category_service as service
from dependencies import DatabaseSession, OrgId, require_permission
from schemas.categories import (
    AssetCategoryCreate,
    AssetCategoryResponse,
    AssetCategoryUpdate,
    AssetTypeCreate,
    AssetTypeResponse,
    AssetTypeUpdate,
)
from schemas.common import PageResponse

router = APIRouter(tags=["categories"])

CAN_READ = Depends(require_permission(permissions.ASSET_READ))
CAN_MANAGE_SETUP = Depends(require_permission(permissions.SETUP_MANAGE))


# --- Categories -------------------------------------------------------------


@router.get("/asset-categories", response_model=PageResponse[AssetCategoryResponse], dependencies=[CAN_READ])
async def list_categories(
    session: DatabaseSession,
    org_id: OrgId,
    parent_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[AssetCategoryResponse]:
    """List asset categories."""
    return await service.list_categories(session, org_id, parent_id, limit, cursor)


@router.post(
    "/asset-categories",
    response_model=AssetCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_SETUP],
)
async def create_category(
    payload: AssetCategoryCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetCategoryResponse:
    """Create an asset category."""
    cat = await service.create_category(session, org_id, payload)
    await session.commit()
    return cat


@router.get("/asset-categories/{category_id}", response_model=AssetCategoryResponse, dependencies=[CAN_READ])
async def get_category(
    category_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetCategoryResponse:
    """Get an asset category."""
    return await service.get_category(session, org_id, category_id)


@router.patch("/asset-categories/{category_id}", response_model=AssetCategoryResponse, dependencies=[CAN_MANAGE_SETUP])
async def update_category(
    category_id: uuid.UUID,
    payload: AssetCategoryUpdate,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetCategoryResponse:
    """Update an asset category."""
    cat = await service.update_category(session, org_id, category_id, payload)
    await session.commit()
    return cat


# --- Asset Types ------------------------------------------------------------


@router.get("/asset-types", response_model=PageResponse[AssetTypeResponse], dependencies=[CAN_READ])
async def list_types(
    session: DatabaseSession,
    org_id: OrgId,
    category_id: Optional[uuid.UUID] = Query(None),
    family: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[AssetTypeResponse]:
    """List asset types."""
    return await service.list_types(session, org_id, category_id, family, limit, cursor)


@router.post(
    "/asset-types",
    response_model=AssetTypeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_MANAGE_SETUP],
)
async def create_type(
    payload: AssetTypeCreate,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetTypeResponse:
    """Create an asset type."""
    at = await service.create_type(session, org_id, payload)
    await session.commit()
    return at


@router.get("/asset-types/{type_id}", response_model=AssetTypeResponse, dependencies=[CAN_READ])
async def get_type(
    type_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetTypeResponse:
    """Get an asset type."""
    return await service.get_type(session, org_id, type_id)


@router.patch("/asset-types/{type_id}", response_model=AssetTypeResponse, dependencies=[CAN_MANAGE_SETUP])
async def update_type(
    type_id: uuid.UUID,
    payload: AssetTypeUpdate,
    session: DatabaseSession,
    org_id: OrgId,
) -> AssetTypeResponse:
    """Update an asset type."""
    at = await service.update_type(session, org_id, type_id, payload)
    await session.commit()
    return at
