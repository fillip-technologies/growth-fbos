"""TDS withheld by customers (until it is claimed), and how GST owed compares with cash collected."""

from datetime import date, datetime, timedelta
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.errors import FinanceNotFoundError, TaxConfigError
from finance.money import ZERO, as_float, round_money, to_decimal
from models.document_tax import DocumentTaxLine
from models.invoice import Invoice
from models.payment import Payment, PaymentAllocation
from models.receivables import TdsReceivable
from schemas.common import Money
from schemas.tax import GstVsCashReport, TdsReceivableResponse, TdsReceivableUpdate
from services.versioning import check_version

CHARGED = ("added", "collected")
# Documents whose GST counts toward what is owed (credit notes count against it).
CHARGE_DOCUMENTS = ("tax_invoice", "debit_note")


def _response(row: TdsReceivable, currency: str = "INR") -> TdsReceivableResponse:
    return TdsReceivableResponse(
        id=row.id, client_id=row.client_id, payment_id=row.payment_id, invoice_id=row.invoice_id,
        section_code=row.section_code, statute_ref=row.statute_ref,
        amount=Money(amount=as_float(to_decimal(row.amount)), currency=currency), deducted_on=row.deducted_on,
        fiscal_year=row.fiscal_year, quarter=row.quarter, status=row.status, certificate_no=row.certificate_no,
        notes=row.notes, version=row.version,
    )


def _month(period: str) -> tuple[date, date]:
    try:
        first = datetime.strptime(period, "%Y-%m").date()
    except ValueError as error:
        raise TaxConfigError("PERIOD_INVALID", "period must look like 2026-09") from error
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, next_month


class ReceivablesService:
    @staticmethod
    async def list_tds(
        session: AsyncSession,
        org_id: uuid.UUID,
        client_id: Optional[uuid.UUID],
        status: Optional[str],
        fiscal_year: Optional[str],
    ) -> list[TdsReceivableResponse]:
        query = select(TdsReceivable).where(TdsReceivable.organization_id == org_id)
        if client_id is not None:
            query = query.where(TdsReceivable.client_id == client_id)
        if status is not None:
            query = query.where(TdsReceivable.status == status)
        if fiscal_year is not None:
            query = query.where(TdsReceivable.fiscal_year == fiscal_year)
        rows = await session.execute(query.order_by(TdsReceivable.deducted_on.desc()))
        return [_response(row) for row in rows.scalars().all()]

    @staticmethod
    async def update_tds(
        session: AsyncSession, org_id: uuid.UUID, receivable_id: uuid.UUID, payload: TdsReceivableUpdate, if_match: Optional[str]
    ) -> TdsReceivableResponse:
        row = await session.get(TdsReceivable, receivable_id)
        if row is None or row.organization_id != org_id:
            raise FinanceNotFoundError("TDS_RECEIVABLE_NOT_FOUND", f"TDS receivable '{receivable_id}' not found")
        check_version(if_match, row.version)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, field, value)
        row.version += 1
        await session.flush()
        return _response(row)

    @staticmethod
    async def gst_vs_cash(session: AsyncSession, org_id: uuid.UUID, period: str, currency: str = "INR") -> GstVsCashReport:
        first, next_month = _month(period)
        documents = (await session.execute(
            select(Invoice).where(
                Invoice.organization_id == org_id,
                Invoice.issue_date >= first,
                Invoice.issue_date < next_month,
                Invoice.status.not_in(("draft", "pending_approval")),
                Invoice.currency == currency,
            )
        )).scalars().all()
        sign = {invoice.id: (-1 if invoice.doc_type == "credit_note" else 1) for invoice in documents}
        tax_rows = (await session.execute(
            select(DocumentTaxLine).where(
                DocumentTaxLine.document_type == "invoice",
                DocumentTaxLine.document_id.in_(list(sign)),
                DocumentTaxLine.behaviour.in_(CHARGED),
            )
        )).scalars().all() if sign else []
        gst_on_documents = sum((sign[row.document_id] * to_decimal(row.tax_amount) for row in tax_rows), ZERO)
        documents_total = sum((sign[invoice.id] * to_decimal(invoice.grand_total) for invoice in documents), ZERO)

        settlements = (await session.execute(
            select(PaymentAllocation, Invoice)
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(
                Payment.organization_id == org_id,
                PaymentAllocation.allocated_at >= datetime.combine(first, datetime.min.time()),
                PaymentAllocation.allocated_at < datetime.combine(next_month, datetime.min.time()),
                Invoice.currency == currency,
            )
        )).all()
        cash = tds = gst_tds = gst_in_settlements = ZERO
        for allocation, invoice in settlements:
            settled = to_decimal(allocation.amount) + to_decimal(allocation.tds_amount) + to_decimal(allocation.gst_tds_amount)
            cash += to_decimal(allocation.amount)
            tds += to_decimal(allocation.tds_amount)
            gst_tds += to_decimal(allocation.gst_tds_amount)
            grand_total = to_decimal(invoice.grand_total)
            if grand_total > ZERO:
                invoice_gst = grand_total - to_decimal(invoice.taxable_total) - to_decimal(invoice.round_off)
                gst_in_settlements += settled * invoice_gst / grand_total

        def money(amount) -> Money:
            return Money(amount=as_float(round_money(amount, currency)), currency=currency)

        return GstVsCashReport(
            period=period, currency=currency, gst_on_documents=money(gst_on_documents), documents_total=money(documents_total),
            cash_collected=money(cash), tds_withheld=money(tds), gst_tds_withheld=money(gst_tds),
            gst_in_settlements=money(gst_in_settlements), gap=money(gst_on_documents - gst_in_settlements),
        )
