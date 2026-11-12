"""
Proposals: what we propose to do for the customer, before the priced quotation.

One proposal is open on an opportunity at a time: a draft, or sent and waiting for (or
discussing) the customer's answer. A sent version never changes; revising makes the next
version as a draft and the old one reads "Replaced by vN". Every change is a proposal event,
and what the customer is told or says is also a line on the opportunity's timeline.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    InvalidStateTransitionError,
    OfferingNotFoundError,
    OpportunityNotFoundError,
    PreconditionRequiredError,
    ProposalAlreadyOpenError,
    ProposalEmptyError,
    ProposalFrozenError,
    ProposalNotFoundError,
    VersionConflictError,
)
from finance.money import as_float, to_decimal
from models.activity import Activity
from models.client import Client
from models.offering import Offering
from models.opportunity import Opportunity
from models.proposal import Proposal, ProposalEvent, ProposalItem
from models.quotation import Quotation
from schemas.common import Money
from schemas.opportunity import ClientRef
from schemas.proposal import (
    ProposalCreate,
    ProposalEventResponse,
    ProposalItemInput,
    ProposalItemResponse,
    ProposalRef,
    ProposalResponse,
    ProposalUpdate,
)
from services import opportunity_stage
from services.opportunity_stage import OPEN_STAGES

OPPORTUNITY_SUBJECT = "commercial.opportunity"
LEAD_SUBJECT = "commercial.lead"
# Being worked on: only one of these per opportunity.
OPEN_PROPOSAL = ("draft", "sent", "under_discussion")
# With the customer, waiting for their answer.
AWAITING_CUSTOMER = ("sent", "under_discussion")
REVISABLE = ("sent", "under_discussion", "rejected")
EMAILABLE = ("draft", "sent", "under_discussion", "accepted")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def label(proposal: Proposal) -> str:
    return f"{proposal.proposal_no} v{proposal.version_no}"


def check_version(if_match: Optional[str], version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    if int(if_match.strip('"').replace("W/", "")) != version:
        raise VersionConflictError(version)


async def get_in_org(session: AsyncSession, org_id: uuid.UUID, proposal_id: uuid.UUID) -> Proposal:
    proposal = (
        await session.execute(select(Proposal).where(Proposal.id == proposal_id, Proposal.organization_id == org_id))
    ).scalar_one_or_none()
    if not proposal:
        raise ProposalNotFoundError(str(proposal_id))
    return proposal


async def record(
    session: AsyncSession,
    org_id: uuid.UUID,
    proposal: Proposal,
    event: str,
    actor_user_id: Optional[uuid.UUID],
    *,
    note: Optional[str] = None,
    data: Optional[dict] = None,
    timeline: Optional[str] = None,
    timeline_type: str = "note",
    occurred_at: Optional[datetime] = None,
) -> None:
    """One history event; with `timeline`, also that line on the opportunity's timeline."""
    moment = occurred_at or now_utc()
    session.add(ProposalEvent(
        organization_id=org_id, proposal_id=proposal.id, event=event, actor_user_id=actor_user_id,
        occurred_at=moment, note=note, data=data,
    ))
    if timeline and actor_user_id:
        session.add(Activity(
            organization_id=org_id, subject_type=OPPORTUNITY_SUBJECT, subject_id=proposal.opportunity_id,
            activity_type=timeline_type, owner_user_id=actor_user_id, occurred_at=moment, summary=timeline,
            outcome=event,
        ))
    await session.flush()


async def _items(session: AsyncSession, org_id: uuid.UUID, proposal: Proposal, given: list[ProposalItemInput]) -> list[ProposalItem]:
    """The services as proposal lines, each checked to be in the organization's catalog."""
    if not given:
        return []
    rows = await session.execute(
        select(Offering).where(Offering.id.in_({i.offering_id for i in given}), Offering.organization_id == org_id)
    )
    offerings = {o.id: o for o in rows.scalars()}
    lines = []
    for line_no, item in enumerate(given, start=1):
        offering = offerings.get(item.offering_id)
        if not offering:
            raise OfferingNotFoundError(str(item.offering_id))
        price = item.unit_price.amount if item.unit_price is not None else (offering.list_price or 0)
        lines.append(ProposalItem(
            proposal_id=proposal.id, offering_id=offering.id, line_no=line_no,
            description=(item.description or "").strip() or None, quantity=to_decimal(item.quantity),
            unit=offering.unit or "project", unit_price=to_decimal(price),
        ))
    return lines


def _total(items: list[ProposalItem]) -> Decimal:
    return sum((to_decimal(i.quantity) * to_decimal(i.unit_price) for i in items), Decimal(0)).quantize(Decimal("0.01"))


