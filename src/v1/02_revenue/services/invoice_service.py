"""
Invoices, credit notes and debit notes.

Taxes come from the tax engine (services/tax_service.py) on the organization's configuration:
worked out when a draft is saved, worked out again as of the issue date when it is issued,
then frozen. Numbers come from series templates. Credit notes copy the original's tax
treatment and never mark an invoice paid; write-offs change no tax.
"""

from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    ClientNotFoundError,
    ContractNotFoundError,
    InvalidStateTransitionError,
    InvoiceAlreadyIssuedError,
    InvoiceNotFoundError,
    InvoiceNotIssuedError,
    InvoicePdfNotAvailableError,
    OfferingNotFoundError,
    PreconditionRequiredError,
    VersionConflictError,
)
from finance import policies
from finance.deadlines import Deadline, deadlines_for
from finance.errors import FinanceConflictError, TaxConfigError
from finance.money import ZERO, as_float, to_decimal
from finance.numbering import next_document_number
from finance.receivables import settlement
from finance.tax.result import TaxResult
from finance.tax.store import load_snapshot
from models.billing import BillingSchedule
from models.client import Client
from models.contract import Contract
from models.document_tax import DocumentTaxLine
from models.invoice import Invoice, InvoiceLine
from models.offering import Offering
from models.receivables import InvoiceWriteOff
from models.tax_registration import OrgTaxRegistration
from schemas.common import Money, PageMeta, PageResponse, decode_cursor, encode_cursor
from schemas.invoice import (
    CreditNoteCreate,
    DebitNoteCreate,
    DownloadUrl,
    InvoiceDraftCreate,
    InvoiceIssue,
    InvoiceLineInput,
    InvoiceLineResponse,
    InvoiceResponse,
    InvoiceTotals,
    WriteOffCreate,
)
from schemas.opportunity import ClientRef
from schemas.tax import DeadlineInfo, LineTax, TaxAmount, WithholdingPreview
from services.tax_service import (
    DocumentLineSpec,
    TaxCalculation,
    calculate_document,
    copy_tax_lines,
    group_by_document,
    legacy_rate,
    legacy_split,
    load_tax_lines,
    parse_address,
    registration_snapshot,
    replace_tax_lines,
    totals_of,
    withholding_json,
)

TAX_DOCUMENT = "invoice"  # DocumentTaxLine.document_type for every invoice doc_type
CREDITABLE_STATUSES = ("issued", "partially_paid", "paid", "overdue")


@dataclass(frozen=True)
class DraftLine:
    """A line to put on a document: what it says, plus what the tax engine needs."""

    description: str
    offering_id: Optional[uuid.UUID]
    spec: DocumentLineSpec


# ---------------------------------------------------------------- building lines


async def _offerings_for(session: AsyncSession, org_id: uuid.UUID, ids: Iterable[Optional[uuid.UUID]]) -> dict[uuid.UUID, Offering]:
    wanted = {offering_id for offering_id in ids if offering_id is not None}
    if not wanted:
        return {}
    rows = await session.execute(select(Offering).where(Offering.id.in_(wanted), Offering.organization_id == org_id))
    found = {offering.id: offering for offering in rows.scalars().all()}
    missing = wanted - set(found)
    if missing:
        raise OfferingNotFoundError(str(next(iter(missing))))
    return found


def draft_lines_from_inputs(lines: List[InvoiceLineInput], offerings: dict[uuid.UUID, Offering]) -> list[DraftLine]:
    """Category precedence: the line's, the offering's, the line's legacy rate, the offering's legacy rate."""
    drafted = []
    for line_no, line in enumerate(lines, start=1):
        offering = offerings.get(line.offering_id) if line.offering_id else None
        category = line.tax_category_code or (offering.tax_category_code if offering else None)
        rate = None
        if category is None:
            if line.gst_rate is not None:
                rate = to_decimal(line.gst_rate)
            elif offering is not None:
                rate = legacy_rate(offering.gst_code)
        drafted.append(DraftLine(
            description=line.description,
            offering_id=line.offering_id,
            spec=DocumentLineSpec(
                line_no=line_no,
                quantity=to_decimal(line.quantity),
                unit_price=to_decimal(line.unit_price.amount),
                discount_amount=to_decimal(line.discount.amount) if line.discount else ZERO,
                category_code=category,
                legacy_rate=rate,
                classification_code=line.sac_code or (offering.sac_code if offering else None),
            ),
        ))
    return drafted


