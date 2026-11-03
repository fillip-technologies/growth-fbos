"""One search over customers, leads, opportunities, quotations, contracts, invoices and payments.

Each kind is searched only when the caller may read its list, a few hits per kind, newest first.
Matching is case-insensitive "contains" on the names and numbers people type.
"""
import uuid
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from models.client import Client
from models.contract import Contract
from models.invoice import Invoice
from models.lead import Lead
from models.opportunity import Opportunity
from models.payment import Payment
from models.quotation import Quotation
from schemas.common import Money
from schemas.search import SearchHit, SearchResponse
from services.identity_client import Actor

# Who may find each kind: the read permission of its list.
SEARCH_PERMISSIONS = {
    "customer": "revenue.client.read",
    "lead": "revenue.lead.read",
    "opportunity": "revenue.opportunity.read",
    "quotation": "revenue.opportunity.read",
    "contract": "revenue.contract.read",
    "invoice": "revenue.invoice.read",
    "payment": "revenue.payment.read",
}
MIN_QUERY = 2


def _like(column, term: str):
    return func.lower(column).contains(term, autoescape=True)


def _money(amount, currency: Optional[str]) -> Optional[Money]:
    return Money(amount=float(amount), currency=currency or "INR") if amount is not None else None


class SearchService:
    @staticmethod
    async def search(session: AsyncSession, org_id: uuid.UUID, actor: Actor, q: str, per_type: int) -> SearchResponse:
        term = q.strip().lower()
        allowed = {kind for kind, code in SEARCH_PERMISSIONS.items() if actor.has(code)}
        not_searched = [kind for kind in SEARCH_PERMISSIONS if kind not in allowed]
        if len(term) < MIN_QUERY:
            return SearchResponse(q=q, data=[], not_searched=not_searched)

        hits: list[SearchHit] = []
        if "customer" in allowed:
            hits += await _customers(session, org_id, term, per_type)
        if "lead" in allowed:
            hits += await _leads(session, org_id, term, per_type)
        if "opportunity" in allowed:
            hits += await _opportunities(session, org_id, term, per_type)
        if "quotation" in allowed:
            hits += await _quotations(session, org_id, term, per_type)
        if "contract" in allowed:
            hits += await _contracts(session, org_id, term, per_type)
        if "invoice" in allowed:
            hits += await _invoices(session, org_id, term, per_type)
        if "payment" in allowed:
            hits += await _payments(session, org_id, term, per_type)
        return SearchResponse(q=q, data=hits, not_searched=not_searched)


async def _customers(session, org_id, term, limit) -> list[SearchHit]:
    rows = await session.execute(
        select(Client)
        .where(Client.organization_id == org_id, or_(_like(Client.name, term), _like(Client.legal_name, term), _like(Client.code, term), _like(Client.gstin, term)))
        .order_by(Client.name.asc())
        .limit(limit)
    )
    return [SearchHit(type="customer", id=c.id, title=c.name, subtitle=c.code, status=c.status) for c in rows.scalars()]


async def _leads(session, org_id, term, limit) -> list[SearchHit]:
    rows = await session.execute(
        select(Lead)
        .where(
            Lead.organization_id == org_id,
            or_(_like(Lead.name, term), _like(Lead.contact_name, term), _like(Lead.company_name, term), _like(Lead.contact_email, term)),
        )
        .order_by(Lead.created_at.desc())
        .limit(limit)
    )
    return [
        SearchHit(
            type="lead", id=lead.id, title=lead.contact_name or lead.company_name or lead.name,
            subtitle=" · ".join(filter(None, [lead.name, lead.company_name if lead.contact_name else None])), status=lead.status,
        )
        for lead in rows.scalars()
    ]


async def _opportunities(session, org_id, term, limit) -> list[SearchHit]:
    rows = await session.execute(
        select(Opportunity, Client.name)
        .join(Client, Client.id == Opportunity.client_id)
        .where(Opportunity.organization_id == org_id, or_(_like(Opportunity.name, term), _like(Client.name, term)))
        .limit(limit)
    )
    return [
        SearchHit(type="opportunity", id=o.id, title=o.name, subtitle=client_name, status=o.status, amount=_money(o.expected_value, o.currency))
        for o, client_name in rows.all()
    ]


async def _quotations(session, org_id, term, limit) -> list[SearchHit]:
    rows = await session.execute(
        select(Quotation, Client.name)
        .join(Client, Client.id == Quotation.client_id)
        .where(Client.organization_id == org_id, Quotation.status != "superseded", or_(_like(Quotation.quote_no, term), _like(Quotation.name, term)))
        .order_by(Quotation.created_at.desc())
        .limit(limit)
    )
    return [
        SearchHit(type="quotation", id=q.id, title=q.quote_no, subtitle=" · ".join(filter(None, [q.name, client_name])), status=q.status, amount=_money(q.grand_total, q.currency))
        for q, client_name in rows.all()
    ]


async def _contracts(session, org_id, term, limit) -> list[SearchHit]:
    rows = await session.execute(
        select(Contract, Client.name)
        .join(Client, Client.id == Contract.client_id)
        .where(Contract.organization_id == org_id, _like(Contract.contract_no, term))
        .order_by(Contract.start_date.desc())
        .limit(limit)
    )
    return [
        SearchHit(type="contract", id=c.id, title=c.contract_no, subtitle=client_name, status=c.status, amount=_money(c.total_value, c.currency))
        for c, client_name in rows.all()
    ]


async def _invoices(session, org_id, term, limit) -> list[SearchHit]:
    rows = await session.execute(
        select(Invoice, Client.name)
        .join(Client, Client.id == Invoice.client_id)
        .where(Invoice.organization_id == org_id, _like(Invoice.invoice_no, term))
        .order_by(Invoice.issue_date.desc())
        .limit(limit)
    )
    return [
        SearchHit(type="invoice", id=i.id, title=i.invoice_no, subtitle=client_name, status=i.status, amount=_money(i.grand_total, i.currency))
        for i, client_name in rows.all()
    ]


async def _payments(session, org_id, term, limit) -> list[SearchHit]:
    rows = await session.execute(
        select(Payment, Client.name)
        .join(Client, Client.id == Payment.client_id)
        .where(Payment.organization_id == org_id, or_(_like(Payment.receipt_no, term), _like(Payment.bank_reference, term)))
        .order_by(Payment.received_at.desc())
        .limit(limit)
    )
    return [
        SearchHit(type="payment", id=p.id, title=p.receipt_no, subtitle=client_name, status=p.status, amount=_money(p.amount, p.currency))
        for p, client_name in rows.all()
    ]
