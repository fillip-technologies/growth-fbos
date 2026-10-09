import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, func, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Invoice(Base):
    """
    GST-compliant tax invoice / credit note / proforma.
    client_id and contract_id are cross-service references (commercial) — no DB FK.
    issued_by references identity.users — no DB FK.
    """

    __tablename__ = "invoices"
    # A number is unique per supplier registration (GSTIN), as GST invoice rules require; two
    # registrations of one organization run their own series.
    __table_args__ = (
        UniqueConstraint("organization_id", "supplier_gstin", "invoice_no", name="uq_invoices_org_gstin_invoice_no"),
        UniqueConstraint("schedule_line_id", name="uq_invoices_schedule_line_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    series_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("invoice_series.id", ondelete="RESTRICT"), nullable=True
    )
    # Self-ref: credit notes point to the original invoice they reverse
    original_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True
    )
    invoice_no: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # tax_invoice / credit_note / proforma
    # context_id: polymorphic reference to contract or billing_schedule (cross-service)
    context_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    contract_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    work_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    supplier_gstin: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_gstin: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    place_of_supply: Mapped[str] = mapped_column(String(100), nullable=False)
    reverse_charge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    exchange_rate: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=1)
    taxable_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    igst_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    grand_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    amount_settled: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    balance_due: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    # GST e-invoicing fields
    irn: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    ack_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pdf_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    issued_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    client_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # --- Tax engine (finance/tax). Frozen with the document; see DocumentTaxLine for per-line taxes.
    # The organization's registration it is issued under (org_tax_registrations), and a copy of it.
    tax_registration_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    supplier_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    supply_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # The date the rates and rules were taken as of: the issue date once issued.
    tax_point_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    round_off: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    config_revision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tax_notes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # TDS the customer is expected to withhold (shown, never part of the total).
    withholding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    expected_withholding: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    # balance_due = grand_total - amount_settled (payments and TDS) - credited - written off.
    credited_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    written_off_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    # The billing schedule line it bills (no FK: billing_schedule_lines already points here).
    schedule_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    # Credit and debit notes: why they were raised, and any reason given to pass a deadline.
    note_reason: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    note_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deadline_override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InvoiceLine(Base):
    """
    One line item on an invoice. GST is split into IGST (interstate) or CGST+SGST (intrastate).
    offering_id references commercial.offerings — no DB FK.
    """

    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_line_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("billing_schedule_lines.id", ondelete="SET NULL"), nullable=True
    )
    offering_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)  # cross-service
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hsn_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # HSN/SAC for GST
    quantity: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    discount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    taxable_value: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    igst_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    cgst_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    sgst_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    line_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    tax_category_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Sum of the rates charged on the line (18 for CGST 9 + SGST 9), for display.
    tax_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 4), nullable=True)
