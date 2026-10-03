import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId
from schemas.client_service import (
    ClientServiceCreate,
    ClientServiceResponse,
    ClientServiceUpdate,
    ServiceCategoryCreate,
    ServiceCategoryResponse,
    ServiceCategoryUpdate,
    ServiceProviderCreate,
    ServiceProviderResponse,
    ServiceProviderUpdate,
)
from schemas.common import PageResponse
from services.client_service_service import ClientServiceService

router = APIRouter(tags=["client-services"])


# --- Categories ------------------------------------------------------------


@router.get("/service-categories", response_model=PageResponse[ServiceCategoryResponse])
async def list_service_categories(session: DatabaseSession, org_id: OrgId) -> PageResponse[ServiceCategoryResponse]:
    """List the organization's service categories (a default set is created on first use)."""
    categories = await ClientServiceService.list_categories(session=session, org_id=org_id)
    await session.commit()
    return categories


@router.post("/service-categories", response_model=ServiceCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_service_category(
    payload: ServiceCategoryCreate, session: DatabaseSession, org_id: OrgId
) -> ServiceCategoryResponse:
    """Add a service category."""
    category = await ClientServiceService.create_category(session=session, org_id=org_id, payload=payload)
    await session.commit()
    return category


@router.patch("/service-categories/{category_id}", response_model=ServiceCategoryResponse)
async def update_service_category(
    category_id: uuid.UUID, payload: ServiceCategoryUpdate, session: DatabaseSession, org_id: OrgId
) -> ServiceCategoryResponse:
    """Rename or deactivate a service category."""
    category = await ClientServiceService.update_category(
        session=session, org_id=org_id, category_id=category_id, payload=payload
    )
    await session.commit()
    return category


# --- Providers -------------------------------------------------------------


@router.get("/service-providers", response_model=PageResponse[ServiceProviderResponse])
async def list_service_providers(
    session: DatabaseSession,
    org_id: OrgId,
    category_id: Optional[uuid.UUID] = Query(None, description="Filter by default category"),
    q: Optional[str] = Query(None, description="Search by name"),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[ServiceProviderResponse]:
    """List service providers, alphabetically."""
    return await ClientServiceService.list_providers(
        session=session, org_id=org_id, category_id=category_id, q=q, limit=limit, cursor=cursor
    )


@router.post("/service-providers", response_model=ServiceProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_service_provider(
    payload: ServiceProviderCreate, session: DatabaseSession, org_id: OrgId, response: Response
) -> ServiceProviderResponse:
    """Add a service provider."""
    provider = await ClientServiceService.create_provider(session=session, org_id=org_id, payload=payload)
    await session.commit()
    response.headers["ETag"] = f'"{provider.version}"'
    return provider


@router.get("/service-providers/{provider_id}", response_model=ServiceProviderResponse)
async def get_service_provider(
    provider_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, response: Response
) -> ServiceProviderResponse:
    """Retrieve a service provider."""
    provider = await ClientServiceService.get_provider(session=session, org_id=org_id, provider_id=provider_id)
    response.headers["ETag"] = f'"{provider.version}"'
    return provider


@router.patch("/service-providers/{provider_id}", response_model=ServiceProviderResponse)
async def update_service_provider(
    provider_id: uuid.UUID,
    payload: ServiceProviderUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ServiceProviderResponse:
    """Update a service provider with optimistic concurrency control."""
    provider = await ClientServiceService.update_provider(
        session=session, org_id=org_id, provider_id=provider_id, payload=payload, if_match=if_match
    )
    await session.commit()
    response.headers["ETag"] = f'"{provider.version}"'
    return provider


@router.delete("/service-providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service_provider(provider_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    """Delete a provider that no client service uses."""
    await ClientServiceService.delete_provider(session=session, org_id=org_id, provider_id=provider_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Client services -------------------------------------------------------


@router.get("/client-services", response_model=PageResponse[ClientServiceResponse])
async def list_client_services(
    session: DatabaseSession,
    org_id: OrgId,
    client_id: Optional[uuid.UUID] = Query(None),
    provider_id: Optional[uuid.UUID] = Query(None),
    category_id: Optional[uuid.UUID] = Query(None),
    status: Optional[Literal["active", "expired", "cancelled"]] = Query(None),
    managed_by: Optional[Literal["us", "client", "third_party"]] = Query(None),
    renewal_within_days: Optional[int] = Query(
        None, ge=0, le=3650, description="Renewing within N days (overdue renewals included)"
    ),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[ClientServiceResponse]:
    """Search outside services across all clients, e.g. every client using a provider or renewals due soon."""
    return await ClientServiceService.list_services(
        session=session,
        org_id=org_id,
        client_id=client_id,
        provider_id=provider_id,
        category_id=category_id,
        status=status,
        managed_by=managed_by,
        renewal_within_days=renewal_within_days,
        limit=limit,
        cursor=cursor,
    )


@router.get("/clients/{client_id}/services", response_model=PageResponse[ClientServiceResponse])
async def list_services_for_client(
    client_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
) -> PageResponse[ClientServiceResponse]:
    """List the outside services one client uses."""
    return await ClientServiceService.list_services(
        session=session, org_id=org_id, client_id=client_id, limit=limit, cursor=cursor
    )


@router.post(
    "/clients/{client_id}/services", response_model=ClientServiceResponse, status_code=status.HTTP_201_CREATED
)
async def create_client_service(
    client_id: uuid.UUID,
    payload: ClientServiceCreate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> ClientServiceResponse:
    """Record an outside service the client uses."""
    record = await ClientServiceService.create_service(
        session=session, org_id=org_id, client_id=client_id, payload=payload
    )
    await session.commit()
    response.headers["ETag"] = f'"{record.version}"'
    return record


@router.get("/client-services/{record_id}", response_model=ClientServiceResponse)
async def get_client_service(
    record_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, response: Response
) -> ClientServiceResponse:
    """Retrieve one client service."""
    record = await ClientServiceService.get_service(session=session, org_id=org_id, record_id=record_id)
    response.headers["ETag"] = f'"{record.version}"'
    return record


@router.patch("/client-services/{record_id}", response_model=ClientServiceResponse)
async def update_client_service(
    record_id: uuid.UUID,
    payload: ClientServiceUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ClientServiceResponse:
    """Update a client service with optimistic concurrency control."""
    record = await ClientServiceService.update_service(
        session=session, org_id=org_id, record_id=record_id, payload=payload, if_match=if_match
    )
    await session.commit()
    response.headers["ETag"] = f'"{record.version}"'
    return record


@router.delete("/client-services/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_service(record_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    """Delete a client service."""
    await ClientServiceService.delete_service(session=session, org_id=org_id, record_id=record_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