async def _replace_items(session: AsyncSession, org_id: uuid.UUID, proposal: Proposal, given: list[ProposalItemInput]) -> None:
    new_items = await _items(session, org_id, proposal, given)
    for old in (await session.execute(select(ProposalItem).where(ProposalItem.proposal_id == proposal.id))).scalars():
        await session.delete(old)
    await session.flush()
    session.add_all(new_items)
    proposal.total = _total(new_items)


async def item_responses(session: AsyncSession, proposal: Proposal) -> list[ProposalItemResponse]:
    rows = await session.execute(
        select(ProposalItem, Offering)
        .join(Offering, Offering.id == ProposalItem.offering_id)
        .where(ProposalItem.proposal_id == proposal.id)
        .order_by(ProposalItem.line_no.asc())
    )
    currency = proposal.currency
    return [
        ProposalItemResponse(
            line_no=item.line_no, offering_id=item.offering_id, offering_name=offering.name,
            description=item.description, quantity=float(item.quantity), unit=item.unit,
            unit_price=Money(amount=as_float(to_decimal(item.unit_price)), currency=currency),
            amount=Money(amount=as_float(to_decimal(item.quantity) * to_decimal(item.unit_price)), currency=currency),
        )
        for item, offering in rows.all()
    ]


async def to_response(session: AsyncSession, proposal: Proposal) -> ProposalResponse:
    client = await session.get(Client, proposal.client_id)
    replaced_by = (
        await session.execute(select(Proposal).where(Proposal.previous_version_id == proposal.id))
    ).scalars().first()
    quotation_id = (
        await session.execute(
            select(Quotation.id).where(Quotation.proposal_id == proposal.id).order_by(Quotation.created_at.desc())
        )
    ).scalars().first()
    return ProposalResponse(
        id=proposal.id, opportunity_id=proposal.opportunity_id, client=ClientRef(id=client.id, name=client.name),
        proposal_no=proposal.proposal_no, version_no=proposal.version_no,
        previous_version_id=proposal.previous_version_id,
        replaced_by=ProposalRef(id=replaced_by.id, version_no=replaced_by.version_no) if replaced_by else None,
        title=proposal.title, requirements=proposal.requirements, scope=proposal.scope, timeline=proposal.timeline,
        terms=proposal.terms, currency=proposal.currency,
        total=Money(amount=as_float(to_decimal(proposal.total or 0)), currency=proposal.currency),
        status=proposal.status, revision_note=proposal.revision_note, customer_feedback=proposal.customer_feedback,
        sent_at=proposal.sent_at, decided_at=proposal.decided_at, pdf_document_id=proposal.pdf_document_id,
        pdf_version_no=proposal.pdf_version_no, quotation_id=quotation_id,
        created_by_user_id=proposal.created_by_user_id, created_at=proposal.created_at, version=proposal.version,
        items=await item_responses(session, proposal),
    )


async def _lead_requirements(session: AsyncSession, org_id: uuid.UUID, opp: Opportunity) -> Optional[str]:
    """What the customer said they need on the lead's calls, oldest first: the draft's starting point."""
    if not opp.lead_id:
        return None
    rows = await session.execute(
        select(Activity.requirements)
        .where(
            Activity.organization_id == org_id,
            Activity.subject_type == LEAD_SUBJECT,
            Activity.subject_id == opp.lead_id,
            Activity.requirements.is_not(None),
        )
        .order_by(Activity.occurred_at.asc())
    )
    found = [text.strip() for text in rows.scalars() if text and text.strip()]
    return "\n\n".join(dict.fromkeys(found)) or None


async def _next_number(session: AsyncSession, org_id: uuid.UUID) -> str:
    """PRP-<year>-<nnnn>, counting the organization's proposals this year (versions share a number)."""
    year = now_utc().year
    prefix = f"PRP-{year}-"
    used = (
        await session.execute(
            select(func.count(func.distinct(Proposal.proposal_no))).where(
                Proposal.organization_id == org_id, Proposal.proposal_no.like(f"{prefix}%")
            )
        )
    ).scalar_one()
    return f"{prefix}{used + 1:04d}"


async def _open_opportunity(session: AsyncSession, org_id: uuid.UUID, opportunity_id: uuid.UUID) -> Opportunity:
    opp = (
        await session.execute(
            select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.organization_id == org_id)
        )
    ).scalar_one_or_none()
    if not opp:
        raise OpportunityNotFoundError(str(opportunity_id))
    return opp


