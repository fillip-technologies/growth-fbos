"""A deal's journey, read from any record on it.

The links already sit on the records: an opportunity names its lead, a quotation its opportunity,
a contract its opportunity and accepted quotation, an invoice its contract, a payment allocation
its invoice. From the record a page opens, walk up to the opportunity (or the highest record
there is), then down to everything made from it.

Stages the caller may not read are left empty and named in `hidden`.
"""
import uuid
from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ContractNotFoundError, InvoiceNotFoundError, LeadNotFoundError, OpportunityNotFoundError
from models.client import Client
from models.contract import Contract
from models.invoice import Invoice
from models.lead import Lead
from models.opportunity import Opportunity
from models.payment import Payment, PaymentAllocation
from models.quotation import Quotation
from schemas.common import Money
from schemas.journey import JourneyClient, JourneyRecord, JourneyResponse, JourneySubject, JourneyTotals
from services.identity_client import Actor
from services.quotation_service import get_quote_in_org

# Who may see each stage: the read permission of its list.
STAGE_PERMISSIONS = {
    "lead": "revenue.lead.read",
    "opportunity": "revenue.opportunity.read",
    "quotations": "revenue.opportunity.read",
    "contracts": "revenue.contract.read",
    "invoices": "revenue.invoice.read",
    "payments": "revenue.payment.read",
}
# The opportunity a lead most likely became, when it became several: a won one, then an open one.
OPPORTUNITY_PREFERENCE = {"won": 0, "open": 1, "qualification": 1, "proposal": 1, "negotiation": 1}
# Quotations a newer revision replaced are history, not a step.
HIDDEN_QUOTATIONS = ("superseded",)
# Invoices that don't bill anything (yet, or any more).
NOT_BILLED = ("draft", "cancelled")


def _money(amount, currency: Optional[str]) -> Optional[Money]:
    if amount is None:
        return None
    return Money(amount=float(amount), currency=currency or "INR")


def _lead_record(lead: Lead) -> JourneyRecord:
    return JourneyRecord(
        id=lead.id, number=lead.name, name=lead.contact_name or lead.company_name, status=lead.status,
        date=lead.created_at.date() if lead.created_at else None,
    )


def _opportunity_record(opp: Opportunity) -> JourneyRecord:
    return JourneyRecord(
        id=opp.id, name=opp.name, status=opp.status, amount=_money(opp.expected_value, opp.currency),
        date=opp.expected_close_date,
    )


def _quotation_record(quote: Quotation, accepted_ids: set[uuid.UUID]) -> JourneyRecord:
    return JourneyRecord(
        id=quote.id, number=quote.quote_no, name=quote.name, status=quote.status,
        amount=_money(quote.grand_total, quote.currency),
        date=quote.created_at.date() if quote.created_at else None,
        kind=f"R{quote.revision_no}" if quote.revision_no and quote.revision_no > 1 else None,
        is_main=quote.id in accepted_ids or bool(quote.is_main),
    )


def _contract_record(contract: Contract) -> JourneyRecord:
    return JourneyRecord(
        id=contract.id, number=contract.contract_no, status=contract.status,
        amount=_money(contract.total_value, contract.currency), date=contract.start_date,
    )


def _invoice_record(invoice: Invoice) -> JourneyRecord:
    return JourneyRecord(
        id=invoice.id, number=invoice.invoice_no, status=invoice.status,
        amount=_money(invoice.grand_total, invoice.currency), date=invoice.issue_date, kind=invoice.doc_type,
    )


def _payment_record(payment: Payment, applied: float) -> JourneyRecord:
    """A payment as far as it went to this journey's invoices (cash plus TDS withheld)."""
    return JourneyRecord(
        id=payment.id, number=payment.receipt_no, name=payment.method, status=payment.status,
        amount=_money(applied, payment.currency), date=payment.received_at.date() if payment.received_at else None,
    )


def _signed(invoice: Invoice) -> float:
    """What an invoice adds to what was billed: credit notes take it back."""
    total = float(invoice.grand_total or 0)
    return -abs(total) if invoice.doc_type == "credit_note" else total


