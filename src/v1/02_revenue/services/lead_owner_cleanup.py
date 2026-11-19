"""
One-off clean-up for leads saved before a lead could wait unclaimed: a lead added without an
owner was given a random id that matches nobody. Open leads whose owner is not an active person
of their organization (identity's /internal/people) are put back with the unclaimed leads, each
with a `released` line in its history. Closed leads (converted, disqualified) keep their owner
as history. Run by `unclaim_unknown_owners.py`.
"""

from dataclasses import dataclass, field
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.lead import Lead
from services.identity_client import IdentityClient
from services.lead_service import OPEN_STATUSES, record_event

NOTE = "Owner was not a person in FBOS (saved before leads could wait unclaimed)"


@dataclass
class CleanupReport:
    checked: int = 0
    # owner id -> how many of its open leads go back to the unclaimed leads
    unknown_owners: dict[uuid.UUID, int] = field(default_factory=dict)

    @property
    def unclaimed(self) -> int:
        return sum(self.unknown_owners.values())


async def unclaim_unknown_owners(
    session: AsyncSession, identity: IdentityClient, organization_id: uuid.UUID | None, apply: bool
) -> CleanupReport:
    """Reports, and with `apply` changes, open leads whose owner is no active person of their organization."""
    query = select(Lead).where(Lead.owner_user_id.is_not(None), Lead.status.in_(OPEN_STATUSES))
    if organization_id:
        query = query.where(Lead.organization_id == organization_id)
    leads = list((await session.execute(query)).scalars())

    report = CleanupReport(checked=len(leads))
    people_by_org: dict[uuid.UUID, set[uuid.UUID]] = {}
    for lead in leads:
        if lead.organization_id not in people_by_org:
            people = await identity.people(lead.organization_id, None)
            people_by_org[lead.organization_id] = {person.id for person in people}
        if lead.owner_user_id in people_by_org[lead.organization_id]:
            continue
        report.unknown_owners[lead.owner_user_id] = report.unknown_owners.get(lead.owner_user_id, 0) + 1
        if apply:
            record_event(session, lead, "released", None, from_user_id=lead.owner_user_id, note=NOTE)
            lead.owner_user_id = None
            lead.version += 1

    if apply:
        await session.commit()
    return report