async def create(
    session: AsyncSession, org_id: uuid.UUID, opportunity_id: uuid.UUID, payload: ProposalCreate,
    actor_user_id: uuid.UUID,
) -> Proposal:
    opp = await _open_opportunity(session, org_id, opportunity_id)
    if opp.status not in OPEN_STAGES:
        raise InvalidStateTransitionError(opp.status, "add_proposal")
    already = (
        await session.execute(
            select(Proposal).where(Proposal.opportunity_id == opp.id, Proposal.status.in_(OPEN_PROPOSAL))
        )
    ).scalars().first()
    if already:
        raise ProposalAlreadyOpenError(already.id, label(already))

    proposal = Proposal(
        id=uuid.uuid4(), organization_id=org_id, opportunity_id=opp.id, client_id=opp.client_id,
        proposal_no=await _next_number(session, org_id), version_no=1,
        title=(payload.title or "").strip() or f"Proposal for {opp.name}",
        requirements=payload.requirements if payload.requirements is not None else await _lead_requirements(session, org_id, opp),
        scope=payload.scope, timeline=payload.timeline, terms=payload.terms, currency=opp.currency or "INR",
        status="draft", created_by_user_id=actor_user_id, created_at=now_utc(), version=1, total=0,
    )
    session.add(proposal)
    await session.flush()
    await _replace_items(session, org_id, proposal, payload.items)
    await record(session, org_id, proposal, "created", actor_user_id)
    return proposal


async def list_for_opportunity(session: AsyncSession, org_id: uuid.UUID, opportunity_id: uuid.UUID) -> list[ProposalResponse]:
    """Newest proposal first, its latest version first."""
    await _open_opportunity(session, org_id, opportunity_id)
    rows = await session.execute(
        select(Proposal)
        .where(Proposal.opportunity_id == opportunity_id, Proposal.organization_id == org_id)
        .order_by(Proposal.proposal_no.desc(), Proposal.version_no.desc())
    )
    return [await to_response(session, p) for p in rows.scalars().all()]


async def update(
    session: AsyncSession, org_id: uuid.UUID, proposal_id: uuid.UUID, payload: ProposalUpdate,
    actor_user_id: uuid.UUID, if_match: Optional[str],
) -> Proposal:
    proposal = await get_in_org(session, org_id, proposal_id)
    check_version(if_match, proposal.version)
    if proposal.status != "draft":
        raise ProposalFrozenError(proposal.status)

    given = payload.model_dump(exclude_unset=True)
    changed = []
    for field in ("title", "requirements", "scope", "timeline", "terms"):
        if field in given:
            value = (given[field] or "").strip() or None
            if field == "title" and not value:
                continue
            if value != getattr(proposal, field):
                setattr(proposal, field, value)
                changed.append(field)
    if payload.items is not None:
        await _replace_items(session, org_id, proposal, payload.items)
        changed.append("items")
    if changed:
        proposal.version += 1
        await record(session, org_id, proposal, "edited", actor_user_id, data={"fields": changed})
    return proposal


async def _sync_expected_value(session: AsyncSession, proposal: Proposal) -> None:
    """Until a quotation prices the deal, the proposal's estimate is the opportunity's value."""
    opp = await session.get(Opportunity, proposal.opportunity_id)
    if not opp or opp.status not in OPEN_STAGES or not proposal.total:
        return
    quoted = (
        await session.execute(select(Quotation.id).where(Quotation.opportunity_id == opp.id, Quotation.is_main.is_(True)))
    ).scalars().first()
    if quoted:
        return
    opp.expected_value = to_decimal(proposal.total)
    opp.currency = proposal.currency
    opp.version += 1


async def ensure_sendable(session: AsyncSession, proposal: Proposal) -> None:
    """Something to propose: a scope of work or a service (the requirements alone come from the calls)."""
    if (proposal.scope or "").strip():
        return
    has_item = (
        await session.execute(select(ProposalItem.id).where(ProposalItem.proposal_id == proposal.id).limit(1))
    ).scalar_one_or_none()
    if not has_item:
        raise ProposalEmptyError()


async def mark_sent(
    session: AsyncSession, org_id: uuid.UUID, proposal: Proposal, actor_user_id: uuid.UUID, *, timeline: Optional[str],
) -> None:
    """A draft goes to the customer: frozen from now on. Emailing records its own timeline line."""
    if proposal.status != "draft":
        raise InvalidStateTransitionError(proposal.status, "send")
    moment = now_utc()
    proposal.status = "sent"
    proposal.sent_at = moment
    proposal.version += 1
    await opportunity_stage.advance(session, proposal.opportunity_id, "proposal")
    await _sync_expected_value(session, proposal)
    await record(session, org_id, proposal, "sent", actor_user_id, occurred_at=moment, timeline=timeline)


