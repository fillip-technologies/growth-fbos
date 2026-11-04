"""Revenue, money owed, pipeline and AMC for one organization over a period (the CEO Command Center).

A handful of GROUP BY queries; nothing is loaded row by row. Revenue follows the same rule as
Management's actuals (services/revenue_rules.py), so the two never disagree.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client
from models.client_tax_profile import ClientTaxProfile
from models.contract import Contract
from models.invoice import Invoice, InvoiceLine
from models.offering import Offering
from models.opportunity import Opportunity
from models.renewal import Renewal
from schemas.business_summary import (
    AmcSummary,
    AmountBucket,
    ClientCounts,
    Period,
    RevenueBusinessSummary,
    SegmentAmount,
    SegmentCount,
    StateCount,
)
from schemas.summary import MonthAmount
from services.revenue_rules import NEGATIVE_DOC_TYPES, REVENUE_DOC_TYPES, UNISSUED_STATUSES
from services.summary_service import RECEIVABLE_STATUSES, _main_currency, _money, _month_of

AMC_CONTRACT_TYPE = "amc"
RENEWAL_WINDOW_DAYS = 30
# The pipeline is every opportunity not yet won or lost: the open stages plus older statuses
# outside the stage list, which the opportunity summary counts as "proposal".
CLOSED_STAGES = ("won", "lost")
NONE_KEY = "none"
HOME_COUNTRY = "IN"
GOVERNMENT_CLIENT_TYPE = "government"


def previous_period(from_date: date, to_date: date) -> tuple[date, date]:
    """The same number of days immediately before the period."""
    days = (to_date - from_date).days + 1
    return from_date - timedelta(days=days), from_date - timedelta(days=1)


def months_between(from_date: date, to_date: date) -> list[str]:
    """Every YYYY-MM from the period's first month to its last, oldest first."""
    keys, year, month = [], from_date.year, from_date.month
    while (year, month) <= (to_date.year, to_date.month):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return keys


def _signed(amount_column):
    """A document's amount, negative for a credit note."""
    return case((Invoice.doc_type.in_(NEGATIVE_DOC_TYPES), -amount_column), else_=amount_column)


def _earned_in(org_id: uuid.UUID, from_date: date, to_date: date) -> tuple:
    return (
        Invoice.organization_id == org_id,
        Invoice.doc_type.in_(REVENUE_DOC_TYPES),
        Invoice.status.not_in(UNISSUED_STATUSES),
        Invoice.issue_date >= from_date,
        Invoice.issue_date <= to_date,
    )


def _buckets(rows, currency: str) -> list[AmountBucket]:
    totals: dict[str, Decimal] = {}
    for key, amount in rows:
        name = str(key) if key else NONE_KEY
        totals[name] = totals.get(name, Decimal(0)) + Decimal(str(amount or 0))
    ordered = sorted(totals.items(), key=lambda item: -item[1])
    return [AmountBucket(key=key, amount=_money(amount, currency)) for key, amount in ordered]


