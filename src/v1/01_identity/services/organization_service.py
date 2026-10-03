from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ClientNotFoundError,
    ClientOrganizationLimitReachedError,
    OrganizationNotFoundError,
    OrgCodeAlreadyExistsError,
    UserAlreadyExistsError,
)
from models.auth import UserCredential
from models.client import Client
from models.organization import Organization
from models.rbac import Permission, Role, RoleAssignment, RolePermission
from models.user import User
from models.user_permission import UserPermission
from schemas.common import PageInfo, PaginatedResponse
from schemas.organization import (
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
)
from services.event_publisher import event_publisher
from services.permission_catalog import ADMIN_ROLE_CODE, MEMBER_ROLE_CODE, member_permission_codes

logger = logging.getLogger("identity.organization_service")

_INVITATION_TTL_HOURS = 72

# One pending event to publish once the surrounding transaction commits.
PendingEvent = tuple[str, dict]


class OrganizationService:
    def _build_response(self, org: Organization) -> OrganizationResponse:
        return OrganizationResponse(
            id=org.id,
            client_id=org.client_id,
            name=org.name,
            code=org.code,
            email=org.email,
            base_currency=org.base_currency,
            fiscal_year_start=org.fiscal_year_start,
            timezone=org.timezone,
            status=org.status,
            created_at=org.created_at.isoformat() if org.created_at else None,
        )

    async def bootstrap_org(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        admin_user_id: Optional[uuid.UUID] = None,
    ) -> None:
        """
        Give a freshly created organization a usable RBAC baseline.

        A new org has no roles, so without this its first admin would hold zero
        permissions and could not manage anything. Creates a system `admin` role
        (wired to the whole permission catalog) and a `member` role (read-only),
        then optionally grants `admin` to the org's first user.

        Only permission codes that already exist in the catalog are wired up, so
        this never violates the RolePermission -> Permission foreign key.
        """
        catalog_codes = list((await session.execute(select(Permission.code))).scalars().all())
        member_codes = member_permission_codes(catalog_codes)

        admin_role = Role(
            id=uuid.uuid4(),
            organization_id=organization_id,
            code=ADMIN_ROLE_CODE,
            name="System Administrator",
            is_system=True,
            version=1,
        )
        member_role = Role(
            id=uuid.uuid4(),
            organization_id=organization_id,
            code=MEMBER_ROLE_CODE,
            name="Standard Member",
            is_system=False,
            version=1,
        )
        session.add_all([admin_role, member_role])
        await session.flush()

        for code in catalog_codes:
            session.add(RolePermission(role_id=admin_role.id, permission_code=code))
        for code in member_codes:
            session.add(RolePermission(role_id=member_role.id, permission_code=code))

        if admin_user_id is not None:
            # Access is user-based: the first admin receives the admin preset's
            # permissions directly; the assignment records which preset was applied.
            session.add(
                RoleAssignment(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    user_id=admin_user_id,
                    role_id=admin_role.id,
                    granted_by_id=admin_user_id,
                    reason="First administrator of the organization",
                )
            )
            for code in catalog_codes:
                session.add(UserPermission(
                    id=uuid.uuid4(),
                    organization_id=organization_id,
                    user_id=admin_user_id,
                    permission_code=code,
                    source_role_id=admin_role.id,
                    self_only=False,
                ))
        await session.flush()

    async def _invite_first_admin(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        email: str,
        name: Optional[str],
        user_type: str,
    ) -> tuple[User, str]:
        """Create a pending (invited) admin user with an invitation token."""
        normalized_email = email.lower()
        existing = await session.execute(
            select(User).where(func.lower(User.email) == normalized_email)
        )
        if existing.scalar_one_or_none():
            raise UserAlreadyExistsError()

        now = datetime.now(timezone.utc)
        user = User(
            id=uuid.uuid4(),
            organization_id=organization_id,
            email=normalized_email,
            name=name or normalized_email,
            user_type=user_type,
            status="invited",
            version=1,
            created_at=now,
        )
        session.add(user)
        await session.flush()

        invitation_token = f"inv_{secrets.token_urlsafe(24)}"
        session.add(
            UserCredential(
                user_id=user.id,
                password_hash="",  # set when the invitation is accepted
                invitation_token=invitation_token,
                invitation_token_expires_at=now + timedelta(hours=_INVITATION_TTL_HOURS),
            )
        )
        await session.flush()
        return user, invitation_token

    async def provision_organization(
        self,
        session: AsyncSession,
        client_id: uuid.UUID,
        data: OrganizationCreateRequest,
        admin_user_type: str = "employee",
        actor_id: Optional[uuid.UUID] = None,
    ) -> tuple[Organization, list[PendingEvent]]:
        """
        Insert an organization, its RBAC baseline, and (optionally) its first admin
        within the caller's transaction. Does NOT commit — the caller owns the
        commit so a client + its first org can be created atomically. Returns the
        org plus the domain events to publish after commit.
        """
        client = await session.get(Client, client_id)
        if not client:
            raise ClientNotFoundError()

        # Quota check: ensure client has not exceeded max_organizations
        if client.max_organizations is not None:
            active_orgs_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Organization)
                    .where(
                        Organization.client_id == client_id,
                        Organization.status != "deleted",
                    )
                )
            ).scalar_one()
            if active_orgs_count >= client.max_organizations:
                raise ClientOrganizationLimitReachedError(
                    limit=client.max_organizations, current=active_orgs_count
                )

        duplicate = await session.execute(
            select(Organization).where(func.lower(Organization.code) == data.code.lower())
        )
        if duplicate.scalar_one_or_none():
            raise OrgCodeAlreadyExistsError(data.code)

        org = Organization(
            id=uuid.uuid4(),
            client_id=client_id,
            name=data.name,
            code=data.code,
            email=data.email,
            base_currency=data.base_currency,
            fiscal_year_start=data.fiscal_year_start,
            timezone=data.timezone,
            status="active",
        )
        session.add(org)
        await session.flush()

        events: list[PendingEvent] = []

        admin_user_id: Optional[uuid.UUID] = None
        if data.admin_email:
            admin_user, invitation_token = await self._invite_first_admin(
                session=session,
                organization_id=org.id,
                email=data.admin_email,
                name=data.admin_name,
                user_type=admin_user_type,
            )
            admin_user_id = admin_user.id
            events.append((
                "identity.user.invited.v1",
                {
                    "user_id": str(admin_user.id),
                    "organization_id": str(org.id),
                    "email": admin_user.email,
                    "name": admin_user.name,
                    "organization_name": org.name,
                    "invitation_token": invitation_token,
                    "user_type": admin_user.user_type,
                    "actor_id": str(actor_id) if actor_id else None,
                },
            ))

        await self.bootstrap_org(session, org.id, admin_user_id=admin_user_id)

        events.insert(0, (
            "identity.organization.created.v1",
            {
                "organization_id": str(org.id),
                "client_id": str(client_id),
                "code": org.code,
                "name": org.name,
                "actor_id": str(actor_id) if actor_id else None,
            },
        ))
        return org, events

    async def create_organization(
        self,
        session: AsyncSession,
        client_id: uuid.UUID,
        data: OrganizationCreateRequest,
        admin_user_type: str = "employee",
        actor_id: Optional[uuid.UUID] = None,
    ) -> OrganizationResponse:
        org, events = await self.provision_organization(
            session=session,
            client_id=client_id,
            data=data,
            admin_user_type=admin_user_type,
            actor_id=actor_id,
        )
        await session.commit()
        await session.refresh(org)

        for topic, payload in events:
            await event_publisher.publish(topic, payload)

        return self._build_response(org)

    async def list_organizations(
        self,
        session: AsyncSession,
        client_id: uuid.UUID,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[OrganizationResponse]:
        query = (
            select(Organization)
            .where(Organization.client_id == client_id)
            .order_by(Organization.created_at.desc(), Organization.id.desc())
        )

        offset = int(cursor) if cursor and cursor.isdigit() else 0
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        orgs = list(result.scalars().all())

        has_more = len(orgs) > limit
        if has_more:
            orgs = orgs[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        return PaginatedResponse(
            data=[self._build_response(o) for o in orgs],
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def get_organization(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> OrganizationResponse:
        org = await session.get(Organization, organization_id)
        if not org or org.client_id != client_id:
            raise OrganizationNotFoundError()
        return self._build_response(org)

    async def update_organization(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        client_id: uuid.UUID,
        data: OrganizationUpdateRequest,
    ) -> OrganizationResponse:
        org = await session.get(Organization, organization_id)
        if not org or org.client_id != client_id:
            raise OrganizationNotFoundError()

        if data.name is not None:
            org.name = data.name
        if data.email is not None:
            org.email = data.email
        if data.base_currency is not None:
            org.base_currency = data.base_currency
        if data.fiscal_year_start is not None:
            org.fiscal_year_start = data.fiscal_year_start
        if data.timezone is not None:
            org.timezone = data.timezone
        if data.status is not None:
            org.status = data.status

        await session.commit()
        await session.refresh(org)

        await event_publisher.publish(
            "identity.organization.updated.v1",
            {"organization_id": str(org.id), "client_id": str(client_id)},
        )
        return self._build_response(org)


organization_service = OrganizationService()