async def request_changes(
    session: AsyncSession, org_id: uuid.UUID, proposal_id: uuid.UUID, feedback: str, actor_user_id: uuid.UUID,
    if_match: Optional[str],
) -> Proposal:
    """The customer came back with feedback: under discussion, perhaps to be revised."""
    proposal = await get_in_org(session, org_id, proposal_id)
    check_version(if_match, proposal.version)
    if proposal.status not in AWAITING_CUSTOMER:
        raise InvalidStateTransitionError(proposal.status, "request_changes")
    note = feedback.strip()
    proposal.status = "under_discussion"
    proposal.customer_feedback = note
    proposal.version += 1
    await opportunity_stage.advance(session, proposal.opportunity_id, "negotiation")
    await record(
        session, org_id, proposal, "changes_requested", actor_user_id, note=note,
        timeline=f"Customer's feedback on proposal {label(proposal)}: {note}",
    )
    return proposal


async def revise(
    session: AsyncSession, org_id: uuid.UUID, proposal_id: uuid.UUID, note: Optional[str], actor_user_id: uuid.UUID,
) -> Proposal:
    """The next version, as a draft with this one's content; this one is replaced by it."""
    current = await get_in_org(session, org_id, proposal_id)
    if current.status not in REVISABLE:
        raise InvalidStateTransitionError(current.status, "revise")
    reason = (note or "").strip() or current.customer_feedback

    current.status = "superseded"
    current.version += 1
    await session.flush()

    new = Proposal(
        id=uuid.uuid4(), organization_id=org_id, opportunity_id=current.opportunity_id, client_id=current.client_id,
        proposal_no=current.proposal_no, version_no=current.version_no + 1, previous_version_id=current.id,
        title=current.title, requirements=current.requirements, scope=current.scope, timeline=current.timeline,
        terms=current.terms, currency=current.currency, total=current.total, status="draft",
        revision_note=reason, created_by_user_id=actor_user_id, created_at=now_utc(), version=1,
    )
    session.add(new)
    await session.flush()
    old_items = (
        await session.execute(select(ProposalItem).where(ProposalItem.proposal_id == current.id).order_by(ProposalItem.line_no))
    ).scalars().all()
    session.add_all(
        ProposalItem(
            proposal_id=new.id, offering_id=i.offering_id, line_no=i.line_no, description=i.description,
            quantity=i.quantity, unit=i.unit, unit_price=i.unit_price,
        )
        for i in old_items
    )
    await record(
        session, org_id, current, "revised", actor_user_id, note=reason,
        data={"proposal_id": str(new.id), "version_no": new.version_no},
    )
    await record(
        session, org_id, new, "created", actor_user_id, note=reason,
        data={"proposal_id": str(current.id), "version_no": current.version_no},
    )
    return new


async def decide(
    session: AsyncSession, org_id: uuid.UUID, proposal_id: uuid.UUID, accepted: bool, note: Optional[str],
    actor_user_id: uuid.UUID, if_match: Optional[str],
) -> Proposal:
    """The customer's answer. Accepted, the quotation is made from it; rejected, it can be revised."""
    proposal = await get_in_org(session, org_id, proposal_id)
    check_version(if_match, proposal.version)
    action = "accept" if accepted else "reject"
    if proposal.status not in AWAITING_CUSTOMER:
        raise InvalidStateTransitionError(proposal.status, action)
    text = (note or "").strip() or None
    proposal.status = "accepted" if accepted else "rejected"
    proposal.decided_at = now_utc()
    if text:
        proposal.customer_feedback = text
    proposal.version += 1
    verb = "accepted" if accepted else "rejected"
    await record(
        session, org_id, proposal, verb, actor_user_id, note=text,
        timeline=f"Customer {verb} proposal {label(proposal)}" + (f": {text}" if text else "."),
    )
    return proposal


async def list_events(session: AsyncSession, org_id: uuid.UUID, proposal_id: uuid.UUID) -> list[ProposalEventResponse]:
    await get_in_org(session, org_id, proposal_id)
    rows = await session.execute(
        select(ProposalEvent)
        .where(ProposalEvent.organization_id == org_id, ProposalEvent.proposal_id == proposal_id)
        .order_by(ProposalEvent.occurred_at.asc(), ProposalEvent.id.asc())
    )
    return [
        ProposalEventResponse(
            id=e.id, event=e.event, occurred_at=e.occurred_at, actor_user_id=e.actor_user_id, note=e.note, data=e.data or {},
        )
        for e in rows.scalars()
    ]