def _specs_from_stored(lines: list[InvoiceLine]) -> list[DocumentLineSpec]:
    return [
        DocumentLineSpec(
            line_no=line.line_no,
            quantity=to_decimal(line.quantity),
            unit_price=to_decimal(line.unit_price),
            discount_amount=to_decimal(line.discount),
            category_code=line.tax_category_code,
            classification_code=line.hsn_code,
        )
        for line in lines
    ]


# ---------------------------------------------------------------- writing results


def _write_header(invoice: Invoice, calculation: TaxCalculation, client: Client, tax_point: date) -> None:
    result = calculation.result
    split = legacy_split(result.taxes)
    invoice.tax_registration_id = calculation.registration.id
    invoice.supplier_gstin = calculation.registration.registration_no
    invoice.recipient_gstin = client.gstin
    invoice.place_of_supply = result.place_of_supply or _customer_country(client, calculation)
    invoice.supply_type = result.supply_type
    invoice.reverse_charge = result.reverse_charge
    invoice.tax_point_date = tax_point
    invoice.config_revision = result.config_revision
    invoice.tax_notes = list(result.notes)
    invoice.withholding = withholding_json(result)
    invoice.expected_withholding = result.withheld_total
    invoice.taxable_total = result.taxable_total
    invoice.cgst_total, invoice.sgst_total, invoice.igst_total = split["cgst"], split["sgst"], split["igst"]
    invoice.round_off = result.round_off
    invoice.grand_total = result.grand_total


def _customer_country(client: Client, calculation: TaxCalculation) -> str:
    return (parse_address(client.billing_address).get("country") or calculation.regime.country).upper()


def _write_lines(invoice_id: uuid.UUID, result: TaxResult, drafted: list[DraftLine]) -> list[InvoiceLine]:
    rows = []
    for line, draft in zip(result.lines, drafted):
        split = legacy_split(line.taxes)
        rows.append(InvoiceLine(
            invoice_id=invoice_id, offering_id=draft.offering_id, line_no=line.line_no, description=draft.description,
            hsn_code=line.classification_code, quantity=draft.spec.quantity, unit_price=draft.spec.unit_price,
            discount=line.discount, taxable_value=line.taxable_value, cgst_amount=split["cgst"],
            sgst_amount=split["sgst"], igst_amount=split["igst"], line_total=line.line_total,
            tax_category_code=line.category_code, tax_rate=line.effective_percent,
        ))
    return rows


def _refresh_lines(stored: list[InvoiceLine], result: TaxResult) -> None:
    by_line = {line.line_no: line for line in result.lines}
    for row in stored:
        line = by_line[row.line_no]
        split = legacy_split(line.taxes)
        row.discount, row.taxable_value, row.line_total = line.discount, line.taxable_value, line.line_total
        row.cgst_amount, row.sgst_amount, row.igst_amount = split["cgst"], split["sgst"], split["igst"]
        row.tax_category_code, row.tax_rate, row.hsn_code = line.category_code, line.effective_percent, line.classification_code


# ---------------------------------------------------------------- reading back


def _money(amount, currency: str) -> Money:
    return Money(amount=as_float(to_decimal(amount)), currency=currency)


def _line_taxes(tax_lines: list[DocumentTaxLine], line_no: int, currency: str) -> list[LineTax]:
    return [
        LineTax(component_code=tax.component_code, label=tax.label, behaviour=tax.behaviour,
                rate=as_float(to_decimal(tax.rate_percent)), amount=_money(tax.tax_amount, currency),
                base=_money(tax.base_amount, currency), rule_code=tax.rule_code)
        for tax in tax_lines
        if tax.line_no == line_no
    ]


