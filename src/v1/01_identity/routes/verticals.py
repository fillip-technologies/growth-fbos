from typing import Literal, Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_actor, get_current_user, require_permission
from exceptions import PermissionDeniedError
from schemas.common import PaginatedResponse
from schemas.token import TokenPayload
from schemas.vertical import (
    FieldDefinitionCreate,
    FieldDefinitionResponse,
    ObjectTypeResponse,
    PackInstallationResponse,
    PackInstallRequest,
    PackPreviewResponse,
    PackVersionUpdate,
    VerticalCreate,
    VerticalPackCreate,
    VerticalPackResponse,
    VerticalPackUpdate,
    VerticalResponse,
    VerticalUpdate,
)
from models.user import User
from services.access_control import Actor
from services.org_unit_vertical_service import org_unit_vertical_service
from services.vertical_service import vertical_service

verticals_router = APIRouter()
object_types_router = APIRouter()
field_definitions_router = APIRouter()
vertical_packs_router = APIRouter()


# ---------------------------------------------------------------------------
# Object Types
# ---------------------------------------------------------------------------

PACK_MANAGE = "identity.vertical_pack.manage"
PACK_INSTALL = "identity.vertical_pack.install"


async def require_pack_access(actor: Actor = Depends(get_actor)) -> Actor:
    """Reading packs is part of both designing them and installing them."""
    if not (actor.has(PACK_MANAGE) or actor.has(PACK_INSTALL)):
        raise PermissionDeniedError(PACK_INSTALL)
    return actor


# ---------------------------------------------------------------------------
# Verticals: the client's own industries, shared by all of its organizations
# ---------------------------------------------------------------------------

