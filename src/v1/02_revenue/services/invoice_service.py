import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ClientNotFoundError,
    InvalidStateTransitionError,
    InvoiceAlreadyIssuedError,
    InvoiceNotFoundError,
    InvoiceNotIssuedError,
    PreconditionRequiredError,
    VersionConflictError,
)
from models.client import Client
from models.invoice import Invoice, InvoiceLine
from models.invoice_series import InvoiceSeries
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.invoice import (
    CreditNoteCreate,
    DownloadUrl,
    InvoiceDraftCreate,
    InvoiceLineInput,
    InvoiceLineResponse,
    InvoiceResponse,
    InvoiceTotals,
)
from schemas.opportunity import ClientRef


def calculate_invoice_lines(
    lines_input: List[InvoiceLineInput],
    place_of_supply: str,
    supplier_state_code: str = "29",
) -> tuple[List[dict], InvoiceTotals]:
    processed = []
    taxable_acc = Decimal("0.00")
    cgst_acc = Decimal("0.00")
    sgst_acc = Decimal("0.00")
    igst_acc = Decimal("0.00")

    is_inter_state = place_of_supply.strip() != supplier_state_code.strip()

    for idx, line in enumerate(lines_input, start=1):
        qty = Decimal(str(line.quantity))
        unit_p = Decimal(str(line.unit_price.amount))
        disc = Decimal(str(line.discount.amount)) if line.discount else Decimal("0.00")

        taxable_val = (qty * unit_p) - disc
        gst_rate = Decimal(str(line.gst_rate))

        if is_inter_state:
            item_cgst = Decimal("0.00")
            item_sgst = Decimal("0.00")
            item_igst = (taxable_val * gst_rate) / Decimal("100.00")
        else:
            half = gst_rate / Decimal("2.00")
            item_cgst = (taxable_val * half) / Decimal("100.00")
            item_sgst = (taxable_val * half) / Decimal("100.00")
            item_igst = Decimal("0.00")

        line_total = taxable_val + item_cgst + item_sgst + item_igst

        taxable_acc += taxable_val
        cgst_acc += item_cgst
        sgst_acc += item_sgst
        igst_acc += item_igst

        processed.append(
            {
                "line_no": idx,
                "offering_id": line.offering_id,
                "description": line.description,
                "sac_code": line.sac_code,
                "quantity": float(qty),
                "unit_price": Money(amount=float(unit_p), currency=line.unit_price.currency),
                "discount": Money(amount=float(disc), currency=line.unit_price.currency),
                "taxable_value": Money(amount=float(taxable_val), currency=line.unit_price.currency),
                "gst_rate": float(gst_rate),
                "cgst": Money(amount=float(item_cgst), currency=line.unit_price.currency),
                "sgst": Money(amount=float(item_sgst), currency=line.unit_price.currency),
                "igst": Money(amount=float(item_igst), currency=line.unit_price.currency),
                "line_total": Money(amount=float(line_total), currency=line.unit_price.currency),
            }
        )

    grand = taxable_acc + cgst_acc + sgst_acc + igst_acc
    totals = InvoiceTotals(
        taxable_total=Money(amount=float(taxable_acc), currency="INR"),
        cgst_total=Money(amount=float(cgst_acc), currency="INR"),
        sgst_total=Money(amount=float(sgst_acc), currency="INR"),
        igst_total=Money(amount=float(igst_acc), currency="INR"),
        grand_total=Money(amount=float(grand), currency="INR"),
    )
    return processed, totals


