"""
A quotation's history (quotation_events), and the lines it adds to its opportunity's timeline.

Every change of status writes one event. Those the salesperson tells the customer about, or
hears back from them, also write an activity on the opportunity: an `email` for a send, a
`note` for the rest, as emailing a quotation always has.
"""

from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.activity import Activity
from models.quotation import Quotation, QuotationEvent
from schemas.quotation import QuotationEventResponse

OPPORTUNITY_SUBJECT = "commercial.opportunity"
SENT_EVENTS = ("sent", "emailed")


def now_utc() -> datetime:
    """Stored without a zone, in UTC, like the rest of revenue's moments."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def label(quote: Quotation) -> str:
    return f"{quote.quote_no} rev {quote.revision_no}"


async def record(
    session: AsyncSession,
    org_id: uuid.UUID,
    quote: Quotation,
    event: str,
    actor_user_id: Optional[uuid.UUID],
    *,
    note: Optional[str] = None,
    data: Optional[dict] = None,
    timeline: Optional[str] = None,
    timeline_type: str = "note",
    occurred_at: Optional[datetime] = None,
) -> None:
    """One history event; with `timeline`, also that summary on the opportunity's timeline."""
    moment = occurred_at or now_utc()
    session.add(
        QuotationEvent(
            organization_id=org_id,
            quotation_id=quote.id,
            event=event,
            actor_user_id=actor_user_id,
            occurred_at=moment,
            note=note,
            data=data,
        )
    )
    # A timeline line needs someone it is by, and an opportunity to be on.
    if timeline and quote.opportunity_id and actor_user_id:
        session.add(
            Activity(
                organization_id=org_id,
                subject_type=OPPORTUNITY_SUBJECT,
                subject_id=quote.opportunity_id,
                activity_type=timeline_type,
                owner_user_id=actor_user_id,
                occurred_at=moment,
                summary=timeline,
                outcome=event,
            )
        )
    await session.flush()


async def list_events(session: AsyncSession, org_id: uuid.UUID, quotation_id: uuid.UUID) -> list[QuotationEventResponse]:
    """Oldest first, the order the history reads in."""
    rows = await session.execute(
        select(QuotationEvent)
        .where(QuotationEvent.organization_id == org_id, QuotationEvent.quotation_id == quotation_id)
        .order_by(QuotationEvent.occurred_at.asc(), QuotationEvent.id.asc())
    )
    return [
        QuotationEventResponse(
            id=row.id, event=row.event, occurred_at=row.occurred_at, actor_user_id=row.actor_user_id,
            note=row.note, data=row.data or {},
        )
        for row in rows.scalars()
    ]


async def last_sent_at(session: AsyncSession, quotation_id: uuid.UUID) -> Optional[datetime]:
    """When it last went to the customer: marked sent, or emailed (first or again)."""
    return (
        await session.execute(
            select(func.max(QuotationEvent.occurred_at)).where(
                QuotationEvent.quotation_id == quotation_id, QuotationEvent.event.in_(SENT_EVENTS)
            )
        )
    ).scalar()
