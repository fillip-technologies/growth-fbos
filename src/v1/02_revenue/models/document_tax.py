import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class DocumentTaxLine(Base):
    """
    One tax on one line of a quotation, invoice, credit or debit note, frozen as it was worked
    out: the component, its label, rate and amounts are copied (not referenced), so changing
    the configuration later never changes a document. `rule_code` and `rate_code` record
    which configuration produced it.
    """

    __tablename__ = "document_tax_lines"
    __table_args__ = (Index("ix_document_tax_lines_document", "document_type", "document_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    # invoice (every invoice doc_type) or quotation
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    component_code: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # added | collected | reverse_charge
    behaviour: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rate_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    base_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    return_box: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
