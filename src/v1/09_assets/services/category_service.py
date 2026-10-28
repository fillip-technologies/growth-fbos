import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AssetCategoryNotFoundError,
    AssetTypeNotFoundError,
    DuplicateAssetTypeCodeError,
    DuplicateCategoryCodeError,
)
from models.asset import AssetCategory, AssetType
from schemas.categories import (
    AssetCategoryCreate,
    AssetCategoryResponse,
    AssetCategoryUpdate,
    AssetTypeCreate,
    AssetTypeResponse,
    AssetTypeUpdate,
)
from schemas.common import PageResponse
from services.builtins import ensure_builtin_types
from services.pagination import paginate


# --- Categories -------------------------------------------------------------


async def list_categories(
    session: AsyncSession,
    org_id: uuid.UUID,
    parent_id: Optional[uuid.UUID] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
) -> PageResponse[AssetCategoryResponse]:
    has_cats = await session.scalar(
        select(AssetCategory.id).where(AssetCategory.organization_id == org_id).limit(1)
    )
    if not has_cats:
        await ensure_builtin_types(session, org_id)
        await session.commit()

    query = select(AssetCategory).where(AssetCategory.organization_id == org_id)
    if parent_id is not None:
        query = query.where(AssetCategory.parent_id == parent_id)

    rows, page = await paginate(session, query, AssetCategory, limit, cursor, order_by=AssetCategory.code)
    data = [AssetCategoryResponse.model_validate(row) for row in rows]
    return PageResponse(data=data, page=page)


async def get_category(session: AsyncSession, org_id: uuid.UUID, category_id: uuid.UUID) -> AssetCategoryResponse:
    res = await session.execute(
        select(AssetCategory).where(AssetCategory.id == category_id, AssetCategory.organization_id == org_id)
    )
    cat = res.scalars().first()
    if not cat:
        raise AssetCategoryNotFoundError(str(category_id))
    return AssetCategoryResponse.model_validate(cat)


async def create_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: AssetCategoryCreate,
) -> AssetCategoryResponse:
    existing = await session.execute(
        select(AssetCategory).where(AssetCategory.organization_id == org_id, AssetCategory.code == data.code)
    )
    if existing.scalars().first():
        raise DuplicateCategoryCodeError(data.code)

    if data.parent_id:
        parent = await session.execute(
            select(AssetCategory).where(AssetCategory.id == data.parent_id, AssetCategory.organization_id == org_id)
        )
        if not parent.scalars().first():
            raise AssetCategoryNotFoundError(str(data.parent_id))

    cat = AssetCategory(
        id=uuid.uuid4(),
        organization_id=org_id,
        code=data.code,
        name=data.name,
        parent_id=data.parent_id,
    )
    session.add(cat)
    await session.flush()
    return AssetCategoryResponse.model_validate(cat)


async def update_category(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: uuid.UUID,
    data: AssetCategoryUpdate,
) -> AssetCategoryResponse:
    res = await session.execute(
        select(AssetCategory).where(AssetCategory.id == category_id, AssetCategory.organization_id == org_id)
    )
    cat = res.scalars().first()
    if not cat:
        raise AssetCategoryNotFoundError(str(category_id))

    if data.name is not None:
        cat.name = data.name
    if data.parent_id is not None:
        if data.parent_id == category_id:
            raise AssetCategoryNotFoundError("Category cannot be its own parent")
        cat.parent_id = data.parent_id

    await session.flush()
    return AssetCategoryResponse.model_validate(cat)


# --- Asset Types ------------------------------------------------------------


async def list_types(
    session: AsyncSession,
    org_id: uuid.UUID,
    category_id: Optional[uuid.UUID] = None,
    family: Optional[str] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
) -> PageResponse[AssetTypeResponse]:
    has_cats = await session.scalar(
        select(AssetCategory.id).where(AssetCategory.organization_id == org_id).limit(1)
    )
    if not has_cats:
        await ensure_builtin_types(session, org_id)
        await session.commit()

    query = (
        select(AssetType)
        .join(AssetCategory, AssetType.category_id == AssetCategory.id)
        .where(AssetCategory.organization_id == org_id)
    )
    if category_id is not None:
        query = query.where(AssetType.category_id == category_id)
    if family is not None:
        query = query.where(AssetType.family == family)

    rows, page = await paginate(session, query, AssetType, limit, cursor, order_by=AssetType.name)
    data = [AssetTypeResponse.model_validate(row) for row in rows]
    return PageResponse(data=data, page=page)


async def get_type(session: AsyncSession, org_id: uuid.UUID, type_id: uuid.UUID) -> AssetTypeResponse:
    query = (
        select(AssetType)
        .join(AssetCategory, AssetType.category_id == AssetCategory.id)
        .where(AssetType.id == type_id, AssetCategory.organization_id == org_id)
    )
    res = await session.execute(query)
    at = res.scalars().first()
    if not at:
        raise AssetTypeNotFoundError(str(type_id))
    return AssetTypeResponse.model_validate(at)


async def create_type(
    session: AsyncSession,
    org_id: uuid.UUID,
    data: AssetTypeCreate,
) -> AssetTypeResponse:
    # Ensure category belongs to this organization
    cat_res = await session.execute(
        select(AssetCategory).where(AssetCategory.id == data.category_id, AssetCategory.organization_id == org_id)
    )
    if not cat_res.scalars().first():
        raise AssetCategoryNotFoundError(str(data.category_id))

    existing = await session.execute(
        select(AssetType).where(AssetType.category_id == data.category_id, AssetType.code == data.code)
    )
    if existing.scalars().first():
        raise DuplicateAssetTypeCodeError(data.code)

    at = AssetType(
        id=uuid.uuid4(),
        category_id=data.category_id,
        code=data.code,
        name=data.name,
        family=data.family,
        tracks_expiry=data.tracks_expiry,
        single_custodian=data.single_custodian,
        attribute_schema=data.attribute_schema or {},
    )
    session.add(at)
    await session.flush()
    return AssetTypeResponse.model_validate(at)


async def update_type(
    session: AsyncSession,
    org_id: uuid.UUID,
    type_id: uuid.UUID,
    data: AssetTypeUpdate,
) -> AssetTypeResponse:
    query = (
        select(AssetType)
        .join(AssetCategory, AssetType.category_id == AssetCategory.id)
        .where(AssetType.id == type_id, AssetCategory.organization_id == org_id)
    )
    res = await session.execute(query)
    at = res.scalars().first()
    if not at:
        raise AssetTypeNotFoundError(str(type_id))

    if data.name is not None:
        at.name = data.name
    if data.family is not None:
        at.family = data.family
    if data.tracks_expiry is not None:
        at.tracks_expiry = data.tracks_expiry
    if data.single_custodian is not None:
        at.single_custodian = data.single_custodian
    if data.attribute_schema is not None:
        at.attribute_schema = data.attribute_schema

    await session.flush()
    return AssetTypeResponse.model_validate(at)
