import uuid

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class InvoiceSeries(Base):
    """
    Number sequence generator per legal registration + document type + fiscal year.
    Guarantees contiguous, prefix-stamped invoice numbers (e.g. INV-2425-00001).
    fin_registration_id references identity service's tax_registrations — no DB FK.
    """

    __tablename__ = "invoice_series"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    # References identity.tax_registrations — cross-service, no DB FK
    fin_registration_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)   # tax_invoice / credit_note / proforma
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)      # e.g. "INV", "CN"
    fiscal_year: Mapped[str] = mapped_column(String(10), nullable=False) # e.g. "2024-25"
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
