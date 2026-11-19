"""The one-off that puts leads whose owner is nobody back with the unclaimed leads."""

import uuid

import pytest
from sqlalchemy import select

from models.lead import Lead, LeadEvent
from services.lead_owner_cleanup import unclaim_unknown_owners
from tests.conftest import TEST_ORG_ID, TEST_USER_ID, FakeIdentity

pytestmark = pytest.mark.asyncio


async def test_report_first_then_apply(db_session):
    nobody = uuid.uuid4()
    real = Lead(organization_id=TEST_ORG_ID, name="LD-1", owner_user_id=TEST_USER_ID, status="contacted", version=1)
    orphan = Lead(organization_id=TEST_ORG_ID, name="LD-2", owner_user_id=nobody, status="new", version=1)
    closed = Lead(organization_id=TEST_ORG_ID, name="LD-3", owner_user_id=nobody, status="converted", version=1)
    db_session.add_all([real, orphan, closed])
    await db_session.commit()
    identity = FakeIdentity()
    identity.allowed = {TEST_USER_ID: "Test Admin"}

    report = await unclaim_unknown_owners(db_session, identity, None, apply=False)
    assert (report.checked, report.unknown_owners) == (2, {nobody: 1})
    await db_session.refresh(orphan)
    assert orphan.owner_user_id == nobody  # a report changes nothing

    await unclaim_unknown_owners(db_session, identity, None, apply=True)
    await db_session.refresh(orphan)
    await db_session.refresh(closed)
    assert (orphan.owner_user_id, closed.owner_user_id) == (None, nobody)
    [event] = (await db_session.execute(select(LeadEvent).where(LeadEvent.lead_id == orphan.id))).scalars().all()
    assert (event.event, event.from_user_id, event.actor_user_id) == ("released", nobody, None)

    again = await unclaim_unknown_owners(db_session, identity, None, apply=True)
    assert again.unclaimed == 0
    assert identity.asked[-1] == (None, None)  # every active person, whatever their access
