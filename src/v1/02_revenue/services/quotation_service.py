from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ChangeNoteRequiredError,
    InvalidStateTransitionError,
    OfferingNotFoundError,
    OpportunityNotFoundError,
    PreconditionRequiredError,
    QuotationFrozenError,
    QuotationNotFoundError,
    ValidityInPastError,
    VersionConflictError,
)
from finance import policies
from finance.money import ZERO, as_float, to_decimal
from finance.numbering import next_document_number
from finance.tax.store import load_snapshot
from models.client import Client
from models.document_tax import DocumentTaxLine
from models.offering import Offering
from models.opportunity import Opportunity
from models.quotation import NegotiationNote, Quotation, QuotationItem
from schemas.common import Money
from schemas.opportunity import ClientRef
from schemas.quotation import (
    QuotationChangeRequest,
    QuotationCreate,
    QuotationItemInput,
    QuotationItemResponse,
    QuotationItemsReplace,
    QuotationReject,
    QuotationResponse,
    QuotationTotals,
    QuotationValidityUpdate,
    QuotationWithdrawal,
)
from schemas.tax import LineTax, TaxAmount, WithholdingPreview
from services import quotation_events
from services.quotation_events import label, now_utc
from services.tax_service import (
    DocumentLineSpec,
    TaxCalculation,
    calculate_document,
    copy_tax_lines,
    legacy_rate,
    legacy_split,
    load_tax_lines,
    replace_tax_lines,
    totals_of,
    withholding_json,
)


QUOTATION_DOCUMENT = "quotation"  # DocumentTaxLine.document_type

# With the customer, waiting for their answer: these expire once past valid_until.
AWAITING_CUSTOMER = ("sent", "changes_requested")
# Still ours to take back.
WITHDRAWABLE = ("draft", "pending_approval", "approved", "sent", "changes_requested")
# Revising answers the customer: a new revision after they have seen this one.
REVISABLE = ("sent", "rejected", "changes_requested")
REJECTABLE = AWAITING_CUSTOMER
VALIDITY_EDITABLE = WITHDRAWABLE
WITHDRAWAL_REASONS = {
    "mistake": "sent by mistake",
    "price_change": "price change",
    "scope_change": "scope change",
    "customer_request": "customer's request",
    "other": "other",
}
# The open stages, in the order a deal moves through them.
OPEN_STAGES = ("open", "qualification", "proposal", "negotiation")


@dataclass(frozen=True)
class _QuotedItem:
    offering: Offering
    description: str
    spec: DocumentLineSpec


async def _quoted_items(session: AsyncSession, org_id: uuid.UUID, items: List[QuotationItemInput]) -> list[_QuotedItem]:
    offering_ids = {item.offering_id for item in items}
    rows = await session.execute(select(Offering).where(Offering.id.in_(offering_ids), Offering.organization_id == org_id))
    offerings = {offering.id: offering for offering in rows.scalars().all()}
    quoted = []
    for line_no, item in enumerate(items, start=1):
        offering = offerings.get(item.offering_id)
        if not offering:
            raise OfferingNotFoundError(str(item.offering_id))
        unit_price = item.unit_price.amount if item.unit_price is not None else (offering.list_price or 0)
        quoted.append(_QuotedItem(
            offering=offering,
            description=item.description or offering.name,
            spec=DocumentLineSpec(
                line_no=line_no,
                quantity=to_decimal(item.quantity),
                unit_price=to_decimal(unit_price),
                discount_percent=to_decimal(item.discount_pct),
                category_code=offering.tax_category_code,
                legacy_rate=None if offering.tax_category_code else legacy_rate(offering.gst_code),
                classification_code=offering.sac_code,
            ),
        ))
    return quoted


async def _stored_items_as_quoted(session: AsyncSession, org_id: uuid.UUID, items: list[QuotationItem]) -> list[_QuotedItem]:
    rows = await session.execute(
        select(Offering).where(Offering.id.in_({item.offering_id for item in items}), Offering.organization_id == org_id)
    )
    offerings = {offering.id: offering for offering in rows.scalars().all()}
    return [
        _QuotedItem(
            offering=offerings[item.offering_id],
            description=item.description or offerings[item.offering_id].name,
            spec=DocumentLineSpec(
                line_no=item.line_no,
                quantity=to_decimal(item.quantity),
                unit_price=to_decimal(item.unit_price),
                discount_percent=to_decimal(item.discount_pct),
                category_code=item.tax_category_code,
                classification_code=offerings[item.offering_id].sac_code,
            ),
        )
        for item in items
    ]


