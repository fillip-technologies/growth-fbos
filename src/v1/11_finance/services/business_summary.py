"""Expenses, other income and investments for one organization over a period (CEO Command Center)."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import uuid

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.finance import Expense, ExpenseCategory, IncomeEntry, Investment
from schemas.business_summary import (
    AmountBucket,
    CategoryAmount,
    FinanceBusinessSummary,
    InvestmentsPosition,
    InvestmentTypeRow,
    MonthAmount,
    PendingApproval,
)
from schemas.common import Period
from services.settings_service import DEFAULT_CURRENCY

APPROVED, PENDING = "approved", "pending_approval"
MATURING_WINDOW_DAYS = 30
INVESTMENT_IN_COMPANIES = "investment_in_companies"
ZERO = Decimal(0)


def previous_period(from_date: date, to_date: date) -> tuple[date, date]:
    """The same number of days immediately before the period."""
    days = (to_date - from_date).days + 1
    return from_date - timedelta(days=days), from_date - timedelta(days=1)


def _round(amount: Decimal) -> float:
    return round(float(amount), 2)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


async def finance_summary(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date
) -> FinanceBusinessSummary:
    previous_from, previous_to = previous_period(from_date, to_date)
    by_day = await _approved_expenses_by_day(session, org_id, from_date, to_date)
    months: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for day, amount, _tax, _unpaid in by_day:
        months[day.strftime("%Y-%m")] += amount
    currency, mixed = await _main_currency(session, org_id)
    return FinanceBusinessSummary(
        currency=currency,
        mixed_currencies=mixed,
        period=Period(from_date=from_date, to_date=to_date),
        previous_period=Period(from_date=previous_from, to_date=previous_to),
        expenses=_round(sum((row[1] for row in by_day), ZERO)),
        expenses_previous=_round(await _approved_expense_total(session, org_id, previous_from, previous_to)),
        expense_tax=_round(sum((row[2] for row in by_day), ZERO)),
        expenses_unpaid=_round(sum((row[3] for row in by_day), ZERO)),
        expenses_by_category=await _by_category(session, org_id, from_date, to_date),
        expenses_by_month=[MonthAmount(month=m, amount=_round(v)) for m, v in sorted(months.items())],
        pending_approval=await _pending(session, org_id),
        income=_round(await _income_total(session, org_id, from_date, to_date)),
        income_previous=_round(await _income_total(session, org_id, previous_from, previous_to)),
        income_by_type=_with_previous(
            await _income_by_type(session, org_id, from_date, to_date),
            await _income_by_type(session, org_id, previous_from, previous_to),
        ),
        investments=await _investments(session, org_id, to_date),
    )


def _approved_in(org_id: uuid.UUID, from_date: date, to_date: date):
    return (
        Expense.organization_id == org_id,
        Expense.approval_status == APPROVED,
        Expense.expense_date >= from_date,
        Expense.expense_date <= to_date,
    )


async def _approved_expenses_by_day(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date
) -> list[tuple[date, Decimal, Decimal, Decimal]]:
    """(day, amount, tax, unpaid amount) per day with expenses."""
    rows = (
        await session.execute(
            select(
                Expense.expense_date,
                func.coalesce(func.sum(Expense.amount), 0),
                func.coalesce(func.sum(Expense.tax_amount), 0),
                Expense.payment_status,
            )
            .where(*_approved_in(org_id, from_date, to_date))
            .group_by(Expense.expense_date, Expense.payment_status)
        )
    ).all()
    days: dict[date, list[Decimal]] = {}
    for day, amount, tax, payment_status in rows:
        row = days.setdefault(day, [ZERO, ZERO, ZERO])
        row[0] += _dec(amount)
        row[1] += _dec(tax)
        if payment_status == "unpaid":
            row[2] += _dec(amount)
    return [(day, *values) for day, values in sorted(days.items())]


async def _approved_expense_total(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(*_approved_in(org_id, from_date, to_date))
    )
    return _dec(total)


async def _by_category(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> list[CategoryAmount]:
    rows = (
        await session.execute(
            select(ExpenseCategory.code, ExpenseCategory.name, func.coalesce(func.sum(Expense.amount), 0))
            .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(*_approved_in(org_id, from_date, to_date))
            .group_by(ExpenseCategory.code, ExpenseCategory.name)
        )
    ).all()
    buckets = [CategoryAmount(key=code, name=name, amount=_round(_dec(amount))) for code, name, amount in rows]
    return sorted(buckets, key=lambda bucket: -bucket.amount)


async def _pending(session: AsyncSession, org_id: uuid.UUID) -> PendingApproval:
    count, total = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Expense.amount + Expense.tax_amount), 0)).where(
                Expense.organization_id == org_id, Expense.approval_status == PENDING
            )
        )
    ).one()
    return PendingApproval(count=int(count), amount=_round(_dec(total)))


async def _income_total(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(IncomeEntry.amount), 0)).where(
            IncomeEntry.organization_id == org_id,
            IncomeEntry.received_on >= from_date,
            IncomeEntry.received_on <= to_date,
        )
    )
    return _dec(total)


async def _income_by_type(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date
) -> dict[str, Decimal]:
    """Income per type; what investments in companies (an investment naming its investee
    organization) brought in is one type of its own, `investment_in_companies`, so it is not
    counted under interest or dividend as well."""
    in_a_company = Investment.investee_organization_id.is_not(None)
    income_type = case((in_a_company, INVESTMENT_IN_COMPANIES), else_=IncomeEntry.income_type)
    rows = (
        await session.execute(
            select(income_type, func.coalesce(func.sum(IncomeEntry.amount), 0))
            .outerjoin(Investment, Investment.id == IncomeEntry.investment_id)
            .where(
                IncomeEntry.organization_id == org_id,
                IncomeEntry.received_on >= from_date,
                IncomeEntry.received_on <= to_date,
            )
            .group_by(income_type)
        )
    ).all()
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for key, amount in rows:
        totals[key] += _dec(amount)
    return dict(totals)


def _with_previous(current: dict[str, Decimal], previous: dict[str, Decimal]) -> list[AmountBucket]:
    """Every key of either period, largest first; a key only the previous period had shows 0 now."""
    buckets = [
        AmountBucket(key=key, amount=_round(current.get(key, ZERO)), previous=_round(previous.get(key, ZERO)))
        for key in current.keys() | previous.keys()
    ]
    return sorted(buckets, key=lambda bucket: (-bucket.amount, -(bucket.previous or 0), bucket.key))


async def _investments(session: AsyncSession, org_id: uuid.UUID, to_date: date) -> InvestmentsPosition:
    rows = (
        await session.execute(
            select(
                Investment.investment_type,
                func.count(),
                func.coalesce(func.sum(Investment.principal), 0),
                func.coalesce(func.sum(func.coalesce(Investment.current_value, Investment.principal)), 0),
            )
            .where(Investment.organization_id == org_id, Investment.status == "active")
            .group_by(Investment.investment_type)
        )
    ).all()
    maturing = await session.scalar(
        select(func.count()).where(
            Investment.organization_id == org_id,
            Investment.status == "active",
            Investment.maturity_date.is_not(None),
            Investment.maturity_date > to_date,
            Investment.maturity_date <= to_date + timedelta(days=MATURING_WINDOW_DAYS),
        )
    )
    by_type = sorted(
        (InvestmentTypeRow(key=kind, count=int(count), principal=_round(_dec(principal))) for kind, count, principal, _ in rows),
        key=lambda row: -row.principal,
    )
    return InvestmentsPosition(
        active=sum(int(count) for _, count, _, _ in rows),
        principal=_round(sum((_dec(principal) for _, _, principal, _ in rows), ZERO)),
        current_value=_round(sum((_dec(value) for _, _, _, value in rows), ZERO)),
        by_type=by_type,
        maturing_soon=int(maturing or 0),
    )


async def _main_currency(session: AsyncSession, org_id: uuid.UUID) -> tuple[str, bool]:
    """The currency most expenses are in; mixed when expenses, income or investments use more than one."""
    currencies: dict[str, int] = defaultdict(int)
    for model in (Expense, IncomeEntry, Investment):
        rows = (
            await session.execute(
                select(model.currency, func.count()).where(model.organization_id == org_id).group_by(model.currency)
            )
        ).all()
        for currency, count in rows:
            currencies[currency] += int(count)
    if not currencies:
        return DEFAULT_CURRENCY, False
    return max(currencies.items(), key=lambda item: item[1])[0], len(currencies) > 1