@verticals_router.get(
    "",
    response_model=PaginatedResponse[VerticalResponse],
    status_code=status.HTTP_200_OK,
    summary="List the client's verticals",
)
async def list_verticals(
    vertical_status: Optional[Literal["active", "archived"]] = Query(None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    actor: Actor = Depends(get_actor),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[VerticalResponse]:
    return await vertical_service.list_verticals(
        session=db, organization_id=actor.organization_id, status=vertical_status, limit=limit, cursor=cursor
    )


@verticals_router.post(
    "",
    response_model=VerticalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vertical",
)
async def create_vertical(
    body: VerticalCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_permission("identity.vertical.manage")),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalResponse:
    vertical = await vertical_service.create_vertical(session=db, organization_id=actor.organization_id, data=body)
    response.headers["Location"] = f"/api/identity/v1/verticals/{vertical.id}"
    return vertical


@verticals_router.patch(
    "/{vertical_id}",
    response_model=VerticalResponse,
    status_code=status.HTTP_200_OK,
    summary="Rename or archive a vertical",
)
async def update_vertical(
    vertical_id: uuid.UUID,
    body: VerticalUpdate,
    actor: Actor = Depends(require_permission("identity.vertical.manage")),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalResponse:
    return await vertical_service.update_vertical(
        session=db, organization_id=actor.organization_id, vertical_id=vertical_id, data=body
    )


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
    definition_status: Optional[Literal["draft", "published", "retired"]] = Query(None, alias="status"),
    org_unit_id: Optional[uuid.UUID] = Query(
        None, description="Only definitions that apply in this unit: no vertical, or one of the unit's verticals"
    ),
    user_id: Optional[uuid.UUID] = Query(
        None, description="Only definitions that apply to this user's home unit: no vertical, or one of the unit's verticals"
    ),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    actor: Actor = Depends(require_permission("identity.field_definition.read")),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[FieldDefinitionResponse]:
    unit_vertical_ids = None
    target_unit_id = org_unit_id
    if not target_unit_id and user_id:
        user = await db.get(User, user_id)
        if user and user.organization_id == actor.organization_id and user.home_unit_id:
            target_unit_id = user.home_unit_id
    if target_unit_id:
        unit_vertical_ids = await org_unit_vertical_service.effective_vertical_ids(
            session=db, organization_id=actor.organization_id, unit_id=target_unit_id
        )
    return await vertical_service.list_field_definitions(
        session=db,
        organization_id=actor.organization_id,
        object_type=object_type,
        vertical_id=vertical_id,
        status=definition_status,
        applicable_vertical_ids=unit_vertical_ids,
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
    actor: Actor = Depends(require_permission("identity.field_definition.create")),
    db: AsyncSession = Depends(get_db_session),
) -> FieldDefinitionResponse:
    fd = await vertical_service.create_field_definition(
        session=db,
        organization_id=actor.organization_id,
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
    actor: Actor = Depends(require_permission("identity.field_definition.publish")),
    db: AsyncSession = Depends(get_db_session),
) -> FieldDefinitionResponse:
    fd = await vertical_service.publish_field_definition(
        session=db,
        organization_id=actor.organization_id,
        field_definition_id=field_definition_id,
        if_match=if_match,
    )
    response.headers["ETag"] = f'"{fd.version_no}"'
    return fd


# ---------------------------------------------------------------------------
# Vertical packs: designed once per client (versions), installed per organization
# ---------------------------------------------------------------------------

@vertical_packs_router.get(
    "",
    response_model=PaginatedResponse[VerticalPackResponse],
    status_code=status.HTTP_200_OK,
    summary="List the client's vertical packs",
)
async def list_vertical_packs(
    vertical_id: Optional[uuid.UUID] = Query(None, description="Filter by vertical id"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    actor: Actor = Depends(require_pack_access),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[VerticalPackResponse]:
    return await vertical_service.list_vertical_packs(
        session=db,
        organization_id=actor.organization_id,
        vertical_id=vertical_id,
        limit=limit,
        cursor=cursor,
    )


@vertical_packs_router.post(
    "",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vertical pack with its first draft version",
)
async def create_vertical_pack(
    body: VerticalPackCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_permission(PACK_MANAGE)),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    pack = await vertical_service.create_vertical_pack(session=db, organization_id=actor.organization_id, data=body)
    response.headers["Location"] = f"/api/identity/v1/vertical-packs/{pack.id}"
    return pack


@vertical_packs_router.get(
    "/{pack_id}",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a vertical pack with its versions",
)
async def get_vertical_pack(
    pack_id: uuid.UUID,
    actor: Actor = Depends(require_pack_access),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    return await vertical_service.get_vertical_pack(session=db, organization_id=actor.organization_id, pack_id=pack_id)


@vertical_packs_router.patch(
    "/{pack_id}",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_200_OK,
    summary="Rename a vertical pack or move it to another vertical",
)
async def update_vertical_pack(
    pack_id: uuid.UUID,
    body: VerticalPackUpdate,
    actor: Actor = Depends(require_permission(PACK_MANAGE)),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    return await vertical_service.update_vertical_pack(
        session=db, organization_id=actor.organization_id, pack_id=pack_id, data=body
    )


@vertical_packs_router.post(
    "/{pack_id}/versions",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new draft version from the latest one",
)
async def create_pack_version(
    pack_id: uuid.UUID,
    actor: Actor = Depends(require_permission(PACK_MANAGE)),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    return await vertical_service.create_pack_version(session=db, organization_id=actor.organization_id, pack_id=pack_id)


@vertical_packs_router.put(
    "/{pack_id}/versions/{version_no}",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a draft version's content",
)
async def replace_pack_version(
    pack_id: uuid.UUID,
    version_no: int,
    body: PackVersionUpdate,
    if_match: Optional[str] = Header(None, alias="If-Match", description="The draft's revision"),
    actor: Actor = Depends(require_permission(PACK_MANAGE)),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    return await vertical_service.replace_pack_version_content(
        session=db,
        organization_id=actor.organization_id,
        pack_id=pack_id,
        version_no=version_no,
        content=body.content,
        if_match=if_match,
    )


@vertical_packs_router.post(
    "/{pack_id}/versions/{version_no}/publish",
    response_model=VerticalPackResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish a draft version; published versions are read-only",
)
async def publish_pack_version(
    pack_id: uuid.UUID,
    version_no: int,
    if_match: Optional[str] = Header(None, alias="If-Match", description="The draft's revision"),
    actor: Actor = Depends(require_permission(PACK_MANAGE)),
    db: AsyncSession = Depends(get_db_session),
) -> VerticalPackResponse:
    return await vertical_service.publish_pack_version(
        session=db, organization_id=actor.organization_id, pack_id=pack_id, version_no=version_no, if_match=if_match
    )


@vertical_packs_router.get(
    "/{pack_id}/versions/{version_no}/preview",
    response_model=PackPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="What installing this version would change in the organization",
)
async def preview_pack_installation(
    pack_id: uuid.UUID,
    version_no: int,
    actor: Actor = Depends(require_permission(PACK_INSTALL)),
    db: AsyncSession = Depends(get_db_session),
) -> PackPreviewResponse:
    return await vertical_service.preview_installation(
        session=db, organization_id=actor.organization_id, pack_id=pack_id, version_no=version_no
    )


@vertical_packs_router.put(
    "/{pack_id}/installation",
    response_model=PackInstallationResponse,
    status_code=status.HTTP_200_OK,
    summary="Install a published version in the organization (idempotent)",
)
async def install_pack(
    pack_id: uuid.UUID,
    body: PackInstallRequest,
    actor: Actor = Depends(require_permission(PACK_INSTALL)),
    db: AsyncSession = Depends(get_db_session),
) -> PackInstallationResponse:
    return await vertical_service.install_pack(
        session=db,
        organization_id=actor.organization_id,
        user_id=actor.user_id,
        pack_id=pack_id,
        version_no=body.version_no,
    )
