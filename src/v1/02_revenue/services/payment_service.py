import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AllocationClientMismatchError,
    AllocationExceedsPaymentError,
    ClientNotFoundError,
    InvoiceNotFoundError,
    InvoiceNotIssuedError,
    InvoiceOverallocatedError,
    PaymentNotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from finance import policies
from finance.fiscal import fiscal_year_of
from finance.money import ZERO, as_float, to_decimal
from finance.numbering import next_document_number
from finance.receivables import settlement
from finance.tax.store import load_snapshot
from models.client import Client
from models.client_tax_profile import ClientTaxProfile
from models.invoice import Invoice
from models.payment import Payment, PaymentAllocation
from models.receivables import TdsReceivable
from models.tax_registration import OrgTaxRegistration
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.opportunity import ClientRef
from schemas.payment import (
    AllocationBatch,
    PaymentAllocationInput,
    PaymentAllocationResponse,
    PaymentCreate,
    PaymentResponse,
)


def format_payment_response(
    payment: Payment,
    client: Client,
    allocations_with_invoices: List[tuple[PaymentAllocation, Optional[str]]],
) -> PaymentResponse:
    currency = payment.currency
    alloc_responses = [
        PaymentAllocationResponse(
            invoice_id=alloc.invoice_id,
            invoice_no=inv_no,
            amount=Money(amount=float(alloc.amount), currency=currency),
            tds_amount=Money(amount=float(alloc.tds_amount or 0), currency=currency),
            tds_section_code=alloc.tds_section_code,
            gst_tds_amount=Money(amount=float(alloc.gst_tds_amount or 0), currency=currency),
            allocated_at=alloc.allocated_at,
        )
        for alloc, inv_no in allocations_with_invoices
    ]
    withheld = to_decimal(payment.tds_amount) + sum(
        (to_decimal(alloc.tds_amount) for alloc, _ in allocations_with_invoices), ZERO
    )

    return PaymentResponse(
        id=payment.id,
        code=payment.receipt_no,
        client=ClientRef(id=client.id, name=client.name),
        received_on=payment.received_at.date() if payment.received_at else date.today(),
        amount=Money(amount=float(payment.amount), currency=payment.currency),
        method=payment.method,
        gateway=payment.gateway,
        gateway_payment_id=payment.gateway_payment_id,
        bank_reference=payment.bank_reference,
        tds_amount=Money(amount=as_float(withheld), currency=payment.currency),
        unallocated_amount=Money(amount=float(payment.unapplied_amount), currency=payment.currency),
        status=payment.status if payment.status in ("pending", "confirmed", "failed", "refunded", "partially_refunded") else "confirmed",
        allocations=alloc_responses,
        version=payment.version,
    )


# Documents a payment can settle: issued invoices and debit notes that still have a balance.
PAYABLE_DOC_TYPES = ("tax_invoice", "debit_note")