class _Anchors:
    """The records the walk up found; each may be missing."""

    def __init__(self) -> None:
        self.lead: Optional[Lead] = None
        self.opportunity: Optional[Opportunity] = None
        self.quotation: Optional[Quotation] = None
        self.contract: Optional[Contract] = None
        self.invoice: Optional[Invoice] = None
        self.client_id: Optional[uuid.UUID] = None


class JourneyService:
    @staticmethod
    async def journey(
        session: AsyncSession, org_id: uuid.UUID, actor: Actor, subject_type: JourneySubject, subject_id: uuid.UUID,
    ) -> JourneyResponse:
        anchors = await _walk_up(session, org_id, subject_type, subject_id)
        can = {stage: actor.has(code) for stage, code in STAGE_PERMISSIONS.items()}

        opp = anchors.opportunity
        quotations = await _quotations(session, opp, anchors.quotation)
        contracts = await _contracts(session, org_id, opp, anchors.contract)
        accepted = {c.accepted_quotation_id for c in contracts if c.accepted_quotation_id}
        invoices = await _invoices(session, org_id, contracts, anchors.invoice)
        payments = await _payments(session, org_id, invoices)

        billed = [i for i in invoices if i.status not in NOT_BILLED]
        currency = next((i.currency for i in billed), None) or next((c.currency for c in contracts), "INR")
        received = sum(applied for _, applied in payments)
        totals = JourneyTotals(
            invoiced=Money(amount=sum(_signed(i) for i in billed), currency=currency),
            received=Money(amount=received, currency=currency),
            balance_due=Money(amount=sum(float(i.balance_due or 0) for i in billed if i.doc_type != "credit_note"), currency=currency),
        )
        client = await session.get(Client, anchors.client_id) if anchors.client_id else None

        return JourneyResponse(
            subject_type=subject_type,
            subject_id=subject_id,
            client=JourneyClient(id=client.id, name=client.name) if client and client.organization_id == org_id else None,
            lead=_lead_record(anchors.lead) if anchors.lead and can["lead"] else None,
            opportunity=_opportunity_record(opp) if opp and can["opportunity"] else None,
            quotations=[_quotation_record(q, accepted) for q in quotations] if can["quotations"] else [],
            contracts=[_contract_record(c) for c in contracts] if can["contracts"] else [],
            invoices=[_invoice_record(i) for i in invoices] if can["invoices"] else [],
            payments=[_payment_record(p, applied) for p, applied in payments] if can["payments"] else [],
            totals=totals if can["invoices"] else None,
            hidden=[stage for stage, allowed in can.items() if not allowed],
        )


async def _walk_up(session: AsyncSession, org_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID) -> _Anchors:
    """From the record asked for, up to its opportunity and lead. 404 when the record isn't the org's."""
    found = _Anchors()
    if subject_type == "lead":
        found.lead = _found(await _in_org(session, Lead, subject_id, org_id), LeadNotFoundError(str(subject_id)))
        found.opportunity = await _opportunity_of_lead(session, org_id, found.lead.id)
        found.client_id = found.lead.client_id
    elif subject_type == "opportunity":
        found.opportunity = _found(await _in_org(session, Opportunity, subject_id, org_id), OpportunityNotFoundError(str(subject_id)))
    elif subject_type == "quotation":
        found.quotation = await get_quote_in_org(session, org_id, subject_id)
        found.client_id = found.quotation.client_id
        if found.quotation.opportunity_id:
            found.opportunity = await _in_org(session, Opportunity, found.quotation.opportunity_id, org_id)
    elif subject_type == "contract":
        found.contract = _found(await _in_org(session, Contract, subject_id, org_id), ContractNotFoundError(str(subject_id)))
        await _up_from_contract(session, org_id, found)
    elif subject_type == "invoice":
        found.invoice = _found(await _in_org(session, Invoice, subject_id, org_id), InvoiceNotFoundError(str(subject_id)))
        found.client_id = found.invoice.client_id
        if found.invoice.contract_id:
            found.contract = await _in_org(session, Contract, found.invoice.contract_id, org_id)
        if found.contract:
            await _up_from_contract(session, org_id, found)

    if found.opportunity:
        found.client_id = found.opportunity.client_id
        if found.lead is None and found.opportunity.lead_id:
            found.lead = await _in_org(session, Lead, found.opportunity.lead_id, org_id)
    return found


