import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId
from schemas.client import ClientCreate, ClientResponse, ClientUpdate, ContactCreate, ContactResponse
from schemas.common import PageResponse
from services.client_service import ClientService

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=PageResponse[ClientResponse])
async def list_clients(
    session: DatabaseSession,
    org_id: OrgId,
    status: Optional[str] = Query(None, description="Filter by status: prospect, active, inactive"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[ClientResponse]:
    """List clients with keyset cursor pagination."""
    return await ClientService.list_clients(
        session=session,
        org_id=org_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ClientResponse:
    """Create a new client with GSTIN verification."""
    client = await ClientService.create_client(session=session, org_id=org_id, payload=payload)
    await session.commit()
    response.headers["ETag"] = f'"{client.version}"'
    return client


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> ClientResponse:
    """Retrieve client details by id."""
    client = await ClientService.get_client(session=session, client_id=client_id, org_id=org_id)
    response.headers["ETag"] = f'"{client.version}"'
    return client


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: uuid.UUID,
    payload: ClientUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ClientResponse:
    """Update client fields with optimistic concurrency control."""
    client = await ClientService.update_client(
        session=session,
        client_id=client_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{client.version}"'
    return client


@router.post("/{client_id}/contacts", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def add_client_contact(
    client_id: uuid.UUID,
    payload: ContactCreate,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ContactResponse:
    """Add a new contact person to the specified client."""
    contact = await ClientService.add_contact(
        session=session,
        client_id=client_id,
        org_id=org_id,
        payload=payload,
    )
    await session.commit()
    return contact
