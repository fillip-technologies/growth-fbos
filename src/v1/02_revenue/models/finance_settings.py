import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class FinanceSettings(Base):
    """
    How one organization runs billing. Without a row every setting is at its default, so an
    organization changes nothing until it chooses to. Each behaviour that changes how money
    flows comes in behind a setting here. Services ask `finance/policies.py`, never these
    columns directly. Created by the migration `a3f1c7d9e2b4` (finance tax foundation).
    """

    __tablename__ = "finance_settings"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    # How a contract's money is billed once it is active (finance/billing/scheduler.py):
    # staged = one invoice per payment term (advance, milestones, monthly...), as each falls
    # due; full_upfront = one invoice for everything on the start date; manual = no schedule,
    # invoices are drafted by hand.
    billing_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="staged")
    # An invoice for a contract that has a billing schedule must come from one of its lines,
    # so nothing is billed twice. Invoices without a contract are never affected.
    invoice_requires_schedule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # A credit note after the legal limit (a `deadline` entry): block = refused; warn_with_reason
    # = allowed when the request gives a reason, which is kept on the credit note.
    credit_note_deadline_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="block")
    # Collections chase what is genuinely owed: the balance less the TDS the customer is
    # expected to withhold. Off: the full balance.
    collections_on_net: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Days from issue to due date when an invoice doesn't give one.
    default_payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    # MM-DD; overrides the regime's fiscal year start (used for FY numbering and deadlines).
    fiscal_year_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    # Category for lines that name none; overrides the regime's default.
    default_tax_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # What the organization is when customers withhold TDS from it (company, firm, individual…):
    # some sections deduct at different rates by deductee. None: the sections' default rate.
    deductee_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