def _totals(invoice: Invoice, tax_lines: list[DocumentTaxLine]) -> InvoiceTotals:
    currency = invoice.currency
    totals = totals_of(tax_lines)
    return InvoiceTotals(
        taxable_total=_money(invoice.taxable_total, currency),
        cgst_total=_money(invoice.cgst_total, currency),
        sgst_total=_money(invoice.sgst_total, currency),
        igst_total=_money(invoice.igst_total, currency),
        grand_total=_money(invoice.grand_total, currency),
        taxes=[
            TaxAmount(component_code=total.component_code, label=total.label, behaviour=total.behaviour,
                      rate=as_float(total.percent), amount=_money(total.amount, currency))
            for total in totals
        ],
        tax_total=_money(sum((total.amount for total in totals if total.behaviour in ("added", "collected")), ZERO), currency),
        round_off=_money(invoice.round_off, currency),
    )


def _withholding_previews(invoice: Invoice) -> list[WithholdingPreview]:
    currency = invoice.currency
    return [
        WithholdingPreview(
            section_code=item["section_code"], statute_ref=item["statute_ref"], payment_code=item.get("payment_code"),
            rate=float(item["percent"]), base=_money(item["base"], currency), amount=_money(item["amount"], currency),
            certificate_no=item.get("certificate_no"),
        )
        for item in invoice.withholding or []
    ]


def format_invoice_response(
    invoice: Invoice,
    client: Client,
    lines: List[InvoiceLine],
    tax_lines: list[DocumentTaxLine],
    deadlines: Optional[list[DeadlineInfo]] = None,
) -> InvoiceResponse:
    currency = invoice.currency
    line_responses = [
        InvoiceLineResponse(
            line_no=line.line_no,
            description=line.description,
            sac_code=line.hsn_code,
            quantity=float(line.quantity),
            unit_price=_money(line.unit_price, currency),
            discount=_money(line.discount, currency),
            taxable_value=_money(line.taxable_value, currency),
            gst_rate=as_float(to_decimal(line.tax_rate)) if line.tax_rate is not None else 0.0,
            cgst=_money(line.cgst_amount, currency),
            sgst=_money(line.sgst_amount, currency),
            igst=_money(line.igst_amount, currency),
            line_total=_money(line.line_total, currency),
            tax_category_code=line.tax_category_code,
            taxes=_line_taxes(tax_lines, line.line_no, currency),
        )
        for line in lines
    ]
    return InvoiceResponse(
        id=invoice.id,
        invoice_no=invoice.invoice_no,
        doc_type=invoice.doc_type,
        status=invoice.status,
        client=ClientRef(id=client.id, name=client.name),
        contract_id=invoice.contract_id,
        work_unit_id=invoice.work_unit_id,
        original_invoice_id=invoice.original_invoice_id,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        supplier_gstin=invoice.supplier_gstin,
        recipient_gstin=invoice.recipient_gstin,
        place_of_supply=invoice.place_of_supply,
        currency=currency,
        lines=line_responses,
        totals=_totals(invoice, tax_lines),
        amount_settled=_money(invoice.amount_settled, currency),
        balance_due=_money(invoice.balance_due, currency),
        e_invoice=None,
        pdf_document_id=invoice.pdf_document_id,
        client_snapshot=invoice.client_snapshot,
        version=invoice.version,
        tax_registration_id=invoice.tax_registration_id,
        supplier_snapshot=invoice.supplier_snapshot,
        supply_type=invoice.supply_type,
        tax_point_date=invoice.tax_point_date,
        tax_notes=list(invoice.tax_notes or []),
        withholding=_withholding_previews(invoice),
        net_receivable=_money(to_decimal(invoice.grand_total) - to_decimal(invoice.expected_withholding), currency),
        credited_amount=_money(invoice.credited_amount, currency),
        written_off_amount=_money(invoice.written_off_amount, currency),
        schedule_line_id=invoice.schedule_line_id,
        note_reason=invoice.note_reason,
        deadlines=deadlines or [],
    )


async def _lines_of(session: AsyncSession, invoice_id: uuid.UUID) -> list[InvoiceLine]:
    rows = await session.execute(
        select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id).order_by(InvoiceLine.line_no.asc())
    )
    return list(rows.scalars().all())


