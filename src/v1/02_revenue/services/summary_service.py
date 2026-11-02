"""Counts and money per resource for one organization, for the console's overview.

Each summary is a handful of GROUP BY queries; nothing is loaded row by row. Month series cover
the last `months` calendar months including the current one, oldest first, with empty months
present so a chart's axis never skips.
"""
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.client import Client
from models.contract import Contract
from models.invoice import Invoice
from models.lead import Lead
from models.opportunity import Opportunity
from models.payment import Payment
from schemas.common import Money
from schemas.summary import (
    AgingBucket,
    ClientBalance,
    ContractSummary,
    CountBucket,
    InvoiceStatusRow,
    InvoiceSummary,
    LeadSummary,
    MonthAmount,
    OpportunitySummary,
    OwnerCount,
    OwnerPipeline,
    PaymentSummary,
    StageValue,
    StatusValue,
)

DEFAULT_CURRENCY = "INR"
OPEN_LEAD_STATUSES = ("new", "contacted", "qualified")
OPPORTUNITY_STAGES = ("qualification", "proposal", "negotiation", "won", "lost")
OPEN_STAGES = ("qualification", "proposal", "negotiation")
# Invoices that still ask the customer for money.
RECEIVABLE_STATUSES = ("issued", "partially_paid", "overdue")
# Documents that are not sales: credit notes reduce what is owed, they are not invoiced revenue.
NON_SALES_DOC_TYPES = ("credit_note",)
COLLECTED_PAYMENT_STATUSES = ("confirmed", "partially_refunded")
AGING_BUCKETS = (("current", None, 0), ("1_30", 1, 30), ("31_60", 31, 60), ("61_90", 61, 90), ("90_plus", 91, None))
TOP_BALANCES = 5


def _amount(value) -> float:
    return float(value or 0)


def _money(value, currency: str) -> Money:
    return Money(amount=round(_amount(value), 2), currency=currency)


def _month_keys(months: int, today: date) -> list[str]:
    """The last `months` months as YYYY-MM, oldest first."""
    year, month = today.year, today.month
    keys = []
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(keys))


def _window_start(months: int, today: date) -> date:
    first = _month_keys(months, today)[0]
    return date(int(first[:4]), int(first[5:]), 1)


def _month_of(day) -> str:
    return f"{day.year:04d}-{day.month:02d}"


async def _main_currency(session: AsyncSession, model, org_id: uuid.UUID, *where) -> tuple[str, bool]:
    """The currency most of the records use, and whether any use another one."""
    rows = (
        await session.execute(
            select(model.currency, func.count()).where(model.organization_id == org_id, *where).group_by(model.currency)
        )
    ).all()
    if not rows:
        return DEFAULT_CURRENCY, False
    currency = max(rows, key=lambda row: row[1])[0] or DEFAULT_CURRENCY
    return currency, len(rows) > 1


def _buckets(rows: Iterable[tuple], order: Optional[Iterable[str]] = None) -> list[CountBucket]:
    counts = {str(key or "unknown"): int(count) for key, count in rows}
    keys = [k for k in (order or []) if k in counts] + sorted(k for k in counts if k not in (order or []))
    return [CountBucket(key=k, count=counts[k]) for k in keys]