def format_invoice_response(
    inv: Invoice,
    client: Client,
    lines: List[InvoiceLine],
    totals: InvoiceTotals,
) -> InvoiceResponse:
    line_responses = [
        InvoiceLineResponse(
            line_no=ln.line_no,
            description=ln.description,
            sac_code=ln.hsn_code,
            quantity=float(ln.quantity),
            unit_price=Money(amount=float(ln.unit_price), currency=inv.currency),
            discount=Money(amount=float(ln.discount), currency=inv.currency),
            taxable_value=Money(amount=float(ln.taxable_value), currency=inv.currency),
            gst_rate=18.0,
            cgst=Money(amount=float(ln.cgst_amount), currency=inv.currency),
            sgst=Money(amount=float(ln.sgst_amount), currency=inv.currency),
            igst=Money(amount=float(ln.igst_amount), currency=inv.currency),
            line_total=Money(amount=float(ln.line_total), currency=inv.currency),
        )
        for ln in lines
    ]

    return InvoiceResponse(
        id=inv.id,
        invoice_no=inv.invoice_no,
        doc_type=inv.doc_type,
        status=inv.status,
        client=ClientRef(id=client.id, name=client.name),
        contract_id=inv.contract_id,
        work_unit_id=inv.work_unit_id,
        original_invoice_id=inv.original_invoice_id,
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        supplier_gstin=inv.supplier_gstin,
        recipient_gstin=inv.recipient_gstin,
        place_of_supply=inv.place_of_supply,
        currency=inv.currency,
        lines=line_responses,
        totals=totals,
        amount_settled=Money(amount=float(inv.amount_settled), currency=inv.currency),
        balance_due=Money(amount=float(inv.balance_due), currency=inv.currency),
        e_invoice=None,
        pdf_document_id=inv.pdf_document_id,
        client_snapshot=inv.client_snapshot,
        version=inv.version,
    )


