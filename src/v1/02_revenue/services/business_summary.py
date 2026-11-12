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
    TopProduct,
    UnitCount,
    WorkUnitSegment,
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
HARDWARE_PRODUCT_LINE = "hardware"
TOP_PRODUCTS = 10
# Business segments (CEO design gaps plan, decision D5): every invoice line lands in the first one
# it matches. "associate" (a project given to an associate company) is decided by the gateway, which
# knows those projects from Delivery; the rest are decided here, in this order.
ASSOCIATE_SEGMENT = "associate"
BUSINESS_SEGMENTS = (
    ASSOCIATE_SEGMENT,
    "amc_hardware",
    "amc_services",
    "hardware_sales",
    "government_india",
    "government_international",
    "private_india",
    "private_international",
    "other",
)


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


def _totals(rows) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for key, amount in rows:
        name = str(key) if key else NONE_KEY
        totals[name] = totals.get(name, Decimal(0)) + Decimal(str(amount or 0))
    return totals


def _buckets(rows, currency: str) -> list[AmountBucket]:
    ordered = sorted(_totals(rows).items(), key=lambda item: -item[1])
    return [AmountBucket(key=key, amount=_money(amount, currency)) for key, amount in ordered]


def _buckets_with_previous(rows, previous_rows, currency: str) -> list[AmountBucket]:
    """Every key of either period, largest first; a key only the previous period had shows 0 now."""
    current, previous = _totals(rows), _totals(previous_rows)
    keys = sorted(current.keys() | previous.keys(), key=lambda key: (-current.get(key, 0), -previous.get(key, 0), key))
    return [
        AmountBucket(
            key=key,
            amount=_money(current.get(key, 0), currency),
            previous=_money(previous.get(key, 0), currency),
        )
        for key in keys
    ]


def business_segment(contract_type: Optional[str], product_line: Optional[str], sector: Optional[str], market: str) -> str:
    """The segment of one invoice line, the first that matches (BUSINESS_SEGMENTS, after "associate").
    `sector` is None when the invoice names no customer."""
    if contract_type == AMC_CONTRACT_TYPE:
        return "amc_hardware" if product_line == HARDWARE_PRODUCT_LINE else "amc_services"
    if product_line == HARDWARE_PRODUCT_LINE:
        return "hardware_sales"
    if sector is None:
        return "other"
    return f"{sector}_{market}"


class BusinessSummaryService:
    @staticmethod
    async def revenue(
        session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date, today: Optional[date] = None
    ) -> RevenueBusinessSummary:
        today = today or date.today()
        previous_from, previous_to = previous_period(from_date, to_date)
        currency, mixed = await _main_currency(session, Invoice, org_id, Invoice.doc_type.in_(REVENUE_DOC_TYPES))
        earned = _earned_in(org_id, from_date, to_date)
        earned_previous = _earned_in(org_id, previous_from, previous_to)
        signed_taxable = func.coalesce(func.sum(_signed(Invoice.taxable_total)), 0)

        revenue = await _scalar(session, select(signed_taxable).where(*earned))
        revenue_previous = await _scalar(session, select(signed_taxable).where(*earned_previous))
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
            revenue_by_state=_buckets_with_previous(
                await _by_state(session, earned), await _by_state(session, earned_previous), currency
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
            revenue_by_product_line=_buckets_with_previous(
                await _by_product_line(session, org_id, earned),
                await _by_product_line(session, org_id, earned_previous),
                currency,
            ),
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
            amc=await _amc(session, org_id, earned, earned_previous, today, currency),
            hardware_units=UnitCount(
                amount=await _hardware_units(session, org_id, earned),
                previous=await _hardware_units(session, org_id, earned_previous),
            ),
            top_products=await _top_products(session, org_id, earned, currency),
            **await _business_segments(session, org_id, earned, currency),
        )

    @staticmethod
    async def client_states(session: AsyncSession, org_id: uuid.UUID, client_ids: list[uuid.UUID]) -> dict[str, Optional[str]]:
        """The GST state of each of these customers of the organization; other ids are left out."""
        if not client_ids:
            return {}
        rows = (
            await session.execute(
                select(Client.id, Client.state_code).where(Client.organization_id == org_id, Client.id.in_(client_ids))
            )
        ).all()
        return {str(client_id): state_code for client_id, state_code in rows}


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


