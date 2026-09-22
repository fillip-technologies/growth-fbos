from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_current_user
from schemas.common import PaginatedResponse
from schemas.token import TokenPayload
from schemas.vertical import (
    FieldDefinitionCreate,
    FieldDefinitionResponse,
    ObjectTypeResponse,
    VerticalPackCreate,
    VerticalPackResponse,
)
from services.vertical_service import vertical_service

object_types_router = APIRouter()
field_definitions_router = APIRouter()
vertical_packs_router = APIRouter()


# ---------------------------------------------------------------------------
# Object Types
# ---------------------------------------------------------------------------

@object_types_router.get(
    "",
    response_model=PaginatedResponse[ObjectTypeResponse],
    status_code=status.HTTP_200_OK,
    summary="List registered business object types",
)
async def list_object_types(
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[ObjectTypeResponse]:
    return await vertical_service.list_object_types(
        session=db,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


# ---------------------------------------------------------------------------
# Field Definitions
# ---------------------------------------------------------------------------

@field_definitions_router.get(
    "",
    response_model=PaginatedResponse[FieldDefinitionResponse],
    status_code=status.HTTP_200_OK,
    summary="List custom field schemas",
)
async def list_field_definitions(
    object_type: Optional[str] = Query(None, description="Filter by object type"),
    vertical_id: Optional[uuid.UUID] = Query(None, description="Filter by vertical id"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[FieldDefinitionResponse]:
    return await vertical_service.list_field_definitions(
        session=db,
        organization_id=current_user.organization_id,
        object_type=object_type,
        vertical_id=vertical_id,
        limit=limit,
        cursor=cursor,
        sort=sort,
    )


@field_definitions_router.post(
    "",
    response_model=FieldDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom field schema (draft)",
)
async def create_field_definition(
    body: FieldDefinitionCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FieldDefinitionResponse:
    fd = await vertical_service.create_field_definition(
        session=db,
        organization_id=current_user.organization_id,
        data=body,
    )
    response.headers["Location"] = f"/api/identity/v1/field-definitions/{fd.id}"
    return fd


@field_definitions_router.post(
    "/{field_definition_id}/publish",
    response_model=FieldDefinitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish a custom field schema",
)
async def publish_field_definition(
    field_definition_id: uuid.UUID,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> FieldDefinitionResponse:
    fd = await vertical_service.publish_field_definition(
        session=db,
        organization_id=current_user.organization_id,
        field_definition_id=field_definition_id,
        if_match=if_match,
    )
    response.headers["ETag"] = f'"{fd.version_no}"'
    return fd


# ---------------------------------------------------------------------------
# Vertical Packs
# ---------------------------------------------------------------------------

@vertical_packs_router.post(
    "",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a vertical configuration pack",
)
async def create_vertical_pack(
    body: VerticalPackCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    pack = await vertical_service.create_vertical_pack(
        session=db,
        organization_id=current_user.organization_id,
        data=body,
    )
    response.headers["Location"] = f"/api/identity/v1/vertical-packs/{pack.id}"
    return pack


@vertical_packs_router.post(
    "/{pack_id}/activate",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Install and activate a vertical pack",
)
async def activate_vertical_pack(
    pack_id: uuid.UUID,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    pack = await vertical_service.activate_vertical_pack(
        session=db,
        organization_id=current_user.organization_id,
        pack_id=pack_id,
    )
    response.headers["Location"] = f"/api/identity/v1/vertical-packs/{pack.id}/activate"
    return pack
