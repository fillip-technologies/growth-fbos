import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ClientNotFoundError,
    InvalidStateTransitionError,
    LeadAlreadyClaimedError,
    LeadAssigneeNotAllowedError,
    LeadCallRequiredError,
    LeadNotClaimedError,
    LeadNotFoundError,
    LeadReopenNotAllowedError,
    NotLeadOwnerError,
    PreconditionRequiredError,
    VersionConflictError,
)
from models.activity import Activity
from models.client import Client, ClientContact
from models.deal import Deal
from models.lead import Lead, LeadEvent
from models.opportunity import Opportunity
from permissions import LEAD_ASSIGN, LEAD_WRITE
from schemas.activity import ActivityResponse
from schemas.common import PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.lead import (
    LeadCallCreate,
    LeadCreate,
    LeadDisqualify,
    LeadEventResponse,
    LeadQualifyRequest,
    LeadQualifyResult,
    LeadResponse,
    LeadTransfer,
    LeadUpdate,
)
from schemas.opportunity import UserRef, VerticalRef
from services.activity_service import format_activity_response
from services.client_service import ClientService
from services.identity_client import Actor, IdentityClient
from services.opportunity_service import format_opportunity_detail

LEAD_SUBJECT = "commercial.lead"
# Statuses a lead is still being worked in; converted and disqualified are closed.
OPEN_STATUSES = ("new", "contacted", "qualified")
OPEN_OPPORTUNITY = ("qualification", "proposal", "negotiation", "open")


def now_utc() -> datetime:
    """Stored without a zone, in UTC, like the rest of revenue's moments."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment


@dataclass(frozen=True)
class LeadCallResult:
    lead: LeadResponse
    activity: ActivityResponse


def merge_attributes(stored: Optional[dict], changes: dict) -> dict:
    """
    `changes` over the stored attributes, as a new dict: the JSON column only notices a new
    object, so a change made to the stored dict in place would silently not be saved. An empty
    value (None, "", []) removes the key.
    """
    merged = {**(stored or {}), **changes}
    return {key: value for key, value in merged.items() if value not in (None, "", [])}


def format_lead_response(lead: Lead) -> LeadResponse:
    score = None
    if lead.attributes and isinstance(lead.attributes, dict):
        score = lead.attributes.get("score")

    code = lead.name if lead.name.startswith("LD-") else f"LD-{str(lead.id)[:8].upper()}"

    return LeadResponse(
        id=lead.id,
        code=code,
        deal_id=getattr(lead, "deal_id", None),
        vertical=VerticalRef(id=lead.vertical_id, name="Vertical") if lead.vertical_id else None,
        status=lead.status,
        source=lead.source,
        campaign_ref=lead.company_ref,
        contact_name=lead.contact_name,
        contact_email=lead.contact_email,
        contact_phone=lead.contact_phone,
        company_name=lead.company_name,
        owner=UserRef(id=lead.owner_user_id, name="Assigned Owner") if lead.owner_user_id else None,
        score=score,
        client_id=lead.client_id,
        attributes=lead.attributes or {},
        next_follow_up_on=lead.next_follow_up_on,
        converted_at=lead.converted_at,
        converted_by_user_id=lead.converted_by_user_id,
        version=lead.version,
        created_at=lead.created_at,
    )


def record_event(
    session: AsyncSession,
    lead: Lead,
    event: str,
    actor_user_id: Optional[uuid.UUID],
    *,
    from_user_id: Optional[uuid.UUID] = None,
    to_user_id: Optional[uuid.UUID] = None,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    note: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> None:
    """One line of the lead's history; the caller flushes."""
    session.add(
        LeadEvent(
            organization_id=lead.organization_id,
            lead_id=lead.id,
            event=event,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at or now_utc(),
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
        )
    )


