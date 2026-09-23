import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AllocationExceedsPaymentError,
    ClientNotFoundError,
    InvoiceNotFoundError,
    InvoiceOverallocatedError,
    PaymentNotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from models.client import Client
from models.invoice import Invoice
from models.payment import Payment, PaymentAllocation
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.opportunity import ClientRef
from schemas.payment import (
    AllocationBatch,
    PaymentAllocationResponse,
    PaymentCreate,
    PaymentResponse,
)


def format_payment_response(
    payment: Payment,
    client: Client,
    allocations_with_invoices: List[tuple[PaymentAllocation, Optional[str]]],
) -> PaymentResponse:
    alloc_responses = [
        PaymentAllocationResponse(
            invoice_id=alloc.invoice_id,
            invoice_no=inv_no,
            amount=Money(amount=float(alloc.amount), currency=payment.currency),
            allocated_at=alloc.allocated_at,
        )
        for alloc, inv_no in allocations_with_invoices
    ]

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
        tds_amount=Money(amount=0.0, currency=payment.currency),
        unallocated_amount=Money(amount=float(payment.unapplied_amount), currency=payment.currency),
        status=payment.status if payment.status in ("pending", "confirmed", "failed", "refunded", "partially_refunded") else "confirmed",
        allocations=alloc_responses,
        version=payment.version,
    )


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
    async def record_payment(
        session: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: PaymentCreate,
    ) -> PaymentResponse:
        client = await session.get(Client, payload.client_id)
        if not client:
            raise ClientNotFoundError(str(payload.client_id))

        current_year = datetime.now(timezone.utc).year
        count_res = await session.execute(
            select(func.count(Payment.id)).where(Payment.organization_id == org_id)
        )
        p_count = (count_res.scalar_one() or 0) + 1
        code = f"RC-{current_year}-{p_count:04d}"

        total_funds = payload.amount.amount
        if payload.tds_amount:
            total_funds += payload.tds_amount.amount

        payment = Payment(
            organization_id=org_id,
            client_id=client.id,
            receipt_no=code,
            amount=payload.amount.amount,
            currency=payload.amount.currency,
            method=payload.method,
            bank_reference=payload.bank_reference,
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
                inv = await session.get(Invoice, alloc_in.invoice_id)
                if not inv or inv.organization_id != org_id:
                    raise InvoiceNotFoundError(str(alloc_in.invoice_id))

                alloc_amt = alloc_in.amount.amount
                if alloc_amt > float(inv.balance_due):
                    raise InvoiceOverallocatedError(float(inv.balance_due), alloc_amt)
                if alloc_amt > float(payment.unapplied_amount):
                    raise AllocationExceedsPaymentError(float(payment.unapplied_amount), alloc_amt)

                inv.balance_due = max(0.0, float(inv.balance_due) - alloc_amt)
                inv.amount_settled = min(float(inv.grand_total), float(inv.amount_settled) + alloc_amt)
                if inv.balance_due == 0.0:
                    inv.status = "paid"
                else:
                    inv.status = "partially_paid"
                inv.version += 1

                pa = PaymentAllocation(
                    payment_id=payment.id,
                    invoice_id=inv.id,
                    amount=alloc_amt,
                )
                session.add(pa)
                persisted_allocations.append((pa, inv.invoice_no))
                payment.unapplied_amount = float(payment.unapplied_amount) - alloc_amt

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
            inv = await session.get(Invoice, alloc_in.invoice_id)
            if not inv or inv.organization_id != org_id:
                raise InvoiceNotFoundError(str(alloc_in.invoice_id))

            alloc_amt = alloc_in.amount.amount
            if alloc_amt > float(inv.balance_due):
                raise InvoiceOverallocatedError(float(inv.balance_due), alloc_amt)
            if alloc_amt > float(payment.unapplied_amount):
                raise AllocationExceedsPaymentError(float(payment.unapplied_amount), alloc_amt)

            inv.balance_due = max(0.0, float(inv.balance_due) - alloc_amt)
            inv.amount_settled = min(float(inv.grand_total), float(inv.amount_settled) + alloc_amt)
            if inv.balance_due == 0.0:
                inv.status = "paid"
            else:
                inv.status = "partially_paid"
            inv.version += 1

            pa = PaymentAllocation(
                payment_id=payment.id,
                invoice_id=inv.id,
                amount=alloc_amt,
            )
            session.add(pa)
            existing_allocs.append((pa, inv.invoice_no))
            payment.unapplied_amount = float(payment.unapplied_amount) - alloc_amt

        payment.version += 1
        await session.flush()
        return format_payment_response(payment, client, existing_allocs)
