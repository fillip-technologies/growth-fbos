import uuid
from typing import Optional

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType

# scope_key of series that belong to the organization rather than to one registration.
ORGANIZATION_SCOPE = "organization"


class InvoiceSeries(Base):
    """
    One running number sequence: per registration (or the whole organization), document type
    and period (fiscal year, calendar year, or forever, as the series template says). The
    prefix and format are copied from the template when the series starts, so a template edit
    applies from the next period. Numbers are taken under a row lock (finance/numbering.py).
    fin_registration_id references org_tax_registrations.
    """

    __tablename__ = "invoice_series"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope_key", "doc_type", "fiscal_year", name="uq_invoice_series_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    fin_registration_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    # The registration id as text, or ORGANIZATION_SCOPE: unique constraints can't rely on NULLs.
    scope_key: Mapped[str] = mapped_column(String(36), nullable=False, default=ORGANIZATION_SCOPE)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)   # tax_invoice / credit_note / ...
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)      # e.g. "INV", "CN"
    # The period label: "2026-27" (fiscal year), "2026" (calendar year) or "all".
    fiscal_year: Mapped[str] = mapped_column(String(10), nullable=False)
    format: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