async def _lead_in_org(session: AsyncSession, org_id: uuid.UUID, lead_id: uuid.UUID) -> Lead:
    lead = (
        await session.execute(select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id))
    ).scalars().first()
    if not lead:
        raise LeadNotFoundError(str(lead_id))
    return lead


def _check_version(lead: Lead, if_match: Optional[str]) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    if lead.version != int(if_match.strip('"').replace("W/", "")):
        raise VersionConflictError(lead.version)


def _ensure_can_work(actor: Actor, lead: Lead) -> None:
    """A claimed lead is worked by the person handling it, or by someone who may assign leads."""
    if actor.has(LEAD_ASSIGN) or lead.owner_user_id == actor.user_id:
        return
    raise NotLeadOwnerError()


def _ensure_claimed_and_workable(actor: Actor, lead: Lead) -> None:
    if lead.owner_user_id is None:
        raise LeadNotClaimedError()
    _ensure_can_work(actor, lead)


async def _ensure_can_take_leads(identity: IdentityClient, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Leads go only to active people of the organization who may work them."""
    if not await identity.people(org_id, LEAD_WRITE, user_id):
        raise LeadAssigneeNotAllowedError(user_id)


async def next_lead_number(session: AsyncSession, org_id: uuid.UUID) -> int:
    count_res = await session.execute(
        select(func.count(Lead.id)).where(Lead.organization_id == org_id)
    )
    return (count_res.scalar_one() or 0) + 1


def lead_code(lead_number: int) -> str:
    return f"LD-{datetime.now(timezone.utc).year}-{lead_number:04d}"


async def _copy_lead_contact(session: AsyncSession, lead: Lead, client: Client) -> bool:
    """
    The person the lead came in with becomes one of the customer's contacts (the primary one
    if it has none yet), unless they are already there: the same email, or with no email the
    same name. Returns whether a contact was added.
    """
    name = (lead.contact_name or "").strip()
    email = (lead.contact_email or "").strip()
    if not name and not email:
        return False
    existing = list((await session.execute(select(ClientContact).where(ClientContact.client_id == client.id))).scalars())
    already = any(
        (c.email or "").strip().lower() == email.lower() if email else c.name.strip().lower() == name.lower()
        for c in existing
    )
    if already:
        return False
    session.add(
        ClientContact(
            client_id=client.id,
            name=name or email,
            email=email or None,
            phone=(lead.contact_phone or "").strip() or None,
            is_primary=not any(c.is_primary for c in existing),
        )
    )
    await session.flush()
    return True


class LeadService:
    @staticmethod
    async def list_leads(
        session: AsyncSession,
        org_id: uuid.UUID,
        status: Optional[str] = None,
        vertical_id: Optional[uuid.UUID] = None,
        owner_user_id: Optional[uuid.UUID] = None,
        source: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
        unclaimed: bool = False,
        follow_up_due: Optional[date] = None,
    ) -> PageResponse[LeadResponse]:
        query = select(Lead).where(Lead.organization_id == org_id)
        if status:
            query = query.where(Lead.status == status)
        if unclaimed:
            query = query.where(Lead.owner_user_id.is_(None), Lead.status.in_(OPEN_STATUSES))
        if follow_up_due:
            query = query.where(Lead.next_follow_up_on <= follow_up_due, Lead.status.in_(OPEN_STATUSES))
        if vertical_id:
            query = query.where(Lead.vertical_id == vertical_id)
        if owner_user_id:
            query = query.where(Lead.owner_user_id == owner_user_id)
        if source:
            query = query.where(Lead.source == source)

        # Newest first; the id breaks ties between leads added in the same second.
        after = decode_cursor(cursor) if cursor else {}
        if after.get("created_at") and after.get("id"):
            created_at, last_id = datetime.fromisoformat(after["created_at"]), uuid.UUID(after["id"])
            query = query.where(
                (Lead.created_at < created_at) | ((Lead.created_at == created_at) & (Lead.id < last_id))
            )

        query = query.order_by(Lead.created_at.desc(), Lead.id.desc()).limit(limit + 1)
        result = await session.execute(query)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            last = data_rows[-1]
            next_cursor = encode_cursor({"created_at": last.created_at.isoformat(), "id": str(last.id)})

        return PageResponse(
            data=[format_lead_response(ld) for ld in data_rows],
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def create_lead(
        session: AsyncSession,
        org_id: uuid.UUID,
        payload: LeadCreate,
        actor: Actor,
        identity: IdentityClient,
    ) -> LeadResponse:
        """
        A new lead, unclaimed unless someone is named: the person adding it, or anyone who may
        take leads when the actor may assign them.
        """
        owner_id = payload.owner_user_id
        if owner_id is not None and owner_id != actor.user_id:
            if not actor.has(LEAD_ASSIGN):
                raise NotLeadOwnerError()
            await _ensure_can_take_leads(identity, org_id, owner_id)

        lead = Lead(
            organization_id=org_id,
            vertical_id=payload.vertical_id,
            name=lead_code(await next_lead_number(session, org_id)),
            contact_name=payload.contact_name,
            contact_email=str(payload.contact_email) if payload.contact_email else None,
            contact_phone=payload.contact_phone,
            company_name=payload.company_name,
            company_ref=payload.campaign_ref,
            source=payload.source,
            owner_user_id=owner_id,
            status="new",
            attributes=payload.attributes or {},
            version=1,
        )
        if payload.created_on:
            lead.created_at = datetime.combine(payload.created_on, datetime.min.time())
        session.add(lead)
        await session.flush()
        record_event(session, lead, "created", actor.user_id, to_user_id=owner_id, to_status="new")
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def get_lead(
        session: AsyncSession,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> LeadResponse:
        res = await session.execute(
            select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id)
        )
        lead = res.scalars().first()
        if not lead:
            raise LeadNotFoundError(str(lead_id))
        return format_lead_response(lead)

    @staticmethod
    async def update_lead(
        session: AsyncSession,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: LeadUpdate,
        if_match: Optional[str] = None,
        actor: Optional[Actor] = None,
    ) -> LeadResponse:
        """A claimed lead's details are changed by whoever handles it, or a sales manager."""
        lead = await _lead_in_org(session, org_id, lead_id)
        _check_version(lead, if_match)
        if actor is not None and lead.owner_user_id is not None:
            _ensure_can_work(actor, lead)

        if payload.score is not None:
            lead.attributes = merge_attributes(lead.attributes, {"score": payload.score})

        if payload.attributes is not None:
            lead.attributes = merge_attributes(lead.attributes, payload.attributes)

        lead.version += 1
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def claim_lead(session: AsyncSession, org_id: uuid.UUID, lead_id: uuid.UUID, actor: Actor) -> LeadResponse:
        """
        The actor takes an unclaimed open lead. The first to claim it wins: the change applies
        only while nobody holds it, so a second person at the same moment is told it's taken.
        Claiming a lead you already hold changes nothing.
        """
        claimed = await session.execute(
            update(Lead)
            .where(
                Lead.id == lead_id,
                Lead.organization_id == org_id,
                Lead.owner_user_id.is_(None),
                Lead.status.in_(OPEN_STATUSES),
            )
            .values(owner_user_id=actor.user_id, version=Lead.version + 1)
            .execution_options(synchronize_session=False)
        )
        lead = (
            await session.execute(
                select(Lead)
                .where(Lead.id == lead_id, Lead.organization_id == org_id)
                .execution_options(populate_existing=True)
            )
        ).scalars().first()
        if not lead:
            raise LeadNotFoundError(str(lead_id))
        if claimed.rowcount == 1:
            record_event(session, lead, "claimed", actor.user_id, to_user_id=actor.user_id)
            await session.flush()
            return format_lead_response(lead)
        if lead.owner_user_id == actor.user_id:
            return format_lead_response(lead)
        if lead.owner_user_id is not None:
            raise LeadAlreadyClaimedError(lead.owner_user_id)
        raise InvalidStateTransitionError(lead.status, "claim")

    @staticmethod
    async def transfer_lead(
        session: AsyncSession,
        org_id: uuid.UUID,
        lead_id: uuid.UUID,
        payload: LeadTransfer,
        actor: Actor,
        identity: IdentityClient,
        if_match: Optional[str] = None,
    ) -> LeadResponse:
        """
        Hands the lead to someone who may take leads, or with nobody named back to the
        unclaimed leads. The person handling it may pass it on; anyone else needs to be able
        to assign leads. A converted lead stays with whoever won it.
        """
        lead = await _lead_in_org(session, org_id, lead_id)
        _check_version(lead, if_match)
        if lead.status == "converted":
            raise InvalidStateTransitionError(lead.status, "transfer")
        if lead.owner_user_id is None and not actor.has(LEAD_ASSIGN):
            raise NotLeadOwnerError()
        _ensure_can_work(actor, lead)
        if payload.to_user_id == lead.owner_user_id:
            raise InvalidStateTransitionError(lead.status, "transfer to the person already handling it")
        if payload.to_user_id is not None:
            await _ensure_can_take_leads(identity, org_id, payload.to_user_id)

        previous = lead.owner_user_id
        lead.owner_user_id = payload.to_user_id
        lead.version += 1
        record_event(
            session, lead, "transferred" if payload.to_user_id else "released", actor.user_id,
            from_user_id=previous, to_user_id=payload.to_user_id, note=payload.reason.strip(),
        )
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def log_call(
        session: AsyncSession,
        org_id: uuid.UUID,
        lead_id: uuid.UUID,
        payload: LeadCallCreate,
        actor: Actor,
    ) -> LeadCallResult:
        """
        A call with the lead, on its timeline as a new entry (nothing is overwritten). Its
        follow-up date becomes the lead's next follow-up; the first call moves a new lead to
        contacted, in the same transaction.
        """
        lead = await _lead_in_org(session, org_id, lead_id)
        if lead.status not in OPEN_STATUSES:
            raise InvalidStateTransitionError(lead.status, "log a call")
        _ensure_claimed_and_workable(actor, lead)

        occurred_at = _naive_utc(payload.occurred_at) if payload.occurred_at else now_utc()
        activity = Activity(
            organization_id=org_id,
            subject_type=LEAD_SUBJECT,
            subject_id=lead.id,
            activity_type="call",
            owner_user_id=actor.user_id,
            occurred_at=occurred_at,
            summary=payload.summary.strip(),
            requirements=_clean(payload.requirements),
            expectations=_clean(payload.expectations),
            next_action=_clean(payload.next_action),
            follow_up_on=payload.follow_up_on,
        )
        session.add(activity)
        lead.next_follow_up_on = payload.follow_up_on
        if lead.status == "new":
            lead.status = "contacted"
            record_event(session, lead, "contacted", actor.user_id, from_status="new", to_status="contacted")
        lead.version += 1
        await session.flush()
        return LeadCallResult(lead=format_lead_response(lead), activity=format_activity_response(activity))

    @staticmethod
    async def qualify_lead(
        session: AsyncSession,
        org_id: uuid.UUID,
        lead_id: uuid.UUID,
        payload: LeadQualifyRequest,
        actor: Actor,
        if_match: Optional[str] = None,
    ) -> LeadQualifyResult:
        """
        A contacted lead is worth pursuing: its customer (an existing one, or a new prospect,
        who becomes active when they accept a quotation) and an opportunity to work, owned by
        the person handling the lead. The lead becomes qualified; it is converted when the
        customer accepts a quotation. A lead marked qualified before calls were required can
        be finished the same way.
        """
        lead = await _lead_in_org(session, org_id, lead_id)
        _check_version(lead, if_match)
        if lead.status == "new":
            raise LeadCallRequiredError()
        if not (lead.status == "contacted" or (lead.status == "qualified" and lead.client_id is None)):
            raise InvalidStateTransitionError(lead.status, "qualify")
        _ensure_claimed_and_workable(actor, lead)

        # 1. Resolve or create client
        client_created = False
        if payload.existing_client_id:
            c_res = await session.execute(
                select(Client).where(Client.id == payload.existing_client_id, Client.organization_id == org_id)
            )
            client_entity = c_res.scalars().first()
            if not client_entity:
                raise ClientNotFoundError(str(payload.existing_client_id))
            client_resp = await ClientService.get_client(session, client_entity.id, org_id)
        elif payload.new_client:
            client_resp = await ClientService.create_client(session, org_id, payload.new_client, status="prospect")
            client_entity = await session.get(Client, client_resp.id)
            client_created = True
        else:
            raise ClientNotFoundError("Either existing_client_id or new_client must be provided")
        if await _copy_lead_contact(session, lead, client_entity):
            client_resp = await ClientService.get_client(session, client_entity.id, org_id)

        # 2. Create Deal
        deal = Deal(
            organization_id=org_id,
            name=payload.opportunity.name,
            status="open",
            owner_user_id=lead.owner_user_id,
        )
        session.add(deal)
        await session.flush()

        # 3. Create Opportunity; its value fills in from the proposal or quotation when not known yet.
        value = payload.opportunity.expected_value
        opp = Opportunity(
            organization_id=org_id,
            client_id=client_entity.id,
            deal_id=deal.id,
            lead_id=lead.id,
            name=payload.opportunity.name,
            status="qualification",
            probability=50,
            expected_value=value.amount if value else None,
            expected_close_date=payload.opportunity.expected_close_date,
            owner_user_id=lead.owner_user_id,
            version=1,
        )
        if value:
            opp.currency = value.currency
        session.add(opp)
        await session.flush()

        # 4. The lead is qualified
        previous_status = lead.status
        lead.status = "qualified"
        lead.client_id = client_entity.id
        lead.version += 1
        record_event(
            session, lead, "qualified", actor.user_id,
            from_status=previous_status, to_status="qualified", note=payload.opportunity.name,
        )
        await session.flush()

        return LeadQualifyResult(
            lead=format_lead_response(lead),
            client=client_resp,
            opportunity=format_opportunity_detail(opp, client_resp.name),
            client_created=client_created,
        )

    @staticmethod
    async def disqualify_lead(
        session: AsyncSession,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: LeadDisqualify,
        actor: Actor,
        if_match: Optional[str] = None,
    ) -> LeadResponse:
        """
        Closes an open lead with a reason. A claimed lead is closed by the person handling it
        (or a sales manager); an unclaimed one (spam, a duplicate) by anyone who works leads.
        A qualified lead's open opportunity is marked lost with it.
        """
        lead = await _lead_in_org(session, org_id, lead_id)
        _check_version(lead, if_match)
        if lead.status not in OPEN_STATUSES:
            raise InvalidStateTransitionError(lead.status, "disqualify")
        if lead.owner_user_id is not None:
            _ensure_can_work(actor, lead)

        reason = f"{payload.reason}: {payload.note}" if payload.note else payload.reason
        previous_status = lead.status
        lead.status = "disqualified"
        lead.loss_reason = reason
        lead.next_follow_up_on = None
        lead.version += 1

        opportunities = (
            await session.execute(
                select(Opportunity).where(
                    Opportunity.organization_id == org_id,
                    Opportunity.lead_id == lead.id,
                    Opportunity.status.in_(OPEN_OPPORTUNITY),
                )
            )
        ).scalars().all()
        for opp in opportunities:
            opp.status = "lost"
            opp.loss_reason = f"Lead disqualified: {reason}"[:512]
            opp.version += 1

        record_event(
            session, lead, "disqualified", actor.user_id, from_status=previous_status, to_status="disqualified", note=reason
        )
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def reopen_lead(
        session: AsyncSession, org_id: uuid.UUID, lead_id: uuid.UUID, actor: Actor, if_match: Optional[str] = None
    ) -> LeadResponse:
        """
        A disqualified lead back in play: contacted when a call was logged with it, else new.
        A lead that was qualified first already has a customer and a lost opportunity, so it
        isn't reopened; a new opportunity on the customer is the way back.
        """
        lead = await _lead_in_org(session, org_id, lead_id)
        _check_version(lead, if_match)
        if lead.status != "disqualified":
            raise InvalidStateTransitionError(lead.status, "reopen")
        if lead.client_id is not None:
            raise LeadReopenNotAllowedError()
        if lead.owner_user_id is not None:
            _ensure_can_work(actor, lead)

        called = (
            await session.execute(
                select(Activity.id).where(
                    Activity.organization_id == org_id,
                    Activity.subject_type == LEAD_SUBJECT,
                    Activity.subject_id == lead.id,
                    Activity.activity_type == "call",
                ).limit(1)
            )
        ).first()
        lead.status = "contacted" if called else "new"
        lead.loss_reason = None
        lead.version += 1
        record_event(session, lead, "reopened", actor.user_id, from_status="disqualified", to_status=lead.status)
        await session.flush()
        return format_lead_response(lead)

    @staticmethod
    async def list_events(session: AsyncSession, org_id: uuid.UUID, lead_id: uuid.UUID) -> list[LeadEventResponse]:
        """The lead's history, oldest first."""
        await _lead_in_org(session, org_id, lead_id)
        rows = (
            await session.execute(
                select(LeadEvent)
                .where(LeadEvent.organization_id == org_id, LeadEvent.lead_id == lead_id)
                .order_by(LeadEvent.occurred_at, LeadEvent.id)
            )
        ).scalars().all()
        return [
            LeadEventResponse(
                id=row.id,
                event=row.event,
                occurred_at=row.occurred_at,
                actor_user_id=row.actor_user_id,
                from_user_id=row.from_user_id,
                to_user_id=row.to_user_id,
                from_status=row.from_status,
                to_status=row.to_status,
                note=row.note,
            )
            for row in rows
        ]