class BusinessSummaryService:
    @staticmethod
    async def revenue(
        session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date, today: Optional[date] = None
    ) -> RevenueBusinessSummary:
        today = today or date.today()
        previous_from, previous_to = previous_period(from_date, to_date)
        currency, mixed = await _main_currency(session, Invoice, org_id, Invoice.doc_type.in_(REVENUE_DOC_TYPES))
        earned = _earned_in(org_id, from_date, to_date)
        signed_taxable = func.coalesce(func.sum(_signed(Invoice.taxable_total)), 0)

        revenue = await _scalar(session, select(signed_taxable).where(*earned))
        revenue_previous = await _scalar(
            session, select(signed_taxable).where(*_earned_in(org_id, previous_from, previous_to))
        )
        receivables, overdue = await _receivables(session, org_id, today)

        return RevenueBusinessSummary(
            currency=currency,
            mixed_currencies=mixed,
            period=Period(from_date=from_date, to_date=to_date),
            previous_period=Period(from_date=previous_from, to_date=previous_to),
            revenue=_money(revenue, currency),
            revenue_previous=_money(revenue_previous, currency),
            receivables=_money(receivables, currency),
            overdue=_money(overdue, currency),
            pipeline=_money(await _pipeline(session, org_id), currency),
            clients=await _client_counts(session, org_id),
            revenue_by_month=await _by_month(session, earned, from_date, to_date, currency),
            revenue_by_vertical=_buckets(await _by_vertical(session, org_id, earned), currency),
            revenue_by_state=_buckets(
                (await session.execute(
                    select(Invoice.place_of_supply, signed_taxable).where(*earned).group_by(Invoice.place_of_supply)
                )).all(),
                currency,
            ),
            revenue_by_client_type=_buckets(
                (await session.execute(
                    select(Client.client_type, signed_taxable)
                    .join(Client, Client.id == Invoice.client_id)
                    .where(*earned)
                    .group_by(Client.client_type)
                )).all(),
                currency,
            ),
            revenue_by_contract_type=_buckets(
                (await session.execute(
                    select(Contract.contract_type, signed_taxable)
                    .outerjoin(Contract, Contract.id == Invoice.contract_id)
                    .where(*earned)
                    .group_by(Contract.contract_type)
                )).all(),
                currency,
            ),
            revenue_by_segment=await _revenue_by_segment(session, earned, currency),
            revenue_by_product_line=_buckets(await _by_product_line(session, org_id, earned), currency),
            clients_by_segment=await _clients_by_segment(session, org_id),
            clients_by_state=await _clients_by_state(session, org_id),
            revenue_by_work_unit=_buckets(
                (await session.execute(
                    select(Invoice.work_unit_id, signed_taxable)
                    .where(*earned, Invoice.work_unit_id.is_not(None))
                    .group_by(Invoice.work_unit_id)
                )).all(),
                currency,
            ),
            amc=await _amc(session, org_id, earned, today, currency),
        )


async def _scalar(session: AsyncSession, statement) -> Decimal:
    return Decimal(str((await session.execute(statement)).scalar() or 0))


async def _receivables(session: AsyncSession, org_id: uuid.UUID, today: date) -> tuple[Decimal, Decimal]:
    owed = (
        Invoice.organization_id == org_id,
        Invoice.doc_type.not_in(NEGATIVE_DOC_TYPES),
        Invoice.status.in_(RECEIVABLE_STATUSES),
        Invoice.balance_due > 0,
    )
    balance = func.coalesce(func.sum(Invoice.balance_due), 0)
    outstanding = await _scalar(session, select(balance).where(*owed))
    overdue = await _scalar(session, select(balance).where(*owed, Invoice.due_date < today))
    return outstanding, overdue


async def _pipeline(session: AsyncSession, org_id: uuid.UUID) -> Decimal:
    return await _scalar(
        session,
        select(func.coalesce(func.sum(Opportunity.expected_value), 0)).where(
            Opportunity.organization_id == org_id, Opportunity.status.not_in(CLOSED_STAGES)
        ),
    )


async def _client_counts(session: AsyncSession, org_id: uuid.UUID) -> ClientCounts:
    rows = (
        await session.execute(
            select(Client.status, func.count()).where(Client.organization_id == org_id).group_by(Client.status)
        )
    ).all()
    counts = {status: int(count) for status, count in rows}
    return ClientCounts(total=sum(counts.values()), active=counts.get("active", 0))


async def _by_month(session: AsyncSession, earned: tuple, from_date: date, to_date: date, currency: str) -> list[MonthAmount]:
    rows = (
        await session.execute(
            select(Invoice.issue_date, func.count(), func.coalesce(func.sum(_signed(Invoice.taxable_total)), 0))
            .where(*earned)
            .group_by(Invoice.issue_date)
        )
    ).all()
    per_month: dict[str, list] = {}
    for day, count, amount in rows:
        month = per_month.setdefault(_month_of(day), [0, Decimal(0)])
        month[0] += int(count)
        month[1] += Decimal(str(amount))
    return [
        MonthAmount(month=key, count=per_month.get(key, [0])[0], amount=_money(per_month.get(key, [0, 0])[1], currency))
        for key in months_between(from_date, to_date)
    ]