async def _apply_allocation(
    session: AsyncSession,
    org_id: uuid.UUID,
    payment: Payment,
    allocation_input: PaymentAllocationInput,
    allocated_at: datetime,
) -> tuple[PaymentAllocation, Optional[str]]:
    """
    Settle an invoice with cash from the payment plus what the customer withheld for it.
    Withheld income tax becomes a TDS receivable: owed by the government until claimed.
    """
    inv = await session.get(Invoice, allocation_input.invoice_id)
    if not inv or inv.organization_id != org_id:
        raise InvoiceNotFoundError(str(allocation_input.invoice_id))
    if inv.client_id != payment.client_id:
        raise AllocationClientMismatchError()
    if inv.doc_type not in PAYABLE_DOC_TYPES or inv.status not in settlement.OPEN_STATUSES:
        raise InvoiceNotIssuedError(inv.status)

    cash = to_decimal(allocation_input.amount.amount)
    tds = to_decimal(allocation_input.tds_amount.amount) if allocation_input.tds_amount else ZERO
    gst_tds = to_decimal(allocation_input.gst_tds_amount.amount) if allocation_input.gst_tds_amount else ZERO
    settled = cash + tds + gst_tds
    if settled > to_decimal(inv.balance_due):
        raise InvoiceOverallocatedError(float(inv.balance_due), float(settled))
    if cash > to_decimal(payment.unapplied_amount):
        raise AllocationExceedsPaymentError(float(payment.unapplied_amount), float(cash))

    settlement.apply_settlement(inv, settled)
    section_code = allocation_input.tds_section_code
    if tds > ZERO and section_code is None:
        profile = await session.get(ClientTaxProfile, payment.client_id)
        section_code = profile.tds_section_code if profile else None
    allocation = PaymentAllocation(
        payment_id=payment.id, invoice_id=inv.id, amount=cash, tds_amount=tds, tds_section_code=section_code,
        gst_tds_amount=gst_tds, allocated_at=allocated_at,
    )
    session.add(allocation)
    await session.flush()
    payment.unapplied_amount = to_decimal(payment.unapplied_amount) - cash
    if tds > ZERO:
        await _record_tds_receivable(session, org_id, payment, inv, allocation, tds, section_code, allocated_at.date())
    return allocation, inv.invoice_no


async def _record_tds_receivable(
    session: AsyncSession,
    org_id: uuid.UUID,
    payment: Payment,
    invoice: Invoice,
    allocation: PaymentAllocation,
    amount: Decimal,
    section_code: Optional[str],
    deducted_on: date,
) -> None:
    snapshot = await load_snapshot(session, org_id, deducted_on)
    section = snapshot.withholding_section(section_code) if section_code else None
    registration = await session.get(OrgTaxRegistration, invoice.tax_registration_id) if invoice.tax_registration_id else None
    regime_entry = snapshot.find("regime", registration.regime_code) if registration else None
    settings = await policies.load_settings(session, org_id)
    fiscal_year = fiscal_year_of(deducted_on, policies.fiscal_year_start(settings, regime_entry.data if regime_entry else None))  # type: ignore[arg-type]
    session.add(TdsReceivable(
        organization_id=org_id, client_id=payment.client_id, payment_id=payment.id, allocation_id=allocation.id,
        invoice_id=invoice.id, section_code=section[0] if section else section_code,
        statute_ref=section[1].statute_ref if section else None, amount=amount, deducted_on=deducted_on,
        fiscal_year=fiscal_year.label, quarter=fiscal_year.quarter_of(deducted_on),
    ))


async def _receipt_number(session: AsyncSession, org_id: uuid.UUID, received_on: date) -> str:
    snapshot = await load_snapshot(session, org_id, received_on)
    settings = await policies.load_settings(session, org_id)

    async def numbers_used() -> list[str]:
        rows = await session.execute(select(Payment.receipt_no).where(Payment.organization_id == org_id))
        return list(rows.scalars().all())

    _, number = await next_document_number(
        session, org_id, "payment_receipt", received_on, snapshot, policies.fiscal_year_start(settings, None), numbers_used
    )
    return number