async def _up_from_contract(session: AsyncSession, org_id: uuid.UUID, found: _Anchors) -> None:
    contract = found.contract
    found.client_id = contract.client_id
    if contract.opportunity_id:
        found.opportunity = await _in_org(session, Opportunity, contract.opportunity_id, org_id)
    if found.opportunity is None and contract.accepted_quotation_id:
        quote = await session.get(Quotation, contract.accepted_quotation_id)
        if quote and quote.client_id == contract.client_id:
            found.quotation = quote
            if quote.opportunity_id:
                found.opportunity = await _in_org(session, Opportunity, quote.opportunity_id, org_id)


def _found(record, error: Exception):
    """The record, or the not-found error when the walk couldn't find it in the organization."""
    if record is None:
        raise error
    return record


async def _in_org(session: AsyncSession, model, record_id: uuid.UUID, org_id: uuid.UUID):
    record = await session.get(model, record_id)
    return record if record is not None and record.organization_id == org_id else None


async def _opportunity_of_lead(session: AsyncSession, org_id: uuid.UUID, lead_id: uuid.UUID) -> Optional[Opportunity]:
    rows = (
        await session.execute(
            select(Opportunity).where(Opportunity.organization_id == org_id, Opportunity.lead_id == lead_id)
        )
    ).scalars().all()
    return min(rows, key=lambda o: OPPORTUNITY_PREFERENCE.get(o.status, 2), default=None)


async def _quotations(session: AsyncSession, opp: Optional[Opportunity], quotation: Optional[Quotation]) -> list[Quotation]:
    """The opportunity's current quotations (each option's latest revision); or the one asked for."""
    if opp is None:
        return [quotation] if quotation else []
    rows = (
        await session.execute(
            select(Quotation)
            .where(Quotation.opportunity_id == opp.id, Quotation.client_id == opp.client_id)
            .order_by(Quotation.created_at.asc())
        )
    ).scalars().all()
    return [q for q in rows if q.status not in HIDDEN_QUOTATIONS]


async def _contracts(
    session: AsyncSession, org_id: uuid.UUID, opp: Optional[Opportunity], contract: Optional[Contract],
) -> list[Contract]:
    if opp is None:
        return [contract] if contract else []
    rows = (
        await session.execute(
            select(Contract)
            .where(Contract.organization_id == org_id, Contract.opportunity_id == opp.id)
            .order_by(Contract.start_date.asc())
        )
    ).scalars().all()
    if contract and all(c.id != contract.id for c in rows):
        rows = [*rows, contract]
    return list(rows)


async def _invoices(
    session: AsyncSession, org_id: uuid.UUID, contracts: Iterable[Contract], invoice: Optional[Invoice],
) -> list[Invoice]:
    contract_ids = [c.id for c in contracts]
    if not contract_ids:
        return [invoice] if invoice else []
    rows = (
        await session.execute(
            select(Invoice)
            .where(Invoice.organization_id == org_id, Invoice.contract_id.in_(contract_ids))
            .order_by(Invoice.issue_date.is_(None), Invoice.issue_date.asc(), Invoice.created_at.asc())
        )
    ).scalars().all()
    if invoice and all(i.id != invoice.id for i in rows):
        rows = [*rows, invoice]
    return list(rows)


async def _payments(session: AsyncSession, org_id: uuid.UUID, invoices: Iterable[Invoice]) -> list[tuple[Payment, float]]:
    """Payments allocated to the invoices, with how much of each went to them (cash and TDS)."""
    invoice_ids = [i.id for i in invoices]
    if not invoice_ids:
        return []
    rows = (
        await session.execute(
            select(PaymentAllocation, Payment)
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(Payment.organization_id == org_id, PaymentAllocation.invoice_id.in_(invoice_ids))
            .order_by(Payment.received_at.asc())
        )
    ).all()
    applied: dict[uuid.UUID, float] = defaultdict(float)
    payments: dict[uuid.UUID, Payment] = {}
    for allocation, payment in rows:
        applied[payment.id] += float(allocation.amount or 0) + float(allocation.tds_amount or 0)
        payments[payment.id] = payment
    return [(payment, applied[pid]) for pid, payment in payments.items()]