async def _by_vertical(session: AsyncSession, org_id: uuid.UUID, earned: tuple) -> list:
    """Line by line: an invoice may bill offerings of several verticals."""
    return (
        await session.execute(
            select(Offering.vertical_id, func.coalesce(func.sum(_signed(InvoiceLine.taxable_value)), 0))
            .select_from(InvoiceLine)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .outerjoin(Offering, (Offering.id == InvoiceLine.offering_id) & (Offering.organization_id == org_id))
            .where(*earned)
            .group_by(Offering.vertical_id)
        )
    ).all()


async def _amc(session: AsyncSession, org_id: uuid.UUID, earned: tuple, today: date, currency: str) -> AmcSummary:
    active_amc = (
        Contract.organization_id == org_id,
        Contract.contract_type == AMC_CONTRACT_TYPE,
        Contract.status == "active",
    )
    count, value, clients = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Contract.total_value), 0),
                func.count(func.distinct(Contract.client_id)),
            ).where(*active_amc)
        )
    ).one()
    renewals_due = (
        await session.execute(
            select(func.count())
            .select_from(Renewal)
            .join(Contract, Contract.id == Renewal.contract_id)
            .where(
                Contract.organization_id == org_id,
                Renewal.status == "pending",
                Renewal.date >= today,
                Renewal.date <= today + timedelta(days=RENEWAL_WINDOW_DAYS),
            )
        )
    ).scalar()
    amc_revenue = await _scalar(
        session,
        select(func.coalesce(func.sum(_signed(Invoice.taxable_total)), 0))
        .join(Contract, Contract.id == Invoice.contract_id)
        .where(*earned, Contract.contract_type == AMC_CONTRACT_TYPE),
    )
    return AmcSummary(
        active_contracts=int(count),
        active_value=_money(value, currency),
        clients=int(clients),
        renewals_due=int(renewals_due or 0),
        revenue=_money(amc_revenue, currency),
    )


def _sector():
    return case((Client.client_type == GOVERNMENT_CLIENT_TYPE, "government"), else_="private")


def _market():
    """India or abroad: the tax profile's country first, else the billing address's (the tax engine's rule)."""
    country = func.coalesce(ClientTaxProfile.country, Client.country, HOME_COUNTRY)
    return case((func.upper(country) == HOME_COUNTRY, "india"), else_="international")


async def _revenue_by_segment(session: AsyncSession, earned: tuple, currency: str) -> list[SegmentAmount]:
    rows = (
        await session.execute(
            select(_sector(), _market(), func.coalesce(func.sum(_signed(Invoice.taxable_total)), 0))
            .select_from(Invoice)
            .join(Client, Client.id == Invoice.client_id)
            .outerjoin(ClientTaxProfile, ClientTaxProfile.client_id == Client.id)
            .where(*earned)
            .group_by(_sector(), _market())
        )
    ).all()
    ordered = sorted(rows, key=lambda row: -Decimal(str(row[2] or 0)))
    return [SegmentAmount(sector=sector, market=market, amount=_money(amount, currency)) for sector, market, amount in ordered]


async def _by_product_line(session: AsyncSession, org_id: uuid.UUID, earned: tuple) -> list:
    return (
        await session.execute(
            select(Offering.product_line, func.coalesce(func.sum(_signed(InvoiceLine.taxable_value)), 0))
            .select_from(InvoiceLine)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .outerjoin(Offering, (Offering.id == InvoiceLine.offering_id) & (Offering.organization_id == org_id))
            .where(*earned)
            .group_by(Offering.product_line)
        )
    ).all()


async def _clients_by_segment(session: AsyncSession, org_id: uuid.UUID) -> list[SegmentCount]:
    rows = (
        await session.execute(
            select(_sector(), _market(), func.count())
            .select_from(Client)
            .outerjoin(ClientTaxProfile, ClientTaxProfile.client_id == Client.id)
            .where(Client.organization_id == org_id)
            .group_by(_sector(), _market())
        )
    ).all()
    return [SegmentCount(sector=sector, market=market, count=int(count)) for sector, market, count in sorted(rows, key=lambda r: -r[2])]


async def _clients_by_state(session: AsyncSession, org_id: uuid.UUID) -> list[StateCount]:
    rows = (
        await session.execute(
            select(Client.state_code, func.count()).where(Client.organization_id == org_id).group_by(Client.state_code)
        )
    ).all()
    return [StateCount(key=state or NONE_KEY, count=int(count)) for state, count in sorted(rows, key=lambda r: -r[1])]
