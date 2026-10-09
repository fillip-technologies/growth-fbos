"""
Contract billing schedules (staged invoicing, docs/tax-and-finance-research.md §7.8).

Activating a contract builds its schedule from the payment terms (finance/billing/strategies.py),
per the organization's billing mode. Each line is invoiced on its own when it falls due (or its
milestone is reached), so GST is owed on what is billed now, not on the whole contract.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ContractNotFoundError, InvalidStateTransitionError
from finance import policies
from finance.billing.strategies import ContractFacts, TermFacts, plan_schedule
from finance.errors import FinanceConflictError, FinanceNotFoundError
from finance.money import ZERO, as_float, round_money, to_decimal
from models.billing import BillingSchedule, BillingScheduleLine
from models.client import Client
from models.contract import Contract, ContractPaymentTerm, ContractTerm
from models.offering import Offering
from models.quotation import Quotation, QuotationItem
from schemas.billing import BillingScheduleLineResponse, BillingScheduleLineUpdate, BillingScheduleResponse
from schemas.common import Money
from schemas.invoice import InvoiceResponse
from services.invoice_service import DraftLine, create_draft
from services.tax_service import DocumentLineSpec, legacy_rate
from services.versioning import check_version


def _billable(line: BillingScheduleLine, today: date) -> bool:
    if line.status == "ready":
        return True
    return line.status == "planned" and line.due_date is not None and line.due_date <= today


def _line_response(line: BillingScheduleLine, currency: str, today: date) -> BillingScheduleLineResponse:
    return BillingScheduleLineResponse(
        id=line.id, schedule_id=line.schedule_id, seq=line.seq, milestone_type=line.milestone_type,
        milestone_code=line.milestone_code, due_date=line.due_date,
        amount=Money(amount=as_float(to_decimal(line.amount)), currency=currency),
        percent=as_float(to_decimal(line.percent)) if line.percent is not None else None,
        description=line.description, status=line.status, billable=_billable(line, today), invoice_id=line.invoice_id,
        version=line.version,
    )


async def _schedule_response(session: AsyncSession, schedule: BillingSchedule) -> BillingScheduleResponse:
    rows = await session.execute(
        select(BillingScheduleLine).where(BillingScheduleLine.schedule_id == schedule.id).order_by(BillingScheduleLine.seq)
    )
    today = date.today()
    return BillingScheduleResponse(
        id=schedule.id, contract_id=schedule.context_id, client_id=schedule.client_id, currency=schedule.currency,
        status=schedule.status, basis_amount=Money(amount=as_float(to_decimal(schedule.basis_amount)), currency=schedule.currency),
        lines=[_line_response(line, schedule.currency, today) for line in rows.scalars().all()],
    )


async def _contract_items(session: AsyncSession, contract: Contract) -> list[tuple[str, Optional[uuid.UUID], Decimal, Optional[str]]]:
    """(description, offering, value before tax, tax category) per item: the accepted quotation's, else the contract terms'."""
    if contract.accepted_quotation_id:
        quoted = await session.execute(
            select(QuotationItem).where(QuotationItem.quotation_id == contract.accepted_quotation_id).order_by(QuotationItem.line_no)
        )
        items = list(quoted.scalars().all())
        if items:
            return [(item.description or "", item.offering_id, to_decimal(item.net_price), item.tax_category_code) for item in items]
    terms = await session.execute(select(ContractTerm).where(ContractTerm.contract_id == contract.id))
    return [
        (term.description or "", term.offering_id, to_decimal(term.quantity) * to_decimal(term.unit_price), None)
        for term in terms.scalars().all()
    ]


async def _basis_amount(session: AsyncSession, contract: Contract) -> Decimal:
    if contract.accepted_quotation_id:
        quote = await session.get(Quotation, contract.accepted_quotation_id)
        if quote is not None:
            return to_decimal(quote.subtotal) - to_decimal(quote.discount_total)
    return sum((value for _, _, value, _ in await _contract_items(session, contract)), ZERO)


async def build_schedule(session: AsyncSession, contract: Contract) -> Optional[BillingSchedule]:
    """Create the contract's schedule if the billing mode wants one and it has none yet."""
    settings = await policies.load_settings(session, contract.organization_id)
    if not policies.schedules_contracts(settings):
        return None
    existing = await session.execute(select(BillingSchedule).where(BillingSchedule.context_id == contract.id))
    if existing.scalars().first() is not None:
        return None

    basis = await _basis_amount(session, contract)
    term_rows = await session.execute(select(ContractPaymentTerm).where(ContractPaymentTerm.contract_id == contract.id))
    terms = [
        TermFacts(
            id=term.id, seq=term.seq, trigger_type=term.trigger_type, milestone_code=term.milestone_code,
            percent=to_decimal(term.percent) if term.percent is not None else None,
            amount=to_decimal(term.amount) if term.amount is not None else None,
            due_offset_days=term.due_offset_days, end_date=term.end_date, description=term.description,
        )
        for term in term_rows.scalars().all()
    ]
    planned = plan_schedule(
        ContractFacts(contract.start_date, contract.end_date, basis, contract.currency),
        terms,
        upfront=policies.bills_everything_upfront(settings),
    )
    schedule = BillingSchedule(
        organization_id=contract.organization_id, context_id=contract.id, client_id=contract.client_id,
        currency=contract.currency, status="active", basis_amount=basis,
    )
    session.add(schedule)
    await session.flush()
    session.add_all([
        BillingScheduleLine(
            schedule_id=schedule.id, seq=line.seq, milestone_type=line.milestone_type, milestone_code=line.milestone_code,
            due_date=line.due_date, amount=line.amount, percent=line.percent, description=line.description,
            payment_term_id=line.payment_term_id, status="planned",
        )
        for line in planned
    ])
    await session.flush()
    return schedule


