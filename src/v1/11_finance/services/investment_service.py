"""Investments (FDs, mutual funds, equity, property...) and the income recorded against them."""
from datetime import date
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    IncomeEntryNotFoundError,
    InvestmentHasIncomeError,
    InvestmentNotFoundError,
    ValidationFailedError,
)
from models.finance import IncomeEntry, Investment
from schemas.common import PageMeta
from schemas.finance import (
    IncomeCreate,
    IncomeResponse,
    IncomeUpdate,
    InvestmentCreate,
    InvestmentResponse,
    InvestmentUpdate,
)
from services import settings_service
from services.pagination import paginate

INVESTMENT_REQUIRED = ("name", "investment_type", "principal", "currency", "start_date", "status")
INCOME_REQUIRED = ("income_type", "amount", "tax_deducted", "currency", "received_on")


def _check_dates(investment: Investment) -> None:
    if investment.maturity_date and investment.maturity_date < investment.start_date:
        raise ValidationFailedError("maturity_date", "must be on or after the start date")


def _require(changes: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in changes and changes[field] is None:
            raise ValidationFailedError(field, "cannot be empty")


def _columns(row) -> dict:
    return {column.key: getattr(row, column.key) for column in type(row).__table__.columns}


# --------------------------------------------------------------------------- investments


async def _income_totals(session: AsyncSession, investment_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not investment_ids:
        return {}
    rows = await session.execute(
        select(IncomeEntry.investment_id, func.coalesce(func.sum(IncomeEntry.amount), 0))
        .where(IncomeEntry.investment_id.in_(investment_ids))
        .group_by(IncomeEntry.investment_id)
    )
    return {investment_id: Decimal(str(total)) for investment_id, total in rows.all()}


def investment_response(investment: Investment, income_to_date: Decimal) -> InvestmentResponse:
    return InvestmentResponse.model_validate({**_columns(investment), "income_to_date": income_to_date})


async def get_investment(session: AsyncSession, organization_id: uuid.UUID, investment_id: uuid.UUID) -> Investment:
    investment = await session.get(Investment, investment_id)
    if investment is None or investment.organization_id != organization_id:
        raise InvestmentNotFoundError()
    return investment


async def read_investment(session: AsyncSession, organization_id: uuid.UUID, investment_id: uuid.UUID) -> InvestmentResponse:
    investment = await get_investment(session, organization_id, investment_id)
    totals = await _income_totals(session, [investment.id])
    return investment_response(investment, totals.get(investment.id, Decimal(0)))


async def create_investment(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, body: InvestmentCreate
) -> InvestmentResponse:
    values = body.model_dump()
    values["currency"] = body.currency or await settings_service.default_currency(session, organization_id)
    investment = Investment(organization_id=organization_id, created_by=user_id, status="active", **values)
    _check_dates(investment)
    session.add(investment)
    await session.commit()
    await session.refresh(investment)
    return investment_response(investment, Decimal(0))


async def update_investment(
    session: AsyncSession, organization_id: uuid.UUID, investment_id: uuid.UUID, body: InvestmentUpdate
) -> InvestmentResponse:
    investment = await get_investment(session, organization_id, investment_id)
    changes = body.model_dump(exclude_unset=True)
    _require(changes, INVESTMENT_REQUIRED)
    for field, value in changes.items():
        setattr(investment, field, value)
    _check_dates(investment)
    await session.commit()
    await session.refresh(investment)
    totals = await _income_totals(session, [investment.id])
    return investment_response(investment, totals.get(investment.id, Decimal(0)))


async def delete_investment(session: AsyncSession, organization_id: uuid.UUID, investment_id: uuid.UUID) -> None:
    investment = await get_investment(session, organization_id, investment_id)
    has_income = await session.scalar(select(IncomeEntry.id).where(IncomeEntry.investment_id == investment.id).limit(1))
    if has_income:
        raise InvestmentHasIncomeError()
    await session.delete(investment)
    await session.commit()


async def list_investments(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    limit: int,
    cursor: Optional[str],
    status: Optional[str] = None,
    investment_type: Optional[str] = None,
    investee_organization_id: Optional[uuid.UUID] = None,
) -> tuple[list[InvestmentResponse], PageMeta]:
    """Latest start date first."""
    query = select(Investment).where(Investment.organization_id == organization_id)
    if status:
        query = query.where(Investment.status == status)
    if investment_type:
        query = query.where(Investment.investment_type == investment_type)
    if investee_organization_id:
        query = query.where(Investment.investee_organization_id == investee_organization_id)
    rows, page = await paginate(session, query, Investment, limit, cursor, order_by=Investment.start_date, descending=True)
    totals = await _income_totals(session, [row.id for row in rows])
    return [investment_response(row, totals.get(row.id, Decimal(0))) for row in rows], page


# --------------------------------------------------------------------------- income


def income_response(entry: IncomeEntry) -> IncomeResponse:
    net = Decimal(entry.amount) - Decimal(entry.tax_deducted or 0)
    return IncomeResponse.model_validate({**_columns(entry), "net_received": net})


async def _check_income(session: AsyncSession, entry: IncomeEntry) -> None:
    if Decimal(entry.tax_deducted or 0) > Decimal(entry.amount):
        raise ValidationFailedError("tax_deducted", "cannot be more than the amount")
    if entry.investment_id is not None:
        investment = await session.get(Investment, entry.investment_id)
        if investment is None or investment.organization_id != entry.organization_id:
            raise ValidationFailedError("investment_id", "no such investment in this organization")


async def get_income(session: AsyncSession, organization_id: uuid.UUID, entry_id: uuid.UUID) -> IncomeEntry:
    entry = await session.get(IncomeEntry, entry_id)
    if entry is None or entry.organization_id != organization_id:
        raise IncomeEntryNotFoundError()
    return entry


async def create_income(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, body: IncomeCreate
) -> IncomeResponse:
    values = body.model_dump()
    values["currency"] = body.currency or await settings_service.default_currency(session, organization_id)
    entry = IncomeEntry(organization_id=organization_id, created_by=user_id, **values)
    await _check_income(session, entry)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return income_response(entry)


async def update_income(
    session: AsyncSession, organization_id: uuid.UUID, entry_id: uuid.UUID, body: IncomeUpdate
) -> IncomeResponse:
    entry = await get_income(session, organization_id, entry_id)
    changes = body.model_dump(exclude_unset=True)
    _require(changes, INCOME_REQUIRED)
    for field, value in changes.items():
        setattr(entry, field, value)
    await _check_income(session, entry)
    await session.commit()
    await session.refresh(entry)
    return income_response(entry)


async def delete_income(session: AsyncSession, organization_id: uuid.UUID, entry_id: uuid.UUID) -> None:
    entry = await get_income(session, organization_id, entry_id)
    await session.delete(entry)
    await session.commit()


async def list_income(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    limit: int,
    cursor: Optional[str],
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    income_type: Optional[str] = None,
    investment_id: Optional[uuid.UUID] = None,
) -> tuple[list[IncomeResponse], PageMeta]:
    """Latest received first."""
    query = select(IncomeEntry).where(IncomeEntry.organization_id == organization_id)
    if from_date:
        query = query.where(IncomeEntry.received_on >= from_date)
    if to_date:
        query = query.where(IncomeEntry.received_on <= to_date)
    if income_type:
        query = query.where(IncomeEntry.income_type == income_type)
    if investment_id:
        query = query.where(IncomeEntry.investment_id == investment_id)
    rows, page = await paginate(session, query, IncomeEntry, limit, cursor, order_by=IncomeEntry.received_on, descending=True)
    return [income_response(row) for row in rows], page