class SummaryService:
    @staticmethod
    async def leads(session: AsyncSession, org_id: uuid.UUID, months: int, today: Optional[date] = None) -> LeadSummary:
        today = today or date.today()
        in_org = Lead.organization_id == org_id
        by_status = (await session.execute(select(Lead.status, func.count()).where(in_org).group_by(Lead.status))).all()
        by_source = (await session.execute(select(Lead.source, func.count()).where(in_org).group_by(Lead.source))).all()
        by_owner = (
            await session.execute(
                select(Lead.owner_user_id, func.count())
                .where(in_org, Lead.status.in_(OPEN_LEAD_STATUSES))
                .group_by(Lead.owner_user_id)
            )
        ).all()
        start = datetime.combine(_window_start(months, today), datetime.min.time())
        created_days = (
            await session.execute(
                select(func.date(Lead.created_at), func.count())
                .where(in_org, Lead.created_at >= start)
                .group_by(func.date(Lead.created_at))
            )
        ).all()
        per_month: Counter = Counter()
        for day, count in created_days:
            per_month[str(day)[:7]] += int(count)
        return LeadSummary(
            total=sum(int(count) for _, count in by_status),
            by_status=_buckets(by_status, ("new", "contacted", "qualified", "converted", "disqualified")),
            by_source=sorted(_buckets(by_source), key=lambda b: -b.count),
            by_owner=[OwnerCount(user_id=user_id, count=int(count)) for user_id, count in sorted(by_owner, key=lambda r: -r[1])],
            created_by_month=[CountBucket(key=key, count=per_month.get(key, 0)) for key in _month_keys(months, today)],
        )

    @staticmethod
    async def opportunities(session: AsyncSession, org_id: uuid.UUID) -> OpportunitySummary:
        currency, mixed = await _main_currency(session, Opportunity, org_id)
        # Older records may carry a status outside the stages; the API shows those as "proposal".
        stage = Opportunity.status
        rows = (
            await session.execute(
                select(
                    stage,
                    Opportunity.owner_user_id,
                    func.count(),
                    func.coalesce(func.sum(Opportunity.expected_value), 0),
                    func.coalesce(func.sum(Opportunity.expected_value * func.coalesce(Opportunity.probability, 0)), 0),
                )
                .where(Opportunity.organization_id == org_id)
                .group_by(stage, Opportunity.owner_user_id)
            )
        ).all()
        stages: dict[str, list] = {s: [0, Decimal(0)] for s in OPPORTUNITY_STAGES}
        owners: dict[uuid.UUID, list] = {}
        weighted = Decimal(0)
        for status, owner, count, value, value_x_probability in rows:
            key = status if status in OPPORTUNITY_STAGES else "proposal"
            stages[key][0] += int(count)
            stages[key][1] += Decimal(str(value))
            owner_row = owners.setdefault(owner, [0, Decimal(0), 0, Decimal(0)])
            if key in OPEN_STAGES:
                weighted += Decimal(str(value_x_probability)) / 100
                owner_row[0] += int(count)
                owner_row[1] += Decimal(str(value))
            elif key == "won":
                owner_row[2] += int(count)
                owner_row[3] += Decimal(str(value))
        open_value = sum((stages[s][1] for s in OPEN_STAGES), Decimal(0))
        return OpportunitySummary(
            currency=currency,
            mixed_currencies=mixed,
            by_stage=[StageValue(stage=s, count=c, value=_money(v, currency)) for s, (c, v) in stages.items()],
            open_value=_money(open_value, currency),
            weighted_value=_money(weighted, currency),
            by_owner=[
                OwnerPipeline(
                    user_id=user_id,
                    open_count=open_count,
                    open_value=_money(open_value_, currency),
                    won_count=won_count,
                    won_value=_money(won_value, currency),
                )
                for user_id, (open_count, open_value_, won_count, won_value) in sorted(
                    owners.items(), key=lambda item: (-item[1][1], -item[1][3])
                )
            ],
        )

    @staticmethod
    async def contracts(session: AsyncSession, org_id: uuid.UUID) -> ContractSummary:
        currency, mixed = await _main_currency(session, Contract, org_id)
        rows = (
            await session.execute(
                select(Contract.status, func.count(), func.coalesce(func.sum(Contract.total_value), 0))
                .where(Contract.organization_id == org_id)
                .group_by(Contract.status)
            )
        ).all()
        order = ("draft", "pending_signature", "active", "completed", "terminated", "expired")
        by_key = {status: (int(count), value) for status, count, value in rows}
        keys = [k for k in order if k in by_key] + sorted(k for k in by_key if k not in order)
        return ContractSummary(
            currency=currency,
            mixed_currencies=mixed,
            by_status=[StatusValue(status=k, count=by_key[k][0], value=_money(by_key[k][1], currency)) for k in keys],
            active_value=_money(by_key.get("active", (0, 0))[1], currency),
        )

    @staticmethod
    async def invoices(
        session: AsyncSession, org_id: uuid.UUID, months: int, today: Optional[date] = None
    ) -> InvoiceSummary:
        today = today or date.today()
        sales = (Invoice.organization_id == org_id, Invoice.doc_type.notin_(NON_SALES_DOC_TYPES))
        currency, mixed = await _main_currency(session, Invoice, org_id, Invoice.doc_type.notin_(NON_SALES_DOC_TYPES))

        status_rows = (
            await session.execute(
                select(
                    Invoice.status,
                    func.count(),
                    func.coalesce(func.sum(Invoice.grand_total), 0),
                    func.coalesce(func.sum(Invoice.balance_due), 0),
                )
                .where(*sales)
                .group_by(Invoice.status)
            )
        ).all()
        order = ("draft", "pending_approval", "issued", "partially_paid", "overdue", "paid", "written_off", "cancelled")
        by_key = {status: (int(c), total, balance) for status, c, total, balance in status_rows}
        keys = [k for k in order if k in by_key] + sorted(k for k in by_key if k not in order)

        receivable = (*sales, Invoice.status.in_(RECEIVABLE_STATUSES), Invoice.balance_due > 0)
        due_rows = (
            await session.execute(
                select(Invoice.due_date, func.count(), func.coalesce(func.sum(Invoice.balance_due), 0))
                .where(*receivable)
                .group_by(Invoice.due_date)
            )
        ).all()
        aging = {key: [0, Decimal(0)] for key, _, _ in AGING_BUCKETS}
        overdue = Decimal(0)
        outstanding = Decimal(0)
        for due, count, balance in due_rows:
            balance = Decimal(str(balance))
            outstanding += balance
            late = (today - due).days if due else 0
            if late > 0:
                overdue += balance
            for key, low, high in AGING_BUCKETS:
                if (low is None and late <= high) or (low is not None and late >= low and (high is None or late <= high)):
                    aging[key][0] += int(count)
                    aging[key][1] += balance
                    break

        start = _window_start(months, today)
        issued_rows = (
            await session.execute(
                select(Invoice.issue_date, func.count(), func.coalesce(func.sum(Invoice.grand_total), 0))
                .where(*sales, Invoice.issue_date >= start, Invoice.status.notin_(("draft", "pending_approval", "cancelled")))
                .group_by(Invoice.issue_date)
            )
        ).all()
        per_month: dict[str, list] = {}
        for day, count, total in issued_rows:
            row = per_month.setdefault(_month_of(day), [0, Decimal(0)])
            row[0] += int(count)
            row[1] += Decimal(str(total))

        top_rows = (
            await session.execute(
                select(Invoice.client_id, Client.name, func.sum(Invoice.balance_due).label("balance"))
                .join(Client, Client.id == Invoice.client_id)
                .where(*receivable)
                .group_by(Invoice.client_id, Client.name)
                .order_by(func.sum(Invoice.balance_due).desc())
                .limit(TOP_BALANCES)
            )
        ).all()

        return InvoiceSummary(
            currency=currency,
            mixed_currencies=mixed,
            as_of=today,
            by_status=[
                InvoiceStatusRow(
                    status=k, count=by_key[k][0], total=_money(by_key[k][1], currency), balance=_money(by_key[k][2], currency)
                )
                for k in keys
            ],
            outstanding=_money(outstanding, currency),
            overdue=_money(overdue, currency),
            aging=[AgingBucket(key=k, count=c, amount=_money(v, currency)) for k, (c, v) in aging.items()],
            invoiced_by_month=[
                MonthAmount(month=key, count=per_month.get(key, [0])[0], amount=_money(per_month.get(key, [0, 0])[1], currency))
                for key in _month_keys(months, today)
            ],
            top_balances=[
                ClientBalance(client_id=client_id, name=name, balance=_money(balance, currency)) for client_id, name, balance in top_rows
            ],
        )

    @staticmethod
    async def payments(
        session: AsyncSession, org_id: uuid.UUID, months: int, today: Optional[date] = None
    ) -> PaymentSummary:
        today = today or date.today()
        collected = (Payment.organization_id == org_id, Payment.status.in_(COLLECTED_PAYMENT_STATUSES))
        currency, mixed = await _main_currency(session, Payment, org_id, Payment.status.in_(COLLECTED_PAYMENT_STATUSES))
        start = datetime.combine(_window_start(months, today), datetime.min.time())
        # The window ends with today; a receipt dated later (a clock ahead) still counts in its month.
        end = datetime.combine(today + timedelta(days=1), datetime.min.time())
        day_rows = (
            await session.execute(
                select(func.date(Payment.received_at), func.count(), func.coalesce(func.sum(Payment.amount), 0))
                .where(*collected, Payment.received_at >= start)
                .group_by(func.date(Payment.received_at))
            )
        ).all()
        per_month: dict[str, list] = {}
        for day, count, amount in day_rows:
            row = per_month.setdefault(str(day)[:7], [0, Decimal(0)])
            row[0] += int(count)
            row[1] += Decimal(str(amount))
        method_rows = (
            await session.execute(
                select(Payment.method, func.count())
                .where(*collected, Payment.received_at >= start, Payment.received_at < end)
                .group_by(Payment.method)
            )
        ).all()
        keys = _month_keys(months, today)
        return PaymentSummary(
            currency=currency,
            mixed_currencies=mixed,
            collected_by_month=[
                MonthAmount(month=key, count=per_month.get(key, [0])[0], amount=_money(per_month.get(key, [0, 0])[1], currency))
                for key in keys
            ],
            by_method=sorted(_buckets(method_rows), key=lambda b: -b.count),
            collected=_money(sum((per_month[k][1] for k in keys if k in per_month), Decimal(0)), currency),
        )
