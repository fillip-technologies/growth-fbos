"""
The organization's billing policy, one function per decision. Services ask here rather than
reading `finance_settings` columns, so what a setting means lives in one place.
"""

from datetime import date
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from finance.deadlines import Deadline
from finance.errors import FinanceConflictError, TaxConfigError
from finance.tax.config_schema import RegimeData
from models.finance_settings import FinanceSettings

# When no registration (and so no regime) is involved, e.g. a quotation number.
CALENDAR_YEAR_START = "01-01"


def defaults(org_id: uuid.UUID) -> FinanceSettings:
    """An unsaved settings row with every column at its declared default."""
    values = {
        column.key: column.default.arg
        for column in FinanceSettings.__table__.columns
        if column.default is not None and not callable(column.default.arg)
    }
    return FinanceSettings(organization_id=org_id, **values)


async def load_settings(session: AsyncSession, org_id: uuid.UUID) -> FinanceSettings:
    saved = await session.get(FinanceSettings, org_id)
    return saved if saved is not None else defaults(org_id)


def fiscal_year_start(settings: FinanceSettings, regime: Optional[RegimeData]) -> str:
    if settings.fiscal_year_start:
        return settings.fiscal_year_start
    if regime is not None:
        return regime.fiscal_year_start
    return CALENDAR_YEAR_START


def due_date(settings: FinanceSettings, issued_on: date, requested: Optional[date]) -> date:
    if requested is not None:
        return requested
    return date.fromordinal(issued_on.toordinal() + settings.default_payment_terms_days)


def default_category(settings: FinanceSettings, regime: RegimeData) -> Optional[str]:
    return settings.default_tax_category or regime.default_category


def schedules_contracts(settings: FinanceSettings) -> bool:
    """Whether activating a contract builds its billing schedule."""
    return settings.billing_mode != "manual"


def bills_everything_upfront(settings: FinanceSettings) -> bool:
    return settings.billing_mode == "full_upfront"


def require_schedule_line(settings: FinanceSettings, contract_has_schedule: bool, schedule_line_given: bool) -> None:
    if settings.invoice_requires_schedule and contract_has_schedule and not schedule_line_given:
        raise FinanceConflictError(
            "INVOICE_REQUIRES_SCHEDULE_LINE",
            "This contract is billed from its billing schedule. Bill one of its schedule lines instead.",
        )


def check_credit_note_deadline(settings: FinanceSettings, deadlines: list[Deadline], today: date, reason: Optional[str]) -> None:
    missed = [deadline for deadline in deadlines if deadline.severity == "block" and today > deadline.due_on]
    if not missed:
        return
    if settings.credit_note_deadline_mode == "warn_with_reason" and reason:
        return
    first = missed[0]
    raise TaxConfigError(
        "CREDIT_NOTE_DEADLINE_PASSED",
        f"{first.description} ({first.due_on.isoformat()} has passed).",
        meta={
            "deadline": first.code,
            "due_on": first.due_on.isoformat(),
            "override_allowed": settings.credit_note_deadline_mode == "warn_with_reason",
        },
    )
