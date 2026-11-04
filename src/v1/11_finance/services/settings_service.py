"""The organization's finance settings; without a row every setting is at its default."""
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from models.finance import FinanceSettings
from schemas.finance import SettingsResponse, SettingsUpdate

DEFAULT_CURRENCY = "INR"


async def load(session: AsyncSession, organization_id: uuid.UUID) -> Optional[FinanceSettings]:
    return await session.get(FinanceSettings, organization_id)


async def read(session: AsyncSession, organization_id: uuid.UUID) -> SettingsResponse:
    row = await load(session, organization_id)
    if row is None:
        return SettingsResponse(expense_approval_threshold=None, default_currency=DEFAULT_CURRENCY)
    return SettingsResponse(expense_approval_threshold=row.expense_approval_threshold, default_currency=row.default_currency)


async def approval_threshold(session: AsyncSession, organization_id: uuid.UUID) -> Optional[Decimal]:
    row = await load(session, organization_id)
    return row.expense_approval_threshold if row else None


async def default_currency(session: AsyncSession, organization_id: uuid.UUID) -> str:
    row = await load(session, organization_id)
    return row.default_currency if row else DEFAULT_CURRENCY


async def update(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, body: SettingsUpdate
) -> SettingsResponse:
    row = await load(session, organization_id)
    if row is None:
        row = FinanceSettings(organization_id=organization_id, default_currency=DEFAULT_CURRENCY)
        session.add(row)
    changes = body.model_dump(exclude_unset=True)
    if "expense_approval_threshold" in changes:
        row.expense_approval_threshold = changes["expense_approval_threshold"]
    if changes.get("default_currency"):
        row.default_currency = changes["default_currency"]
    row.updated_by = user_id
    await session.commit()
    return await read(session, organization_id)
