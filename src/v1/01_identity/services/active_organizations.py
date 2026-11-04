"""
Every active organization of every active client, for background jobs that work per company
with no user signed in (the gateway's nightly CEO Command Center snapshots).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client
from models.organization import Organization
from schemas.organization import ActiveOrganization

ACTIVE = "active"


async def active_organizations(session: AsyncSession) -> list[ActiveOrganization]:
    rows = (
        await session.execute(
            select(Organization.id, Organization.client_id, Organization.name, Organization.relationship)
            .join(Client, Client.id == Organization.client_id)
            .where(Organization.status == ACTIVE, Client.status == ACTIVE)
            .order_by(Organization.client_id, Organization.name)
        )
    ).all()
    return [
        ActiveOrganization(id=row.id, client_id=row.client_id, name=row.name, relationship=row.relationship)
        for row in rows
    ]
