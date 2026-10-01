import logging
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ClientCodeAlreadyExistsError, ClientNotFoundError
from models.client import Client
from models.organization import Organization
from schemas.client import ClientCreateRequest, ClientResponse, ClientUpdateRequest
from schemas.common import PageInfo, PaginatedResponse
from schemas.organization import OrganizationCreateRequest
from services.event_publisher import event_publisher
from services.organization_service import organization_service

logger = logging.getLogger("identity.client_service")


class ClientService:
    def _build_response(
        self, client: Client, active_organizations_count: Optional[int] = None
    ) -> ClientResponse:
        return ClientResponse(
            id=client.id,
            name=client.name,
            code=client.code,
            contact_email=client.contact_email,
            status=client.status,
            max_organizations=client.max_organizations,
            max_users_per_org=client.max_users_per_org,
            active_organizations_count=active_organizations_count,
            created_at=client.created_at.isoformat() if client.created_at else None,
        )

    async def create_client(
        self,
        session: AsyncSession,
        data: ClientCreateRequest,
        actor_id: Optional[uuid.UUID] = None,
    ) -> ClientResponse:
        """
        Create a client and, in the same transaction, its first organization with a
        `client_admin` first user. The client_admin can then create further
        organizations and manage users itself.
        """
        duplicate = await session.execute(
            select(Client).where(func.lower(Client.code) == data.code.lower())
        )
        if duplicate.scalar_one_or_none():
            raise ClientCodeAlreadyExistsError(data.code)

        client = Client(
            id=uuid.uuid4(),
            name=data.name,
            code=data.code,
            contact_email=data.contact_email,
            status="active",
            max_organizations=data.max_organizations if data.max_organizations is not None else 2,
            max_users_per_org=data.max_users_per_org if data.max_users_per_org is not None else 50,
        )
        session.add(client)
        await session.flush()

        first_org = OrganizationCreateRequest(
            name=data.name,
            code=data.code,
            email=data.contact_email,
            base_currency=data.base_currency,
            fiscal_year_start=data.fiscal_year_start,
            timezone=data.timezone,
            admin_email=data.admin_email,
            admin_name=data.admin_name,
        )
        _, org_events = await organization_service.provision_organization(
            session=session,
            client_id=client.id,
            data=first_org,
            admin_user_type="client_admin",
            actor_id=actor_id,
        )

        await session.commit()
        await session.refresh(client)

        await event_publisher.publish(
            "identity.client.created.v1",
            {
                "client_id": str(client.id),
                "code": client.code,
                "name": client.name,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )
        for topic, payload in org_events:
            await event_publisher.publish(topic, payload)

        return self._build_response(client, active_organizations_count=1)

    async def list_clients(
        self,
        session: AsyncSession,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[ClientResponse]:
        query = select(Client).order_by(Client.created_at.desc(), Client.id.desc())

        offset = int(cursor) if cursor and cursor.isdigit() else 0
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        clients = list(result.scalars().all())

        has_more = len(clients) > limit
        if has_more:
            clients = clients[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        return PaginatedResponse(
            data=[self._build_response(c) for c in clients],
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def get_client(
        self,
        session: AsyncSession,
        client_id: uuid.UUID,
    ) -> ClientResponse:
        client = await session.get(Client, client_id)
        if not client:
            raise ClientNotFoundError()

        active_orgs_count = (
            await session.execute(
                select(func.count())
                .select_from(Organization)
                .where(
                    Organization.client_id == client.id,
                    Organization.status != "deleted",
                )
            )
        ).scalar_one()

        return self._build_response(client, active_organizations_count=active_orgs_count)

    async def update_client(
        self,
        session: AsyncSession,
        client_id: uuid.UUID,
        data: ClientUpdateRequest,
    ) -> ClientResponse:
        client = await session.get(Client, client_id)
        if not client:
            raise ClientNotFoundError()

        if data.name is not None:
            client.name = data.name
        if data.contact_email is not None:
            client.contact_email = data.contact_email
        if data.status is not None:
            client.status = data.status
        if data.max_organizations is not None:
            client.max_organizations = data.max_organizations
        if data.max_users_per_org is not None:
            client.max_users_per_org = data.max_users_per_org

        await session.commit()
        await session.refresh(client)

        await event_publisher.publish(
            "identity.client.updated.v1",
            {"client_id": str(client.id)},
        )

        active_orgs_count = (
            await session.execute(
                select(func.count())
                .select_from(Organization)
                .where(
                    Organization.client_id == client.id,
                    Organization.status != "deleted",
                )
            )
        ).scalar_one()

        return self._build_response(client, active_organizations_count=active_orgs_count)



client_service = ClientService()