async def _calculate(
    session: AsyncSession, org_id: uuid.UUID, client: Client, quoted: list[_QuotedItem], quote: Quotation
) -> TaxCalculation:
    return await calculate_document(
        session, org_id, client, [item.spec for item in quoted], date.today(), QUOTATION_DOCUMENT, quote.currency,
        quote.tax_registration_id, quote.place_of_supply,
    )


async def _store_calculation(
    session: AsyncSession, org_id: uuid.UUID, quote: Quotation, quoted: list[_QuotedItem], calculation: TaxCalculation
) -> list[QuotationItem]:
    """Write totals, items and frozen tax lines from a calculation, replacing any previous ones."""
    result = calculation.result
    quote.tax_registration_id = calculation.registration.id
    quote.place_of_supply = result.place_of_supply or quote.place_of_supply
    quote.supply_type = result.supply_type
    quote.config_revision = result.config_revision
    quote.subtotal = result.subtotal
    quote.discount_total = result.discount_total
    quote.tax_total = result.tax_total
    quote.round_off = result.round_off
    quote.grand_total = result.grand_total
    quote.tax_notes = list(result.notes)
    quote.withholding = withholding_json(result)

    old_items = await session.execute(select(QuotationItem).where(QuotationItem.quotation_id == quote.id))
    for old_item in old_items.scalars().all():
        await session.delete(old_item)
    items = [
        QuotationItem(
            quotation_id=quote.id, offering_id=item.offering.id, line_no=line.line_no, description=item.description,
            quantity=item.spec.quantity, unit=item.offering.unit or "project", unit_price=item.spec.unit_price,
            discount_pct=item.spec.discount_percent, gst_rate=line.effective_percent, net_price=line.taxable_value,
            billing_model=item.offering.billing_model, line_total=line.line_total, tax_category_code=line.category_code,
        )
        for line, item in zip(result.lines, quoted)
    ]
    session.add_all(items)
    await replace_tax_lines(session, org_id, QUOTATION_DOCUMENT, quote.id, result)
    await session.flush()
    return items


def _money(amount, currency: str) -> Money:
    return Money(amount=as_float(to_decimal(amount)), currency=currency)


def is_expired(quote: Quotation, today: Optional[date] = None) -> bool:
    """Waiting for the customer past its valid-until date. Derived, never a stored status."""
    return (
        quote.status in AWAITING_CUSTOMER
        and quote.valid_until is not None
        and quote.valid_until < (today or date.today())
    )