class BillingScheduleService:
    @staticmethod
    async def list_schedules(
        session: AsyncSession, org_id: uuid.UUID, contract_id: Optional[uuid.UUID]
    ) -> list[BillingScheduleResponse]:
        query = select(BillingSchedule).where(BillingSchedule.organization_id == org_id)
        if contract_id is not None:
            query = query.where(BillingSchedule.context_id == contract_id)
        schedules = (await session.execute(query.order_by(BillingSchedule.id))).scalars().all()
        return [await _schedule_response(session, schedule) for schedule in schedules]

    @staticmethod
    async def _schedule(session: AsyncSession, org_id: uuid.UUID, schedule_id: uuid.UUID) -> BillingSchedule:
        schedule = await session.get(BillingSchedule, schedule_id)
        if schedule is None or schedule.organization_id != org_id:
            raise FinanceNotFoundError("BILLING_SCHEDULE_NOT_FOUND", f"Billing schedule '{schedule_id}' not found")
        return schedule

    @staticmethod
    async def get_schedule(session: AsyncSession, org_id: uuid.UUID, schedule_id: uuid.UUID) -> BillingScheduleResponse:
        return await _schedule_response(session, await BillingScheduleService._schedule(session, org_id, schedule_id))

    @staticmethod
    async def list_lines(
        session: AsyncSession,
        org_id: uuid.UUID,
        status: Optional[str],
        billable: Optional[bool],
        contract_id: Optional[uuid.UUID],
    ) -> list[BillingScheduleLineResponse]:
        query = (
            select(BillingScheduleLine, BillingSchedule.currency)
            .join(BillingSchedule, BillingSchedule.id == BillingScheduleLine.schedule_id)
            .where(BillingSchedule.organization_id == org_id)
        )
        if status is not None:
            query = query.where(BillingScheduleLine.status == status)
        if contract_id is not None:
            query = query.where(BillingSchedule.context_id == contract_id)
        rows = (await session.execute(query.order_by(BillingScheduleLine.due_date, BillingScheduleLine.seq))).all()
        today = date.today()
        responses = [_line_response(line, currency, today) for line, currency in rows]
        if billable is not None:
            responses = [line for line in responses if line.billable == billable]
        return responses

    @staticmethod
    async def _line(
        session: AsyncSession, org_id: uuid.UUID, schedule_id: uuid.UUID, line_id: uuid.UUID
    ) -> tuple[BillingSchedule, BillingScheduleLine]:
        schedule = await BillingScheduleService._schedule(session, org_id, schedule_id)
        line = await session.get(BillingScheduleLine, line_id)
        if line is None or line.schedule_id != schedule.id:
            raise FinanceNotFoundError("BILLING_SCHEDULE_LINE_NOT_FOUND", f"Schedule line '{line_id}' not found")
        return schedule, line

    @staticmethod
    async def update_line(
        session: AsyncSession,
        org_id: uuid.UUID,
        schedule_id: uuid.UUID,
        line_id: uuid.UUID,
        payload: BillingScheduleLineUpdate,
        if_match: Optional[str],
    ) -> BillingScheduleLineResponse:
        schedule, line = await BillingScheduleService._line(session, org_id, schedule_id, line_id)
        check_version(if_match, line.version)
        if line.status == "invoiced":
            raise InvalidStateTransitionError(line.status, payload.status)
        line.status = payload.status
        line.version += 1
        await session.flush()
        return _line_response(line, schedule.currency, date.today())

    @staticmethod
    async def bill_line(
        session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, schedule_id: uuid.UUID, line_id: uuid.UUID
    ) -> InvoiceResponse:
        """Draft the invoice for one schedule line: the contract's items, scaled to the line's amount."""
        schedule, line = await BillingScheduleService._line(session, org_id, schedule_id, line_id)
        if line.status in ("invoiced", "cancelled"):
            raise FinanceConflictError(
                "SCHEDULE_LINE_NOT_BILLABLE", f"This schedule line is {line.status}; it can't be billed again."
            )
        contract = await session.get(Contract, schedule.context_id)
        if contract is None or contract.organization_id != org_id:
            raise ContractNotFoundError(str(schedule.context_id))
        client = await session.get(Client, contract.client_id)

        drafted = await _draft_lines_for(session, org_id, contract, line, schedule.currency)
        term = await session.get(ContractPaymentTerm, line.payment_term_id) if line.payment_term_id else None
        due_date = date.today() + timedelta(days=term.due_offset_days) if term and term.due_offset_days is not None else None
        invoice = await create_draft(
            session, org_id, user_id, client, drafted, contract_id=contract.id, schedule_line_id=line.id,
            currency=schedule.currency, due_date=due_date,
        )
        line.invoice_id, line.status = invoice.id, "invoiced"
        line.version += 1
        await session.flush()
        return invoice