async def _invoice_in_org(session: AsyncSession, org_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    invoice = await session.get(Invoice, invoice_id)
    if not invoice or invoice.organization_id != org_id:
        raise InvoiceNotFoundError(str(invoice_id))
    return invoice


def _check_version(if_match: Optional[str], version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    if int(if_match.strip('"').replace("W/", "")) != version:
        raise VersionConflictError(version)


async def _numbers_used(session: AsyncSession, org_id: uuid.UUID, doc_type: str, supplier_gstin: Optional[str]) -> list[str]:
    rows = await session.execute(
        select(Invoice.invoice_no).where(
            Invoice.organization_id == org_id, Invoice.doc_type == doc_type, Invoice.supplier_gstin == supplier_gstin,
            Invoice.invoice_no.is_not(None),
        )
    )
    return [number for number in rows.scalars().all() if number]


async def _issue_number(
    session: AsyncSession, org_id: uuid.UUID, doc_type: str, on: date, registration_id: Optional[uuid.UUID]
) -> str:
    """The next number in the registration's series for this document type, as of `on`."""
    snapshot = await load_snapshot(session, org_id, on)
    settings = await policies.load_settings(session, org_id)
    registration = await session.get(OrgTaxRegistration, registration_id) if registration_id else None
    regime = snapshot.regime(registration.regime_code) if registration else None
    _, number = await next_document_number(
        session, org_id, doc_type, on, snapshot, policies.fiscal_year_start(settings, regime),
        existing_numbers=lambda: _numbers_used(session, org_id, doc_type, registration.registration_no if registration else None),
        registration_id=registration_id,
        number_rules=regime.document_number if regime else None,
        jurisdiction=registration.jurisdiction_code if registration else None,
    )
    return number


def _client_snapshot(client: Client) -> dict:
    address = parse_address(client.billing_address)
    return {
        "legal_name": client.legal_name or client.name,
        "gstin": client.gstin,
        "address": f"{address.get('line1', '')}, {address.get('city', '')} {address.get('postal_code', '')}" if address else "",
        "state_code": address.get("state_code"),
        "country": address.get("country"),
    }


# ---------------------------------------------------------------- service


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
        query = select(Invoice, Client).join(Client, Client.id == Invoice.client_id).where(Invoice.organization_id == org_id)
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
            cursor_data = decode_cursor(cursor)
            if "last_id" in cursor_data:
                query = query.where(Invoice.id > uuid.UUID(cursor_data["last_id"]))

        rows = list((await session.execute(query.order_by(Invoice.id.asc()).limit(limit + 1))).all())
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = encode_cursor({"last_id": str(page_rows[-1][0].id)}) if has_more and page_rows else None

        invoice_ids = [invoice.id for invoice, _ in page_rows]
        taxes_by_invoice = group_by_document(await load_tax_lines(session, TAX_DOCUMENT, invoice_ids))
        line_rows = await session.execute(
            select(InvoiceLine).where(InvoiceLine.invoice_id.in_(invoice_ids)).order_by(InvoiceLine.line_no.asc())
        ) if invoice_ids else None
        lines_by_invoice: dict[uuid.UUID, list[InvoiceLine]] = {}
        for line in (line_rows.scalars().all() if line_rows is not None else []):
            lines_by_invoice.setdefault(line.invoice_id, []).append(line)

        return PageResponse(
            data=[
                format_invoice_response(invoice, client, lines_by_invoice.get(invoice.id, []), taxes_by_invoice.get(invoice.id, []))
                for invoice, client in page_rows
            ],
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
        if not client or client.organization_id != org_id:
            raise ClientNotFoundError(str(payload.client_id))
        if payload.contract_id:
            contract = await session.get(Contract, payload.contract_id)
            if not contract or contract.organization_id != org_id or contract.client_id != client.id:
                raise ContractNotFoundError(str(payload.contract_id))
            scheduled = await session.execute(
                select(BillingSchedule.id).where(BillingSchedule.context_id == contract.id).limit(1)
            )
            settings = await policies.load_settings(session, org_id)
            policies.require_schedule_line(settings, scheduled.first() is not None, schedule_line_given=False)

        offerings = await _offerings_for(session, org_id, (line.offering_id for line in payload.lines))
        return await create_draft(
            session, org_id, user_id, client, draft_lines_from_inputs(payload.lines, offerings),
            contract_id=payload.contract_id, due_date=payload.due_date, registration_id=payload.tax_registration_id,
        )

    @staticmethod
    async def get_invoice(session: AsyncSession, invoice_id: uuid.UUID, org_id: uuid.UUID) -> InvoiceResponse:
        invoice = await _invoice_in_org(session, org_id, invoice_id)
        client = await session.get(Client, invoice.client_id)
        tax_lines = await load_tax_lines(session, TAX_DOCUMENT, [invoice.id])
        deadlines = [
            DeadlineInfo(code=item.code, description=item.description, due_on=item.due_on, severity=item.severity)
            for item in await _deadlines(session, org_id, invoice)
        ]
        return format_invoice_response(invoice, client, await _lines_of(session, invoice.id), tax_lines, deadlines)

    @staticmethod
    async def issue_invoice(
        session: AsyncSession,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        if_match: Optional[str] = None,
        payload: Optional[InvoiceIssue] = None,
    ) -> InvoiceResponse:
        invoice = await _invoice_in_org(session, org_id, invoice_id)
        _check_version(if_match, invoice.version)
        if invoice.status == "issued":
            raise InvoiceAlreadyIssuedError(invoice.invoice_no or str(invoice_id))
        if invoice.status != "draft":
            raise InvalidStateTransitionError(invoice.status, "issue")

        client = await session.get(Client, invoice.client_id)
        issue_date = (payload.issue_date if payload else None) or date.today()
        stored_lines = await _lines_of(session, invoice.id)
        # Rates and rules as of the issue date, then frozen.
        calculation = await calculate_document(
            session, org_id, client, _specs_from_stored(stored_lines), issue_date, invoice.doc_type,
            invoice.currency, invoice.tax_registration_id,
        )
        _write_header(invoice, calculation, client, issue_date)
        _refresh_lines(stored_lines, calculation.result)
        await replace_tax_lines(session, org_id, TAX_DOCUMENT, invoice.id, calculation.result)

        invoice.invoice_no = await _issue_number(session, org_id, invoice.doc_type, issue_date, calculation.registration.id)
        invoice.status = "issued"
        invoice.issue_date = issue_date
        invoice.due_date = policies.due_date(calculation.settings, issue_date, invoice.due_date)
        invoice.issued_by = user_id
        invoice.client_snapshot = _client_snapshot(client)
        invoice.supplier_snapshot = registration_snapshot(calculation.registration)
        settlement.recompute(invoice)
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
        original = await _invoice_in_org(session, org_id, invoice_id)
        if original.doc_type != "tax_invoice" or original.status not in CREDITABLE_STATUSES:
            raise InvoiceNotIssuedError(original.status)
        client = await session.get(Client, original.client_id)
        today = date.today()

        settings = await policies.load_settings(session, org_id)
        deadlines = await _deadlines(session, org_id, original, "credit_note")
        policies.check_credit_note_deadline(settings, deadlines, today, payload.override_reason)

        if payload.lines:
            note = await _note_from_lines(session, org_id, user_id, client, original, payload.lines, "credit_note", today)
        else:
            note = await _full_reversal(session, org_id, user_id, original, today)

        if to_decimal(note.grand_total) > to_decimal(original.grand_total) - to_decimal(original.credited_amount):
            raise TaxConfigError(
                "CREDIT_EXCEEDS_INVOICE", "Credit notes can't add up to more than the invoice they correct."
            )
        note.note_reason, note.note_text = payload.reason, payload.note
        note.deadline_override_reason = payload.override_reason
        # Credit beyond what the customer still owed is owed back to them, shown as the note's balance.
        note.balance_due = settlement.apply_credit(original, to_decimal(note.grand_total))
        note.amount_settled = ZERO
        await session.flush()
        return await InvoiceService.get_invoice(session, note.id, org_id)

    @staticmethod
    async def issue_debit_note(
        session: AsyncSession,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: DebitNoteCreate,
    ) -> InvoiceResponse:
        original = await _invoice_in_org(session, org_id, invoice_id)
        if original.doc_type != "tax_invoice" or original.status not in CREDITABLE_STATUSES:
            raise InvoiceNotIssuedError(original.status)
        client = await session.get(Client, original.client_id)
        note = await _note_from_lines(session, org_id, user_id, client, original, payload.lines, "debit_note", date.today())
        note.note_reason, note.note_text = payload.reason, payload.note
        settings = await policies.load_settings(session, org_id)
        note.due_date = policies.due_date(settings, note.issue_date, None)
        settlement.recompute(note)
        await session.flush()
        return await InvoiceService.get_invoice(session, note.id, org_id)

    @staticmethod
    async def write_off(
        session: AsyncSession,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: WriteOffCreate,
        if_match: Optional[str],
    ) -> InvoiceResponse:
        invoice = await _invoice_in_org(session, org_id, invoice_id)
        _check_version(if_match, invoice.version)
        if invoice.doc_type not in ("tax_invoice", "debit_note") or invoice.status not in settlement.OPEN_STATUSES:
            raise InvoiceNotIssuedError(invoice.status)
        amount = to_decimal(payload.amount.amount)
        if amount <= ZERO or amount > to_decimal(invoice.balance_due):
            raise FinanceConflictError(
                "WRITE_OFF_EXCEEDS_BALANCE", f"Only the balance ({invoice.balance_due}) can be written off.",
            )
        session.add(InvoiceWriteOff(
            organization_id=org_id, invoice_id=invoice.id, amount=amount, reason=payload.reason,
            written_off_on=payload.written_off_on or date.today(), created_by=user_id,
        ))
        settlement.apply_write_off(invoice, amount)
        await session.flush()
        return await InvoiceService.get_invoice(session, invoice.id, org_id)

    @staticmethod
    async def get_invoice_pdf(session: AsyncSession, invoice_id: uuid.UUID, org_id: uuid.UUID) -> DownloadUrl:
        await _invoice_in_org(session, org_id, invoice_id)
        # PDFs are not generated or stored yet; never hand out a link to a file that does not exist.
        raise InvoicePdfNotAvailableError()


# ---------------------------------------------------------------- shared steps


async def create_draft(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    client: Client,
    drafted: list[DraftLine],
    contract_id: Optional[uuid.UUID] = None,
    due_date: Optional[date] = None,
    registration_id: Optional[uuid.UUID] = None,
    schedule_line_id: Optional[uuid.UUID] = None,
    currency: str = "INR",
) -> InvoiceResponse:
    """A draft tax invoice, taxed as of today (it is taxed again as of its issue date)."""
    today = date.today()
    calculation = await calculate_document(
        session, org_id, client, [draft.spec for draft in drafted], today, "tax_invoice", currency, registration_id
    )
    invoice = Invoice(
        organization_id=org_id, client_id=client.id, contract_id=contract_id, doc_type="tax_invoice", status="draft",
        due_date=policies.due_date(calculation.settings, today, due_date), currency=currency, amount_settled=ZERO,
        issued_by=user_id, schedule_line_id=schedule_line_id, version=1,
    )
    _write_header(invoice, calculation, client, today)
    invoice.balance_due = invoice.grand_total
    session.add(invoice)
    await session.flush()

    lines = _write_lines(invoice.id, calculation.result, drafted)
    session.add_all(lines)
    await replace_tax_lines(session, org_id, TAX_DOCUMENT, invoice.id, calculation.result)
    await session.flush()
    return format_invoice_response(invoice, client, lines, await load_tax_lines(session, TAX_DOCUMENT, [invoice.id]))


async def _note_from_lines(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    client: Client,
    original: Invoice,
    lines: List[InvoiceLineInput],
    doc_type: str,
    today: date,
) -> Invoice:
    """A credit or debit note for given lines, taxed exactly as the original was (its date, place, registration)."""
    offerings = await _offerings_for(session, org_id, (line.offering_id for line in lines))
    drafted = draft_lines_from_inputs(lines, offerings)
    tax_point = original.tax_point_date or original.issue_date or today
    calculation = await calculate_document(
        session, org_id, client, [draft.spec for draft in drafted], tax_point, doc_type, original.currency,
        original.tax_registration_id, original.place_of_supply if original.supply_type != "export" else None,
    )
    note = _new_note(original, doc_type, user_id, today)
    _write_header(note, calculation, client, tax_point)
    note.invoice_no = await _issue_number(session, org_id, doc_type, today, calculation.registration.id)
    session.add(note)
    await session.flush()
    session.add_all(_write_lines(note.id, calculation.result, drafted))
    await replace_tax_lines(session, org_id, TAX_DOCUMENT, note.id, calculation.result)
    await session.flush()
    return note


async def _full_reversal(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, original: Invoice, today: date) -> Invoice:
    """A credit note for the whole invoice: its lines and taxes copied, never recomputed."""
    original_lines = await _lines_of(session, original.id)
    remaining = to_decimal(original.grand_total) - to_decimal(original.credited_amount)
    if remaining < to_decimal(original.grand_total):
        raise FinanceConflictError(
            "INVOICE_PARTLY_CREDITED", "This invoice already has a credit note. Credit the rest line by line."
        )
    note = _new_note(original, "credit_note", user_id, today)
    for field in ("supplier_gstin", "recipient_gstin", "place_of_supply", "supply_type", "reverse_charge", "tax_point_date",
                  "config_revision", "tax_notes", "taxable_total", "cgst_total", "sgst_total", "igst_total", "round_off",
                  "grand_total", "tax_registration_id"):
        setattr(note, field, getattr(original, field))
    note.withholding, note.expected_withholding = [], ZERO
    note.invoice_no = await _issue_number(session, org_id, "credit_note", today, original.tax_registration_id)
    session.add(note)
    await session.flush()
    session.add_all([
        InvoiceLine(
            invoice_id=note.id, offering_id=line.offering_id, line_no=line.line_no,
            description=f"Credit adjustment: {line.description}", hsn_code=line.hsn_code, quantity=line.quantity,
            unit_price=line.unit_price, discount=line.discount, taxable_value=line.taxable_value,
            cgst_amount=line.cgst_amount, sgst_amount=line.sgst_amount, igst_amount=line.igst_amount,
            line_total=line.line_total, tax_category_code=line.tax_category_code, tax_rate=line.tax_rate,
        )
        for line in original_lines
    ])
    await copy_tax_lines(session, org_id, TAX_DOCUMENT, original.id, note.id)
    await session.flush()
    return note


def _new_note(original: Invoice, doc_type: str, user_id: uuid.UUID, today: date) -> Invoice:
    return Invoice(
        organization_id=original.organization_id, client_id=original.client_id, contract_id=original.contract_id,
        original_invoice_id=original.id, doc_type=doc_type, status="issued", issue_date=today, currency=original.currency,
        exchange_rate=original.exchange_rate, supplier_gstin=original.supplier_gstin, place_of_supply=original.place_of_supply,
        client_snapshot=original.client_snapshot, supplier_snapshot=original.supplier_snapshot, amount_settled=ZERO,
        balance_due=ZERO, issued_by=user_id, version=1,
    )


async def _deadlines(
    session: AsyncSession, org_id: uuid.UUID, invoice: Invoice, for_doc_type: Optional[str] = None
) -> list[Deadline]:
    """Deadlines that hang off an issued invoice (for its own type, or for a note raised against it)."""
    if invoice.status in ("draft", "pending_approval") or invoice.tax_registration_id is None:
        return []
    registration = await session.get(OrgTaxRegistration, invoice.tax_registration_id)
    if registration is None:
        return []
    snapshot = await load_snapshot(session, org_id, date.today())
    regime_entry = snapshot.find("regime", registration.regime_code)
    settings = await policies.load_settings(session, org_id)
    return deadlines_for(
        snapshot, registration.regime_code, for_doc_type or invoice.doc_type,
        {"issue_date": invoice.issue_date, "tax_point_date": invoice.tax_point_date},
        policies.fiscal_year_start(settings, regime_entry.data if regime_entry else None),  # type: ignore[arg-type]
    )