def format_quotation_response(
    quote: Quotation,
    client: Client,
    items: List[QuotationItem],
    tax_lines: list[DocumentTaxLine],
    last_sent_at: Optional[datetime] = None,
) -> QuotationResponse:
    currency = quote.currency
    totals = totals_of(tax_lines)
    split = legacy_split(totals)
    item_responses = [
        QuotationItemResponse(
            line_no=item.line_no,
            offering_id=item.offering_id,
            description=item.description,
            quantity=float(item.quantity),
            unit=item.unit or "project",
            unit_price=_money(item.unit_price, currency),
            discount_pct=float(item.discount_pct),
            taxable_value=_money(item.net_price, currency),
            gst_rate=float(item.gst_rate),
            sac_code=None,
            line_total=_money(item.line_total, currency),
            tax_category_code=item.tax_category_code,
            taxes=[
                LineTax(component_code=tax.component_code, label=tax.label, behaviour=tax.behaviour,
                        rate=as_float(to_decimal(tax.rate_percent)), amount=_money(tax.tax_amount, currency),
                        base=_money(tax.base_amount, currency), rule_code=tax.rule_code)
                for tax in tax_lines
                if tax.line_no == item.line_no
            ],
        )
        for item in items
    ]
    withheld = sum((to_decimal(entry["amount"]) for entry in quote.withholding or []), ZERO)
    return QuotationResponse(
        id=quote.id,
        quote_no=quote.quote_no,
        revision_no=quote.revision_no,
        previous_revision_id=quote.previous_revision_id,
        opportunity_id=quote.opportunity_id,
        client=ClientRef(id=client.id, name=client.name),
        status=quote.status,
        valid_until=quote.valid_until,
        is_expired=is_expired(quote),
        status_note=quote.status_note,
        status_reason=quote.status_reason,
        currency=currency,
        place_of_supply=quote.place_of_supply or "",
        items=item_responses,
        totals=QuotationTotals(
            subtotal=_money(quote.subtotal, currency),
            discount_total=_money(quote.discount_total, currency),
            taxable_total=_money(to_decimal(quote.subtotal) - to_decimal(quote.discount_total), currency),
            cgst=_money(split["cgst"], currency),
            sgst=_money(split["sgst"], currency),
            igst=_money(split["igst"], currency),
            grand_total=_money(quote.grand_total, currency),
            taxes=[
                TaxAmount(component_code=total.component_code, label=total.label, behaviour=total.behaviour,
                          rate=as_float(total.percent), amount=_money(total.amount, currency))
                for total in totals
            ],
            tax_total=_money(quote.tax_total, currency),
            round_off=_money(quote.round_off, currency),
        ),
        approval_request_id=quote.approved_request_id,
        pdf_document_id=None,
        terms=quote.summary,
        sent_at=quote.sent_at,
        last_sent_at=last_sent_at or quote.sent_at,
        accepted_at=quote.completed_at if quote.status == "accepted" else None,
        version=quote.version,
        supply_type=quote.supply_type,
        tax_notes=list(quote.tax_notes or []),
        withholding=[
            WithholdingPreview(
                section_code=entry["section_code"], statute_ref=entry["statute_ref"], payment_code=entry.get("payment_code"),
                rate=float(entry["percent"]), base=_money(entry["base"], currency), amount=_money(entry["amount"], currency),
                certificate_no=entry.get("certificate_no"),
            )
            for entry in quote.withholding or []
        ],
        net_receivable=_money(to_decimal(quote.grand_total) - withheld, currency),
    )


async def _quote_number(session: AsyncSession, org_id: uuid.UUID, on: date) -> str:
    snapshot = await load_snapshot(session, org_id, on)
    settings = await policies.load_settings(session, org_id)

    async def numbers_used() -> list[str]:
        rows = await session.execute(
            select(Quotation.quote_no).join(Client, Client.id == Quotation.client_id).where(Client.organization_id == org_id)
        )
        return list(rows.scalars().all())

    _, number = await next_document_number(
        session, org_id, "quotation", on, snapshot, policies.fiscal_year_start(settings, None), numbers_used
    )
    return number


async def get_quote_in_org(session: AsyncSession, org_id: uuid.UUID, quotation_id: uuid.UUID) -> Quotation:
    """The quotation if it belongs to the organization (through its client), else 404."""
    res = await session.execute(
        select(Quotation)
        .join(Client, Client.id == Quotation.client_id)
        .where(Quotation.id == quotation_id, Client.organization_id == org_id)
    )
    quote = res.scalars().first()
    if not quote:
        raise QuotationNotFoundError(str(quotation_id))
    return quote