async def _amc(
    session: AsyncSession, org_id: uuid.UUID, earned: tuple, earned_previous: tuple, today: date, currency: str
) -> AmcSummary:
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
    amc_revenue = await _amc_revenue(session, earned)
    return AmcSummary(
        active_contracts=int(count),
        active_value=_money(value, currency),
        clients=int(clients),
        renewals_due=int(renewals_due or 0),
        revenue=_money(amc_revenue, currency),
        revenue_previous=_money(await _amc_revenue(session, earned_previous), currency),
    )


async def _amc_revenue(session: AsyncSession, earned: tuple) -> Decimal:
    return await _scalar(
        session,
        select(func.coalesce(func.sum(_signed(Invoice.taxable_total)), 0))
        .join(Contract, Contract.id == Invoice.contract_id)
        .where(*earned, Contract.contract_type == AMC_CONTRACT_TYPE),
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


async def _by_state(session: AsyncSession, earned: tuple) -> list:
    return (
        await session.execute(
            select(Invoice.place_of_supply, func.coalesce(func.sum(_signed(Invoice.taxable_total)), 0))
            .where(*earned)
            .group_by(Invoice.place_of_supply)
        )
    ).all()


def _lines_with_offering(org_id: uuid.UUID):
    """Invoice lines with their invoice and the organization's offering they bill."""
    return (
        select()
        .select_from(InvoiceLine)
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .join(Offering, (Offering.id == InvoiceLine.offering_id) & (Offering.organization_id == org_id))
    )


async def _hardware_units(session: AsyncSession, org_id: uuid.UUID, earned: tuple) -> float:
    units = await _scalar(
        session,
        _lines_with_offering(org_id)
        .add_columns(func.coalesce(func.sum(_signed(InvoiceLine.quantity)), 0))
        .where(*earned, Offering.product_line == HARDWARE_PRODUCT_LINE),
    )
    return float(units)


async def _top_products(session: AsyncSession, org_id: uuid.UUID, earned: tuple, currency: str) -> list[TopProduct]:
    revenue = func.coalesce(func.sum(_signed(InvoiceLine.taxable_value)), 0)
    rows = (
        await session.execute(
            _lines_with_offering(org_id)
            .add_columns(Offering.id, Offering.name, func.coalesce(func.sum(_signed(InvoiceLine.quantity)), 0), revenue)
            .where(*earned)
            .group_by(Offering.id, Offering.name)
            .order_by(revenue.desc(), Offering.name)
            .limit(TOP_PRODUCTS)
        )
    ).all()
    return [
        TopProduct(offering_id=offering_id, name=name, units=float(units), revenue=_money(amount, currency))
        for offering_id, name, units, amount in rows
    ]


async def _business_segments(session: AsyncSession, org_id: uuid.UUID, earned: tuple, currency: str) -> dict:
    """`revenue_by_business_segment` and, for invoices that name a project, the same per project."""
    sector = case((Client.id.is_(None), None), else_=_sector())
    rows = (
        await session.execute(
            select(
                Invoice.work_unit_id,
                Contract.contract_type,
                Offering.product_line,
                sector,
                _market(),
                func.coalesce(func.sum(_signed(InvoiceLine.taxable_value)), 0),
            )
            .select_from(InvoiceLine)
            .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
            .outerjoin(Contract, Contract.id == Invoice.contract_id)
            .outerjoin(Offering, (Offering.id == InvoiceLine.offering_id) & (Offering.organization_id == org_id))
            .outerjoin(Client, Client.id == Invoice.client_id)
            .outerjoin(ClientTaxProfile, ClientTaxProfile.client_id == Client.id)
            .where(*earned)
            .group_by(Invoice.work_unit_id, Contract.contract_type, Offering.product_line, sector, _market())
        )
    ).all()
    totals: dict[str, Decimal] = {}
    per_project: dict[tuple[uuid.UUID, str], Decimal] = {}
    for work_unit_id, contract_type, product_line, client_sector, market, amount in rows:
        key = business_segment(contract_type, product_line, client_sector, market)
        amount = Decimal(str(amount or 0))
        totals[key] = totals.get(key, Decimal(0)) + amount
        if work_unit_id is not None:
            per_project[(work_unit_id, key)] = per_project.get((work_unit_id, key), Decimal(0)) + amount
    return {
        "revenue_by_business_segment": _buckets(totals.items(), currency),
        "business_segments_by_work_unit": [
            WorkUnitSegment(work_unit_id=work_unit_id, key=key, amount=_money(amount, currency))
            for (work_unit_id, key), amount in per_project.items()
        ],
    }