class InvoiceService:
    @staticmethod
    async def list_invoices(
        session: AsyncSession,
        org_id: uuid.UUID,
        status: Optional[str] = None,
        client_id: Optional[uuid.UUID] = None,
        contract_id: Optional[uuid.UUID] = None,
        issue_from: Optional[date] = None,
        issue_to: Optional[date] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PageResponse[InvoiceResponse]:
        query = (
            select(Invoice, Client)
            .join(Client, Client.id == Invoice.client_id)
            .where(Invoice.organization_id == org_id)
        )

        if status:
            query = query.where(Invoice.status == status)
        if client_id:
            query = query.where(Invoice.client_id == client_id)
        if contract_id:
            query = query.where(Invoice.contract_id == contract_id)
        if issue_from:
            query = query.where(Invoice.issue_date >= issue_from)
        if issue_to:
            query = query.where(Invoice.issue_date <= issue_to)

        if cursor:
            c_data = decode_cursor(cursor)
            if "last_id" in c_data:
                query = query.where(Invoice.id > uuid.UUID(c_data["last_id"]))

        query = query.order_by(Invoice.id.asc()).limit(limit + 1)
        res = await session.execute(query)
        rows = list(res.all())

        has_more = len(rows) > limit
        data_rows = rows[:limit]

        next_cursor = None
        if has_more and data_rows:
            next_cursor = encode_cursor({"last_id": str(data_rows[-1][0].id)})

        items_resp = []
        for inv, client in data_rows:
            ln_res = await session.execute(
                select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no.asc())
            )
            lines = list(ln_res.scalars().all())
            totals = InvoiceTotals(
                taxable_total=Money(amount=float(inv.taxable_total), currency=inv.currency),
                cgst_total=Money(amount=float(inv.cgst_total), currency=inv.currency),
                sgst_total=Money(amount=float(inv.sgst_total), currency=inv.currency),
                igst_total=Money(amount=float(inv.igst_total), currency=inv.currency),
                grand_total=Money(amount=float(inv.grand_total), currency=inv.currency),
            )
            items_resp.append(format_invoice_response(inv, client, lines, totals))

        return PageResponse(
            data=items_resp,
            page=PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    @staticmethod
    async def create_draft_invoice(
        session: AsyncSession,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: InvoiceDraftCreate,
    ) -> InvoiceResponse:
        client = await session.get(Client, payload.client_id)
        if not client:
            raise ClientNotFoundError(str(payload.client_id))

        supplier_gstin = "29AABCF9876L1Z3"
        place_of_supply = "29"
        if client.billing_address:
            try:
                addr_dict = json.loads(client.billing_address) if isinstance(client.billing_address, str) else client.billing_address
                place_of_supply = addr_dict.get("state_code", "29")
            except (json.JSONDecodeError, AttributeError, TypeError):
                place_of_supply = "29"

        processed_lines, totals = calculate_invoice_lines(
            lines_input=payload.lines,
            place_of_supply=place_of_supply,
            supplier_state_code=supplier_gstin[:2],
        )

        inv = Invoice(
            organization_id=org_id,
            client_id=client.id,
            contract_id=payload.contract_id,
            doc_type="tax_invoice",
            status="draft",
            due_date=payload.due_date or (date.today() + timedelta(days=15)),
            supplier_gstin=supplier_gstin,
            recipient_gstin=client.gstin,
            place_of_supply=place_of_supply,
            currency="INR",
            taxable_total=totals.taxable_total.amount,
            cgst_total=totals.cgst_total.amount,
            sgst_total=totals.sgst_total.amount,
            igst_total=totals.igst_total.amount,
            grand_total=totals.grand_total.amount,
            amount_settled=0.0,
            balance_due=totals.grand_total.amount,
            issued_by=user_id,
            version=1,
        )
        session.add(inv)
        await session.flush()

        persisted_lines = []
        for p in processed_lines:
            line_obj = InvoiceLine(
                invoice_id=inv.id,
                offering_id=p["offering_id"],
                line_no=p["line_no"],
                description=p["description"],
                hsn_code=p["sac_code"],
                quantity=p["quantity"],
                unit_price=p["unit_price"].amount,
                discount=p["discount"].amount,
                taxable_value=p["taxable_value"].amount,
                cgst_amount=p["cgst"].amount,
                sgst_amount=p["sgst"].amount,
                igst_amount=p["igst"].amount,
                line_total=p["line_total"].amount,
            )
            session.add(line_obj)
            persisted_lines.append(line_obj)

        await session.flush()
        return format_invoice_response(inv, client, persisted_lines, totals)

    @staticmethod
    async def get_invoice(
        session: AsyncSession,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> InvoiceResponse:
        inv = await session.get(Invoice, invoice_id)
        if not inv or inv.organization_id != org_id:
            raise InvoiceNotFoundError(str(invoice_id))

        client = await session.get(Client, inv.client_id)
        ln_res = await session.execute(
            select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no.asc())
        )
        lines = list(ln_res.scalars().all())

        totals = InvoiceTotals(
            taxable_total=Money(amount=float(inv.taxable_total), currency=inv.currency),
            cgst_total=Money(amount=float(inv.cgst_total), currency=inv.currency),
            sgst_total=Money(amount=float(inv.sgst_total), currency=inv.currency),
            igst_total=Money(amount=float(inv.igst_total), currency=inv.currency),
            grand_total=Money(amount=float(inv.grand_total), currency=inv.currency),
        )
        return format_invoice_response(inv, client, lines, totals)

    @staticmethod
    async def issue_invoice(
        session: AsyncSession,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        if_match: Optional[str] = None,
    ) -> InvoiceResponse:
        inv = await session.get(Invoice, invoice_id)
        if not inv or inv.organization_id != org_id:
            raise InvoiceNotFoundError(str(invoice_id))

        if if_match is None:
            raise PreconditionRequiredError()
        expected_version = int(if_match.strip('"').replace("W/", ""))
        if inv.version != expected_version:
            raise VersionConflictError(inv.version)

        if inv.status == "issued":
            raise InvoiceAlreadyIssuedError(inv.invoice_no or str(invoice_id))

        if inv.status != "draft":
            raise InvalidStateTransitionError(inv.status, "issue")

        client = await session.get(Client, inv.client_id)

        # Gapless number sequence
        count_res = await session.execute(
            select(func.count(Invoice.id)).where(Invoice.organization_id == org_id, Invoice.status != "draft")
        )
        issued_count = (count_res.scalar_one() or 0) + 1
        fy = "26-27"
        inv.invoice_no = f"FTB/{fy}/{issued_count:06d}"
        inv.status = "issued"
        inv.issue_date = date.today()
        if not inv.due_date:
            inv.due_date = date.today() + timedelta(days=15)
        inv.issued_by = user_id

        # Snapshot client
        addr_str = ""
        if client.billing_address:
            try:
                ad = json.loads(client.billing_address) if isinstance(client.billing_address, str) else client.billing_address
                addr_str = f"{ad.get('line1', '')}, {ad.get('city', '')} {ad.get('postal_code', '')}"
            except (json.JSONDecodeError, AttributeError, TypeError):
                addr_str = ""

        inv.client_snapshot = {
            "legal_name": client.legal_name or client.name,
            "gstin": client.gstin,
            "address": addr_str,
        }

        inv.version += 1
        await session.flush()
        return await InvoiceService.get_invoice(session, invoice_id, org_id)

    @staticmethod
    async def issue_credit_note(
        session: AsyncSession,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: CreditNoteCreate,
    ) -> InvoiceResponse:
        orig_inv = await session.get(Invoice, invoice_id)
        if not orig_inv or orig_inv.organization_id != org_id:
            raise InvoiceNotFoundError(str(invoice_id))

        if orig_inv.status not in ("issued", "partially_paid", "paid", "overdue"):
            raise InvoiceNotIssuedError(orig_inv.status)

        client = await session.get(Client, orig_inv.client_id)

        # Lines or full reversal
        if payload.lines:
            processed_lines, totals = calculate_invoice_lines(
                lines_input=payload.lines,
                place_of_supply=orig_inv.place_of_supply,
                supplier_state_code=orig_inv.supplier_gstin[:2],
            )
        else:
            # Full reversal
            orig_lines_res = await session.execute(
                select(InvoiceLine).where(InvoiceLine.invoice_id == orig_inv.id)
            )
            converted_lines = [
                InvoiceLineInput(
                    description=f"Credit adjustment: {ln.description}",
                    sac_code=ln.hsn_code,
                    quantity=float(ln.quantity),
                    unit_price=Money(amount=float(ln.unit_price), currency=orig_inv.currency),
                    gst_rate=18.0,
                    discount=Money(amount=float(ln.discount), currency=orig_inv.currency),
                )
                for ln in orig_lines_res.scalars().all()
            ]
            processed_lines, totals = calculate_invoice_lines(
                lines_input=converted_lines,
                place_of_supply=orig_inv.place_of_supply,
                supplier_state_code=orig_inv.supplier_gstin[:2],
            )

        count_res = await session.execute(
            select(func.count(Invoice.id)).where(Invoice.organization_id == org_id, Invoice.doc_type == "credit_note")
        )
        cn_count = (count_res.scalar_one() or 0) + 1
        cn_no = f"CN/26-27/{cn_count:06d}"

        cn = Invoice(
            organization_id=org_id,
            client_id=client.id,
            original_invoice_id=orig_inv.id,
            invoice_no=cn_no,
            doc_type="credit_note",
            status="issued",
            issue_date=date.today(),
            supplier_gstin=orig_inv.supplier_gstin,
            recipient_gstin=orig_inv.recipient_gstin,
            place_of_supply=orig_inv.place_of_supply,
            currency=orig_inv.currency,
            taxable_total=totals.taxable_total.amount,
            cgst_total=totals.cgst_total.amount,
            sgst_total=totals.sgst_total.amount,
            igst_total=totals.igst_total.amount,
            grand_total=totals.grand_total.amount,
            amount_settled=totals.grand_total.amount,
            balance_due=0.0,
            issued_by=user_id,
            client_snapshot=orig_inv.client_snapshot,
            version=1,
        )
        session.add(cn)
        await session.flush()

        persisted_lines = []
        for p in processed_lines:
            ln = InvoiceLine(
                invoice_id=cn.id,
                offering_id=p["offering_id"],
                line_no=p["line_no"],
                description=p["description"],
                hsn_code=p["sac_code"],
                quantity=p["quantity"],
                unit_price=p["unit_price"].amount,
                discount=p["discount"].amount,
                taxable_value=p["taxable_value"].amount,
                cgst_amount=p["cgst"].amount,
                sgst_amount=p["sgst"].amount,
                igst_amount=p["igst"].amount,
                line_total=p["line_total"].amount,
            )
            session.add(ln)
            persisted_lines.append(ln)

        # Reduce balance_due on original invoice
        credited_amt = totals.grand_total.amount
        orig_inv.balance_due = max(0.0, float(orig_inv.balance_due) - credited_amt)
        orig_inv.amount_settled = min(float(orig_inv.grand_total), float(orig_inv.amount_settled) + credited_amt)
        if orig_inv.balance_due == 0.0:
            orig_inv.status = "paid"
        else:
            orig_inv.status = "partially_paid"
        orig_inv.version += 1

        await session.flush()
        return format_invoice_response(cn, client, persisted_lines, totals)

    @staticmethod
    async def get_invoice_pdf(
        session: AsyncSession,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> DownloadUrl:
        inv = await session.get(Invoice, invoice_id)
        if not inv or inv.organization_id != org_id:
            raise InvoiceNotFoundError(str(invoice_id))

        safe_no = (inv.invoice_no or str(inv.id)).replace("/", "-")
        return DownloadUrl(
            url=f"https://fbos-documents.s3.ap-south-1.amazonaws.com/invoices/{safe_no}.pdf",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=60),
            file_name=f"{safe_no}.pdf",
        )
