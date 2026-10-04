from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import require_permission
from exceptions import PreconditionRequiredError
from schemas.common import PaginatedResponse
from schemas.org_unit import (
    OrgUnitCreate,
    OrgUnitMoveRequest,
    OrgUnitResponse,
    OrgUnitUpdate,
    OrgUnitVerticalsResponse,
    OrgUnitVerticalsUpdate,
)
from services.access_control import Actor
from services.org_unit_service import org_unit_service
from services.org_unit_vertical_service import org_unit_vertical_service

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[OrgUnitResponse],
    status_code=status.HTTP_200_OK,
    summary="List organization units",
)
async def list_org_units(
    unit_type: Optional[str] = Query(None, description="Filter by type (branch, department, team)"),
    parent_id: Optional[uuid.UUID] = Query(None, description="Direct children of this unit"),
    status: Optional[str] = Query(None, description="Filter by status (active, inactive)"),
    q: Optional[str] = Query(None, description="Search by name or code"),
    sort: Optional[str] = Query(None, description="Comma-separated fields, - for descending"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    actor: Actor = Depends(require_permission("identity.org_unit.read")),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[OrgUnitResponse]:
    return await org_unit_service.list_org_units(
        session=db,
        organization_id=actor.organization_id,
        unit_type=unit_type,
        parent_id=parent_id,
        status=status,
        q=q,
        sort=sort,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "",
    response_model=OrgUnitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization unit",
)
async def create_org_unit(
    body: OrgUnitCreate,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    actor: Actor = Depends(require_permission("identity.org_unit.create")),
    db: AsyncSession = Depends(get_db_session),
) -> OrgUnitResponse:
    unit = await org_unit_service.create_org_unit(
        session=db,
        organization_id=actor.organization_id,
        data=body,
    )
    response.headers["ETag"] = f'"{unit.version}"'
    response.headers["Location"] = f"/api/identity/v1/org-units/{unit.id}"
    return unit


@router.get(
    "/{unit_id}",
    response_model=OrgUnitResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an organization unit",
)
async def get_org_unit(
    unit_id: uuid.UUID,
    response: Response,
    actor: Actor = Depends(require_permission("identity.org_unit.read")),
    db: AsyncSession = Depends(get_db_session),
) -> OrgUnitResponse:
    unit = await org_unit_service.get_org_unit(
        session=db,
        unit_id=unit_id,
        organization_id=actor.organization_id,
    )
    response.headers["ETag"] = f'"{unit.version}"'
    return unit


@router.patch(
    "/{unit_id}",
    response_model=OrgUnitResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an organization unit",
)
async def update_org_unit(
    unit_id: uuid.UUID,
    body: OrgUnitUpdate,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    actor: Actor = Depends(require_permission("identity.org_unit.update")),
    db: AsyncSession = Depends(get_db_session),
) -> OrgUnitResponse:
    if not if_match:
        raise PreconditionRequiredError("If-Match header with ETag version is required for updates")

    unit = await org_unit_service.update_org_unit(
        session=db,
        unit_id=unit_id,
        organization_id=actor.organization_id,
        data=body,
        if_match=if_match,
    )
    response.headers["ETag"] = f'"{unit.version}"'
    return unit


@router.post(
    "/{unit_id}/move",
    response_model=OrgUnitResponse,
    status_code=status.HTTP_200_OK,
    summary="Move a unit to a new parent",
)
async def move_org_unit(
    unit_id: uuid.UUID,
    body: OrgUnitMoveRequest,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    actor: Actor = Depends(require_permission("identity.org_unit.move")),
    db: AsyncSession = Depends(get_db_session),
) -> OrgUnitResponse:
    if not if_match:
        raise PreconditionRequiredError("If-Match header with ETag version is required to move a unit")

    unit = await org_unit_service.move_org_unit(
        session=db,
        unit_id=unit_id,
        organization_id=actor.organization_id,
        data=body,
        if_match=if_match,
    )
    response.headers["ETag"] = f'"{unit.version}"'
    return unit


@router.get(
    "/{unit_id}/verticals",
    response_model=OrgUnitVerticalsResponse,
    status_code=status.HTTP_200_OK,
    summary="The verticals a unit works in, own or inherited",
)
async def get_org_unit_verticals(
    unit_id: uuid.UUID,
    actor: Actor = Depends(require_permission("identity.org_unit.read")),
    db: AsyncSession = Depends(get_db_session),
) -> OrgUnitVerticalsResponse:
    return await org_unit_vertical_service.get_unit_verticals(
        session=db, organization_id=actor.organization_id, unit_id=unit_id
    )


@router.put(
    "/{unit_id}/verticals",
    response_model=OrgUnitVerticalsResponse,
    status_code=status.HTTP_200_OK,
    summary="Set a branch's or department's own verticals (empty = inherit)",
)
async def replace_org_unit_verticals(
    unit_id: uuid.UUID,
    body: OrgUnitVerticalsUpdate,
    actor: Actor = Depends(require_permission("identity.org_unit.update")),
    db: AsyncSession = Depends(get_db_session),
) -> OrgUnitVerticalsResponse:
    return await org_unit_vertical_service.replace_unit_verticals(
        session=db, organization_id=actor.organization_id, unit_id=unit_id, vertical_ids=body.vertical_ids
    )