async def _draft_lines_for(
    session: AsyncSession, org_id: uuid.UUID, contract: Contract, line: BillingScheduleLine, currency: str
) -> list[DraftLine]:
    items = await _contract_items(session, contract)
    total = sum((value for _, _, value, _ in items), ZERO)
    amount = to_decimal(line.amount)
    offering_ids = {offering_id for _, offering_id, _, _ in items if offering_id}
    offerings = {
        offering.id: offering
        for offering in (await session.execute(
            select(Offering).where(Offering.id.in_(offering_ids), Offering.organization_id == org_id)
        )).scalars().all()
    } if offering_ids else {}

    label = line.description or line.milestone_type.replace("_", " ").title()
    if not items or total <= ZERO:
        return [DraftLine(description=label, offering_id=None, spec=DocumentLineSpec(line_no=1, quantity=Decimal(1), unit_price=amount))]

    drafted: list[DraftLine] = []
    billed = ZERO
    for position, (description, offering_id, value, category) in enumerate(items, start=1):
        is_last = position == len(items)
        portion = amount - billed if is_last else round_money(amount * value / total, currency)
        billed += portion
        offering = offerings.get(offering_id) if offering_id else None
        category = category or (offering.tax_category_code if offering else None)
        drafted.append(DraftLine(
            description=f"{label} — {description or (offering.name if offering else 'Contract item')}",
            offering_id=offering_id,
            spec=DocumentLineSpec(
                line_no=position, quantity=Decimal(1), unit_price=portion, category_code=category,
                legacy_rate=None if category else (legacy_rate(offering.gst_code) if offering else None),
                classification_code=offering.sac_code if offering else None,
            ),
        ))
    return drafted
