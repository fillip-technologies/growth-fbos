import logging
from typing import Optional
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ClientCodeAlreadyExistsError, ClientNotFoundError, InvalidSubscriptionWindowError
from models.auth import ApiClient, RefreshToken, UserCredential
from models.calendar import Calendar, CalendarHoliday
from models.client import Client
from models.legal import LegalEntity, TaxRegistration
from models.membership import UnitMembership
from models.org_unit import OrgUnit, OrgUnitVertical
from models.organization import Organization
from models.rbac import Role, RoleAssignment, RolePermission
from models.user import User
from models.vertical import FieldDefinition, VerticalPack
from schemas.client import ClientCreateRequest, ClientResponse, ClientUpdateRequest
from schemas.common import PageInfo, PaginatedResponse
from schemas.organization import DEFAULT_FISCAL_YEAR_START, OrganizationCreateRequest
from services.event_publisher import event_publisher
from services.organization_service import organization_service
from services.subscription import add_one_year, subscription_state, today_utc

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
            subscription_start=client.subscription_start,
            subscription_end=client.subscription_end,
            subscription_state=subscription_state(client),
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

        start = data.subscription_start or today_utc()
        end = data.subscription_end or add_one_year(start)
        if end < start:
            raise InvalidSubscriptionWindowError()

        client = Client(
            id=uuid.uuid4(),
            name=data.name,
            code=data.code,
            contact_email=data.contact_email,
            status="active",
            max_organizations=data.max_organizations if data.max_organizations is not None else 2,
            max_users_per_org=data.max_users_per_org if data.max_users_per_org is not None else 50,
            subscription_start=start,
            subscription_end=end,
        )
        session.add(client)
        await session.flush()

        first_org = OrganizationCreateRequest(
            name=data.name,
            code=data.code,
            email=data.contact_email,
            base_currency=data.base_currency,
            fiscal_year_start=DEFAULT_FISCAL_YEAR_START,
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
            if topic == "identity.user.invited.v1":
                payload = {
                    **payload,
                    "client_name": client.name,
                    "subscription_start": client.subscription_start.isoformat(),
                    "subscription_end": client.subscription_end.isoformat(),
                }
            await event_publisher.publish(topic, payload)

        return self._build_response(client, active_organizations_count=1)

    async def delete_client(
        self,
        session: AsyncSession,
        client_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
    ) -> None:
        """
        Permanently delete a client with all of its organizations, users, roles, units and
        credentials, in one transaction (all or nothing). Security audit logs are kept.
        Data other services hold for these organizations is NOT removed.
        """
        client = await session.get(Client, client_id)
        if not client:
            raise ClientNotFoundError()

        async def ids(stmt) -> list[uuid.UUID]:
            return list((await session.execute(stmt)).scalars().all())

        org_ids = await ids(select(Organization.id).where(Organization.client_id == client_id))
        user_ids = await ids(select(User.id).where(User.organization_id.in_(org_ids))) if org_ids else []
        role_ids = await ids(select(Role.id).where(Role.organization_id.in_(org_ids))) if org_ids else []
        unit_ids = await ids(select(OrgUnit.id).where(OrgUnit.organization_id.in_(org_ids))) if org_ids else []
        entity_ids = await ids(select(LegalEntity.id).where(LegalEntity.organization_id.in_(org_ids))) if org_ids else []
        calendar_ids = await ids(select(Calendar.id).where(Calendar.organization_id.in_(org_ids))) if org_ids else []

        if org_ids:
            # Children first; break the self/cross references before deleting their targets.
            await session.execute(delete(RoleAssignment).where(
                (RoleAssignment.organization_id.in_(org_ids)) | (RoleAssignment.user_id.in_(user_ids))
            ))
            await session.execute(delete(RolePermission).where(RolePermission.role_id.in_(role_ids)))
            await session.execute(delete(UnitMembership).where(
                (UnitMembership.user_id.in_(user_ids)) | (UnitMembership.unit_id.in_(unit_ids))
            ))
            await session.execute(delete(TaxRegistration).where(
                (TaxRegistration.legal_entity_id.in_(entity_ids)) | (TaxRegistration.branch_unit_id.in_(unit_ids))
            ))
            await session.execute(delete(LegalEntity).where(LegalEntity.organization_id.in_(org_ids)))
            await session.execute(delete(OrgUnitVertical).where(OrgUnitVertical.org_unit_id.in_(unit_ids)))
            await session.execute(update(User).where(User.organization_id.in_(org_ids)).values(
                home_unit_id=None, manager_user_id=None))
            await session.execute(update(OrgUnit).where(OrgUnit.organization_id.in_(org_ids)).values(
                head_user_id=None, parent_id=None))
            await session.execute(delete(OrgUnit).where(OrgUnit.organization_id.in_(org_ids)))
            await session.execute(update(Organization).where(Organization.id.in_(org_ids)).values(calendar_id=None))
            await session.execute(delete(CalendarHoliday).where(CalendarHoliday.calendar_id.in_(calendar_ids)))
            await session.execute(delete(Calendar).where(Calendar.organization_id.in_(org_ids)))
            await session.execute(delete(FieldDefinition).where(FieldDefinition.organization_id.in_(org_ids)))
            await session.execute(delete(VerticalPack).where(VerticalPack.organization_id.in_(org_ids)))
            await session.execute(delete(ApiClient).where(ApiClient.organization_id.in_(org_ids)))
            await session.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(user_ids)))
            await session.execute(delete(UserCredential).where(UserCredential.user_id.in_(user_ids)))
            await session.execute(delete(User).where(User.organization_id.in_(org_ids)))
            await session.execute(delete(Role).where(Role.organization_id.in_(org_ids)))
            await session.execute(delete(Organization).where(Organization.client_id == client_id))

        await session.execute(delete(Client).where(Client.id == client_id))
        await session.commit()

        await event_publisher.publish(
            "identity.client.deleted.v1",
            {
                "client_id": str(client_id),
                "code": client.code,
                "organization_ids": [str(o) for o in org_ids],
                "actor_id": str(actor_id) if actor_id else None,
            },
        )

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
        if data.subscription_start is not None:
            client.subscription_start = data.subscription_start
        if data.subscription_end is not None:
            client.subscription_end = data.subscription_end
        if client.subscription_end < client.subscription_start:
            await session.rollback()
            raise InvalidSubscriptionWindowError()

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
