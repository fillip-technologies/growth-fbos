from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import require_client_admin
from exceptions import ClientAdminRequiredError
from schemas.common import PaginatedResponse
from schemas.organization import (
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from schemas.token import TokenPayload
from services.organization_service import organization_service

router = APIRouter()


def _client_scope(current_user: TokenPayload) -> uuid.UUID:
    """The client a client-admin acts within, always taken from their token."""
    client_id = current_user.client_uuid
    if client_id is None:
        raise ClientAdminRequiredError()
    return client_id


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
)
async def create_organization(
    body: OrganizationCreateRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: TokenPayload = Depends(require_client_admin),
    db: AsyncSession = Depends(get_db_session),
) -> OrganizationResponse:
    org = await organization_service.create_organization(
        session=db,
        client_id=_client_scope(current_user),
        data=body,
        admin_user_type="employee",
        actor_id=current_user.user_id,
    )
    response.headers["Location"] = f"/api/identity/v1/organizations/{org.id}"
    return org


@router.get(
    "",
    response_model=PaginatedResponse[OrganizationResponse],
    status_code=status.HTTP_200_OK,
    summary="List organizations",
)
async def list_organizations(
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    current_user: TokenPayload = Depends(require_client_admin),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[OrganizationResponse]:
    return await organization_service.list_organizations(
        session=db, client_id=_client_scope(current_user), limit=limit, cursor=cursor
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an organization",
)
async def get_organization(
    organization_id: uuid.UUID,
    current_user: TokenPayload = Depends(require_client_admin),
    db: AsyncSession = Depends(get_db_session),
) -> OrganizationResponse:
    return await organization_service.get_organization(
        session=db, organization_id=organization_id, client_id=_client_scope(current_user)
    )


@router.patch(
    "/{organization_id}",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an organization",
)
async def update_organization(
    organization_id: uuid.UUID,
    body: OrganizationUpdateRequest,
    current_user: TokenPayload = Depends(require_client_admin),
    db: AsyncSession = Depends(get_db_session),
) -> OrganizationResponse:
    return await organization_service.update_organization(
        session=db,
        organization_id=organization_id,
        client_id=_client_scope(current_user),
        data=body,
    )