class PaymentService:
    @staticmethod
    async def list_payments(
        session: AsyncSession,
        org_id: uuid.UUID,
        client_id: Optional[uuid.UUID] = None,
        received_from: Optional[date] = None,
        received_to: Optional[date] = None,
        unallocated: Optional[bool] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[PaymentResponse]:
        query = (
            select(Payment, Client)
            .join(Client, Client.id == Payment.client_id)
            .where(Payment.organization_id == org_id)
        )

        if client_id:
            query = query.where(Payment.client_id == client_id)
        if received_from:
            query = query.where(Payment.received_at >= datetime.combine(received_from, datetime.min.time()))
        if received_to:
            query = query.where(Payment.received_at <= datetime.combine(received_to, datetime.max.time()))
        if unallocated:
            query = query.where(Payment.unapplied_amount > 0)

        if cursor:
            c_data = decode_cursor(cursor)
            if "last_id" in c_data:
                query = query.where(Payment.id > uuid.UUID(c_data["last_id"]))

        query = query.order_by(Payment.id.asc()).limit(limit + 1)
        res = await session.execute(query)
        rows = list(res.all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_id": str(data_rows[-1][0].id)})

        items_resp = []
        for payment, client in data_rows:
            alloc_query = (
                select(PaymentAllocation, Invoice.invoice_no)
                .outerjoin(Invoice, Invoice.id == PaymentAllocation.invoice_id)
                .where(PaymentAllocation.payment_id == payment.id)
            )
            alloc_res = await session.execute(alloc_query)
            allocs = list(alloc_res.all())
            items_resp.append(format_payment_response(payment, client, allocs))

        return PageResponse(
            data=items_resp,
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def get_payment(session: AsyncSession, payment_id: uuid.UUID, org_id: uuid.UUID) -> PaymentResponse:
        payment = await session.get(Payment, payment_id)
        if not payment or payment.organization_id != org_id:
            raise PaymentNotFoundError(str(payment_id))
        client = await session.get(Client, payment.client_id)
        allocations = await session.execute(
            select(PaymentAllocation, Invoice.invoice_no)
            .outerjoin(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(PaymentAllocation.payment_id == payment.id)
        )
        return format_payment_response(payment, client, list(allocations.all()))

    @staticmethod
    async def record_payment(
        session: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: PaymentCreate,
    ) -> PaymentResponse:
        client = await session.get(Client, payload.client_id)
        if not client or client.organization_id != org_id:
            raise ClientNotFoundError(str(payload.client_id))

        code = await _receipt_number(session, org_id, payload.received_on)
        legacy_tds = to_decimal(payload.tds_amount.amount) if payload.tds_amount else ZERO
        total_funds = to_decimal(payload.amount.amount) + legacy_tds

        payment = Payment(
            organization_id=org_id,
            client_id=client.id,
            receipt_no=code,
            amount=payload.amount.amount,
            currency=payload.amount.currency,
            method=payload.method,
            bank_reference=payload.bank_reference,
            tds_amount=legacy_tds,
            unapplied_amount=total_funds,
            status="confirmed",
            recorded_by=user_id,
            received_at=datetime.combine(payload.received_on, datetime.min.time()),
        )
        session.add(payment)
        await session.flush()

        # Handle immediate allocations if provided
        persisted_allocations = []
        if payload.allocations:
            for alloc_in in payload.allocations:
                # Allocations recorded with the payment default to its received date.
                allocated_at = datetime.combine(alloc_in.allocated_on or payload.received_on, datetime.min.time())
                persisted_allocations.append(await _apply_allocation(session, org_id, payment, alloc_in, allocated_at))

        await session.flush()
        return format_payment_response(payment, client, persisted_allocations)

    @staticmethod
    async def allocate_payment(
        session: AsyncSession,
        payment_id: uuid.UUID,
        org_id: uuid.UUID,
        payload: AllocationBatch,
        if_match: Optional[str] = None,
    ) -> PaymentResponse:
        payment = await session.get(Payment, payment_id)
        if not payment or payment.organization_id != org_id:
            raise PaymentNotFoundError(str(payment_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if payment.version != expected_version:
            raise VersionConflictError(payment.version)

        client = await session.get(Client, payment.client_id)

        alloc_query = (
            select(PaymentAllocation, Invoice.invoice_no)
            .outerjoin(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(PaymentAllocation.payment_id == payment.id)
        )
        alloc_res = await session.execute(alloc_query)
        existing_allocs = list(alloc_res.all())

        for alloc_in in payload.allocations:
            allocated_at = (
                datetime.combine(alloc_in.allocated_on, datetime.min.time())
                if alloc_in.allocated_on
                else datetime.now(timezone.utc).replace(tzinfo=None)
            )
            existing_allocs.append(await _apply_allocation(session, org_id, payment, alloc_in, allocated_at))

        payment.version += 1
        await session.flush()
        return format_payment_response(payment, client, existing_allocs)
