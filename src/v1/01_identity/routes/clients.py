from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from exceptions import ClientAdminRequiredError
from dependencies import require_client_admin, require_platform_admin
from schemas.client import ClientCreateRequest, ClientResponse, ClientUpdateRequest
from schemas.common import PaginatedResponse
from schemas.token import TokenPayload
from services.client_service import client_service

router = APIRouter()


@router.post(
    "",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a client",
)
async def create_client(
    body: ClientCreateRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: TokenPayload = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    client = await client_service.create_client(
        session=db, data=body, actor_id=current_user.user_id
    )
    response.headers["Location"] = f"/api/identity/v1/clients/{client.id}"
    return client


@router.get(
    "",
    response_model=PaginatedResponse[ClientResponse],
    status_code=status.HTTP_200_OK,
    summary="List clients",
)
async def list_clients(
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    current_user: TokenPayload = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[ClientResponse]:
    return await client_service.list_clients(session=db, limit=limit, cursor=cursor)


@router.get(
    "/me",
    response_model=ClientResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the caller's own client (subscription window, quotas)",
)
async def get_my_client(
    current_user: TokenPayload = Depends(require_client_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    # Declared before "/{client_id}" so "me" is not parsed as a UUID. The client comes
    # from the token, never from the URL, so a client admin can only ever see their own.
    if current_user.client_id is None:
        raise ClientAdminRequiredError()
    return await client_service.get_client(session=db, client_id=current_user.client_uuid)


@router.get(
    "/{client_id}",
    response_model=ClientResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a client",
)
async def get_client(
    client_id: uuid.UUID,
    current_user: TokenPayload = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    return await client_service.get_client(session=db, client_id=client_id)


@router.patch(
    "/{client_id}",
    response_model=ClientResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a client",
)
async def update_client(
    client_id: uuid.UUID,
    body: ClientUpdateRequest,
    current_user: TokenPayload = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ClientResponse:
    return await client_service.update_client(session=db, client_id=client_id, data=body)