async def convert_on_acceptance(
    session: AsyncSession, org_id: uuid.UUID, lead_id: Optional[uuid.UUID], actor_user_id: Optional[uuid.UUID]
) -> Optional[LeadResponse]:
    """
    The customer accepted a quotation on the lead's opportunity: the lead is converted, with
    when and who was handling it. Nothing happens for a lead already closed. Returns the lead
    when it changed.
    """
    if lead_id is None:
        return None
    lead = (
        await session.execute(select(Lead).where(Lead.id == lead_id, Lead.organization_id == org_id))
    ).scalars().first()
    if lead is None or lead.status not in OPEN_STATUSES:
        return None
    previous_status = lead.status
    lead.status = "converted"
    lead.converted_at = now_utc()
    lead.converted_by_user_id = lead.owner_user_id
    lead.next_follow_up_on = None
    lead.version += 1
    record_event(session, lead, "converted", actor_user_id, from_status=previous_status, to_status="converted")
    await session.flush()
    return format_lead_response(lead)


async def lead_of_opportunity(
    session: AsyncSession, org_id: uuid.UUID, opportunity_id: Optional[uuid.UUID]
) -> Optional[LeadResponse]:
    """The lead an opportunity came from, if any."""
    if opportunity_id is None:
        return None
    lead = (
        await session.execute(
            select(Lead)
            .join(Opportunity, Opportunity.lead_id == Lead.id)
            .where(Opportunity.id == opportunity_id, Opportunity.organization_id == org_id)
        )
    ).scalars().first()
    return format_lead_response(lead) if lead else None


def _clean(text: Optional[str]) -> Optional[str]:
    return (text or "").strip() or None