def _check_version(if_match: Optional[str], version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    if int(if_match.strip('"').replace("W/", "")) != version:
        raise VersionConflictError(version)


async def _advance_stage(session: AsyncSession, quote: Quotation, stage: str) -> None:
    """Moves the opportunity forward to `stage`, never back, and never once it is won or lost."""
    if not quote.opportunity_id:
        return
    opp = await session.get(Opportunity, quote.opportunity_id)
    if not opp or opp.status not in OPEN_STAGES or OPEN_STAGES.index(opp.status) >= OPEN_STAGES.index(stage):
        return
    opp.status = stage
    opp.version += 1


class QuotationService:
    @staticmethod
    async def create_quotation(
        session: AsyncSession,
        org_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        payload: QuotationCreate,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        opp_res = await session.execute(
            select(Opportunity).where(Opportunity.id == opportunity_id, Opportunity.organization_id == org_id)
        )
        opp = opp_res.scalars().first()
        if not opp:
            raise OpportunityNotFoundError(str(opportunity_id))

        client = await session.get(Client, opp.client_id)
        quoted = await _quoted_items(session, org_id, payload.items)

        quote = Quotation(
            opportunity_id=opp.id,
            client_id=client.id,
            quote_no=await _quote_number(session, org_id, date.today()),
            revision_no=1,
            currency="INR",
            summary=payload.terms,
            place_of_supply=payload.place_of_supply,
            tax_registration_id=payload.tax_registration_id,
            status="draft",
            valid_until=payload.valid_until,
            version=1,
        )
        if payload.created_on:
            quote.created_at = datetime.combine(payload.created_on, datetime.min.time())
        calculation = await _calculate(session, org_id, client, quoted, quote)
        session.add(quote)
        await session.flush()

        items = await _store_calculation(session, org_id, quote, quoted, calculation)
        await quotation_events.record(session, org_id, quote, "created", actor_user_id)
        return format_quotation_response(quote, client, items, await load_tax_lines(session, QUOTATION_DOCUMENT, [quote.id]))

    @staticmethod
    async def get_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> QuotationResponse:
        quote = await get_quote_in_org(session, org_id, quotation_id)

        client = await session.get(Client, quote.client_id)
        items_res = await session.execute(
            select(QuotationItem).where(QuotationItem.quotation_id == quotation_id).order_by(QuotationItem.line_no.asc())
        )
        items = list(items_res.scalars().all())

        return format_quotation_response(
            quote, client, items, await load_tax_lines(session, QUOTATION_DOCUMENT, [quote.id]),
            await quotation_events.last_sent_at(session, quote.id),
        )

    @staticmethod
    async def replace_quotation_items(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: QuotationItemsReplace,
        if_match: Optional[str] = None,
    ) -> QuotationResponse:
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if quote.status != "draft":
            raise QuotationFrozenError("replace items on", quote.status)

        client = await session.get(Client, quote.client_id)
        quoted = await _quoted_items(session, org_id, payload.items)
        calculation = await _calculate(session, org_id, client, quoted, quote)
        items = await _store_calculation(session, org_id, quote, quoted, calculation)
        quote.version += 1
        await session.flush()
        return format_quotation_response(quote, client, items, await load_tax_lines(session, QUOTATION_DOCUMENT, [quote.id]))

    @staticmethod
    async def submit_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if quote.status != "draft":
            raise InvalidStateTransitionError(quote.status, "submit")

        # Approval policy: if discount percentage > 20%, set pending_approval; otherwise approved immediately
        disc_pct = (float(quote.discount_total) / float(quote.subtotal) * 100.0) if quote.subtotal > 0 else 0.0
        if disc_pct > 20.0:
            quote.status = "pending_approval"
            quote.approved_request_id = uuid.uuid4()
        else:
            quote.status = "approved"

        quote.version += 1
        await quotation_events.record(session, org_id, quote, "submitted", actor_user_id, data={"status": quote.status})
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def send_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
        via_email: bool = False,
    ) -> QuotationResponse:
        """
        Marks the quotation sent. Emailing it records its own event and timeline line
        (`via_email`), so this one then records nothing.
        """
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if quote.status not in ("approved", "draft"):
            raise InvalidStateTransitionError(quote.status, "send")

        # What the customer receives is taxed as of the day it is sent, then frozen.
        client = await session.get(Client, quote.client_id)
        stored = await session.execute(
            select(QuotationItem).where(QuotationItem.quotation_id == quote.id).order_by(QuotationItem.line_no.asc())
        )
        quoted = await _stored_items_as_quoted(session, org_id, list(stored.scalars().all()))
        await _store_calculation(session, org_id, quote, quoted, await _calculate(session, org_id, client, quoted, quote))

        moment = now_utc()
        quote.status = "sent"
        quote.sent_at = quote.sent_at or moment
        quote.version += 1
        await _advance_stage(session, quote, "proposal")
        if not via_email:
            await quotation_events.record(
                session, org_id, quote, "sent", actor_user_id, occurred_at=moment,
                timeline=f"Marked quotation {label(quote)} as sent to the customer.",
            )
        await session.flush()
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def revise_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        """Revision N+1 as a draft, answering what the customer said; this one is superseded."""
        curr_quote = await get_quote_in_org(session, org_id, quotation_id)
        if curr_quote.status not in REVISABLE:
            raise InvalidStateTransitionError(curr_quote.status, "revise")

        client = await session.get(Client, curr_quote.client_id)
        old_items_res = await session.execute(
            select(QuotationItem).where(QuotationItem.quotation_id == quotation_id).order_by(QuotationItem.line_no.asc())
        )
        old_items = list(old_items_res.scalars().all())

        curr_quote.status = "superseded"
        curr_quote.version += 1
        await session.flush()

        new_rev = Quotation(
            opportunity_id=curr_quote.opportunity_id,
            client_id=curr_quote.client_id,
            previous_revision_id=curr_quote.id,
            quote_no=curr_quote.quote_no,
            revision_no=curr_quote.revision_no + 1,
            currency=curr_quote.currency,
            summary=curr_quote.summary,
            place_of_supply=curr_quote.place_of_supply,
            subtotal=curr_quote.subtotal,
            discount_total=curr_quote.discount_total,
            tax_total=curr_quote.tax_total,
            grand_total=curr_quote.grand_total,
            tax_registration_id=curr_quote.tax_registration_id,
            supply_type=curr_quote.supply_type,
            config_revision=curr_quote.config_revision,
            round_off=curr_quote.round_off,
            tax_notes=curr_quote.tax_notes,
            withholding=curr_quote.withholding,
            status="draft",
            valid_until=curr_quote.valid_until,
            version=1,
        )
        session.add(new_rev)
        await session.flush()

        persisted_items = []
        for it in old_items:
            new_item = QuotationItem(
                quotation_id=new_rev.id,
                offering_id=it.offering_id,
                line_no=it.line_no,
                description=it.description,
                quantity=it.quantity,
                unit=it.unit,
                unit_price=it.unit_price,
                discount_pct=it.discount_pct,
                gst_rate=it.gst_rate,
                net_price=it.net_price,
                billing_model=it.billing_model,
                line_total=it.line_total,
                tax_category_code=it.tax_category_code,
            )
            session.add(new_item)
            persisted_items.append(new_item)

        await session.flush()
        tax_lines = await copy_tax_lines(session, org_id, QUOTATION_DOCUMENT, curr_quote.id, new_rev.id)
        await _advance_stage(session, curr_quote, "negotiation")
        await quotation_events.record(
            session, org_id, curr_quote, "revised", actor_user_id,
            data={"revision_id": str(new_rev.id), "revision_no": new_rev.revision_no},
        )
        await quotation_events.record(
            session, org_id, new_rev, "created", actor_user_id,
            data={"revision_id": str(curr_quote.id), "revision_no": curr_quote.revision_no},
        )
        return format_quotation_response(new_rev, client, persisted_items, tax_lines)

    @staticmethod
    async def list_for_opportunity(
        session: AsyncSession,
        org_id: uuid.UUID,
        opportunity_id: uuid.UUID,
    ) -> List[QuotationResponse]:
        """Every revision quoted on the opportunity, newest first."""
        res = await session.execute(
            select(Quotation.id)
            .join(Client, Client.id == Quotation.client_id)
            .where(Quotation.opportunity_id == opportunity_id, Client.organization_id == org_id)
            .order_by(Quotation.revision_no.desc())
        )
        return [await QuotationService.get_quotation(session, qid, org_id) for qid in res.scalars().all()]

    @staticmethod
    async def approve_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        """Approve a quotation held for its discount (over 20%), so it can be sent."""
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)
        if quote.status != "pending_approval":
            raise InvalidStateTransitionError(quote.status, "approve")

        quote.status = "approved"
        quote.version += 1
        await quotation_events.record(session, org_id, quote, "approved", actor_user_id)
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def accept_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        """The customer agreed: the opportunity is won and a prospect becomes a customer. Expired is no bar."""
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if quote.status != "sent":
            raise InvalidStateTransitionError(quote.status, "accept")

        expired = is_expired(quote)
        quote.status = "accepted"
        quote.completed_at = now_utc()
        quote.version += 1

        if quote.opportunity_id:
            opp = await session.get(Opportunity, quote.opportunity_id)
            if opp:
                opp.status = "won"
                opp.version += 1

        # A prospect becomes a customer once it accepts a quotation.
        client = await session.get(Client, quote.client_id)
        if client and client.status == "prospect":
            client.status = "active"
            client.version += 1

        await quotation_events.record(
            session, org_id, quote, "accepted", actor_user_id,
            data={"expired": True} if expired else None,
            timeline=f"Customer accepted quotation {label(quote)}" + (" after its validity ran out." if expired else "."),
        )
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def reject_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: QuotationReject,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if quote.status not in REJECTABLE:
            raise InvalidStateTransitionError(quote.status, "reject")

        quote.status = "rejected"
        quote.status_note = payload.reason
        quote.status_reason = None
        quote.version += 1

        session.add(NegotiationNote(
            quotation_id=quote.id,
            summary=f"Quotation rejected by client: {payload.reason}",
            requested_changes=payload.reason,
            round_no=quote.revision_no,
        ))
        await quotation_events.record(
            session, org_id, quote, "rejected", actor_user_id, note=payload.reason,
            timeline=f"Customer rejected quotation {label(quote)}: {payload.reason}",
        )
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def request_changes(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: QuotationChangeRequest,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        """The customer replied asking for changes; a revision answers them."""
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if quote.status != "sent":
            raise InvalidStateTransitionError(quote.status, "request_changes")
        note = (payload.note or "").strip()
        if not note:
            raise ChangeNoteRequiredError()

        quote.status = "changes_requested"
        quote.status_note = note
        quote.status_reason = None
        quote.version += 1

        session.add(NegotiationNote(
            quotation_id=quote.id,
            summary=f"Customer asked for changes: {note}",
            requested_changes=note,
            round_no=quote.revision_no,
        ))
        await _advance_stage(session, quote, "negotiation")
        await quotation_events.record(
            session, org_id, quote, "changes_requested", actor_user_id, note=note,
            timeline=f"Customer asked for changes to quotation {label(quote)}: {note}",
        )
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def withdraw_quotation(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: QuotationWithdrawal,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        """We take the quotation back (a mistake, a wrong price, the deal changed)."""
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if quote.status not in WITHDRAWABLE:
            raise InvalidStateTransitionError(quote.status, "withdraw")

        note = (payload.note or "").strip() or None
        quote.status = "withdrawn"
        quote.status_reason = payload.reason
        quote.status_note = note
        quote.version += 1

        summary = f"Withdrew quotation {label(quote)} ({WITHDRAWAL_REASONS[payload.reason]})"
        await quotation_events.record(
            session, org_id, quote, "withdrawn", actor_user_id, note=note, data={"reason": payload.reason},
            timeline=f"{summary}: {note}" if note else f"{summary}.",
        )
        return await QuotationService.get_quotation(session, quotation_id, org_id)

    @staticmethod
    async def update_validity(
        session: AsyncSession,
        quotation_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: QuotationValidityUpdate,
        if_match: Optional[str] = None,
        actor_user_id: Optional[uuid.UUID] = None,
    ) -> QuotationResponse:
        """A new valid-until date, today or later, for a quotation still open. Its status stays."""
        quote = await get_quote_in_org(session, org_id, quotation_id)
        _check_version(if_match, quote.version)

        if payload.valid_until < date.today():
            raise ValidityInPastError(payload.valid_until.isoformat())
        if quote.status not in VALIDITY_EDITABLE:
            raise InvalidStateTransitionError(quote.status, "update_validity")

        previous = quote.valid_until
        quote.valid_until = payload.valid_until
        quote.version += 1

        # Only a change the customer has been told about belongs on the timeline.
        told = quote.status in AWAITING_CUSTOMER
        await quotation_events.record(
            session, org_id, quote, "validity_extended", actor_user_id,
            data={"from": previous.isoformat() if previous else None, "to": payload.valid_until.isoformat()},
            timeline=f"Quotation {label(quote)} is now valid until {payload.valid_until:%d %b %Y}." if told else None,
        )
        return await QuotationService.get_quotation(session, quotation_id, org_id)
