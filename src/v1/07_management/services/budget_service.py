"""
Budgets: a fiscal year's plan for a unit or vertical, its lines, the appropriation of lines to
initiatives, the actuals posted against them, and budget vs actual vs committed.

- Lines are edited while the budget is a draft. Submitting raises one of control's approval
  requests (subject `management.budget`); approval copies each line's planned amount into its
  approved amount. Revising an approved budget reopens it as a draft with the next revision number;
  the last approved amounts stay until the revision is approved.
- Allocations to initiatives come out of a line's approved amount and can't exceed it.
- Actuals are a mirror of the service that owns the money, idempotent on `source_event_id`;
  management is not the ledger of record. Hand-entered actuals are marked `manual`.
- Committed money is labour promised but not yet spent: confirmed bookings from `as_of` on an
  initiative a line funds, priced at the resources' cost rates and split between the lines funding
  that initiative in proportion to their allocations.
"""

from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    BudgetExceededError,
    BudgetLineNotFoundError,
    BudgetNotFoundError,
    DuplicateBudgetCodeError,
    FiscalYearNotFoundError,
    InvalidStateTransitionError,
    UnknownReferenceError,
    ValidationFailedError,
)
from models.planning import Budget, BudgetActual, BudgetAllocation, BudgetLine, FiscalYear, Initiative
from models.resource import Allocation, CapacityLedger, Resource
from schemas.budget import (
    BudgetActualCreate,
    BudgetActualResponse,
    BudgetCategoryRow,
    BudgetMonth,
    BudgetSummaryResponse,
    BudgetSummaryRow,
    BudgetAllocationCreate,
    BudgetAllocationResponse,
    BudgetCreate,
    BudgetLineCreate,
    BudgetLineResponse,
    BudgetLineUpdate,
    BudgetResponse,
    BudgetScope,
    BudgetTarget,
    BudgetTotals,
    BudgetUpdate,
    FiscalYearRef,
    InternalBudgetActualCreate,
    VarianceLine,
    VarianceResponse,
)
from schemas.common import PageResponse
from services.common import get_in_org
from services.control_client import ControlClient
from services.identity_client import Actor
from services.pagination import paginate_by_id

SUBJECT_TYPE = "management.budget"
REQUEST_TYPE = "budget"
INITIATIVE_SUBJECT = "initiative"  # allocations (resource bookings) against an initiative use this subject type
_AFTER_DECISION = {
    "approved": "approved",
    "rejected": "rejected",
    "revision_required": "draft",
    "cancelled": "draft",
    "expired": "draft",
}
ZERO = Decimal(0)


# --- Responses ----------------------------------------------------------------


async def _line_sums(session: AsyncSession, line_ids: list[uuid.UUID]) -> tuple[dict, dict]:
    if not line_ids:
        return {}, {}
    actual = dict(
        (await session.execute(
            select(BudgetActual.budget_line_id, func.sum(BudgetActual.amount))
            .where(BudgetActual.budget_line_id.in_(line_ids)).group_by(BudgetActual.budget_line_id)
        )).all()
    )
    allocated = dict(
        (await session.execute(
            select(BudgetAllocation.budget_line_id, func.sum(BudgetAllocation.amount))
            .where(BudgetAllocation.budget_line_id.in_(line_ids)).group_by(BudgetAllocation.budget_line_id)
        )).all()
    )
    return actual, allocated


async def _lines(session: AsyncSession, budget_id: uuid.UUID) -> list[BudgetLine]:
    return list(
        (await session.execute(
            select(BudgetLine).where(BudgetLine.budget_id == budget_id).order_by(BudgetLine.category, BudgetLine.id)
        )).scalars().all()
    )


async def _budget_response(session: AsyncSession, budget: Budget) -> BudgetResponse:
    year = await session.get(FiscalYear, budget.fiscal_year_id)
    lines = await _lines(session, budget.id)
    actual, allocated = await _line_sums(session, [line.id for line in lines])
    line_items = [
        BudgetLineResponse(
            id=line.id, category=line.category, description=line.description,
            planned_amount=float(line.planned_amount), approved_amount=float(line.approved_amount),
            allocated_amount=float(allocated.get(line.id) or 0), actual_amount=float(actual.get(line.id) or 0),
        )
        for line in lines
    ]
    return BudgetResponse(
        id=budget.id, code=budget.code, name=budget.name, fiscal_year=FiscalYearRef(id=year.id, code=year.code),
        scope=BudgetScope(unit_id=budget.scope_unit_id, vertical_id=budget.scope_vertical_id),
        currency=budget.currency, revision_no=budget.revision_no, status=budget.status,
        approval_request_id=budget.approval_request_id, lines=line_items,
        totals=BudgetTotals(
            planned=round(sum(i.planned_amount for i in line_items), 2),
            approved=round(sum(i.approved_amount for i in line_items), 2),
            actual=round(sum(i.actual_amount for i in line_items), 2),
        ),
    )


def _actual_response(actual: BudgetActual) -> BudgetActualResponse:
    return BudgetActualResponse(
        id=actual.id, budget_line_id=actual.budget_line_id, amount=float(actual.amount),
        occurred_on=actual.occurred_on, source_type=actual.source_type, source_event_id=actual.source_event_id,
    )


# --- Lookups ------------------------------------------------------------------


async def get_budget(session: AsyncSession, org_id: uuid.UUID, budget_id: uuid.UUID) -> Budget:
    return await get_in_org(session, Budget, budget_id, org_id, BudgetNotFoundError(str(budget_id)))


async def _get_line(session: AsyncSession, org_id: uuid.UUID, line_id: uuid.UUID) -> tuple[BudgetLine, Budget]:
    line = await session.get(BudgetLine, line_id)
    budget = await session.get(Budget, line.budget_id) if line else None
    if line is None or budget is None or budget.organization_id != org_id:
        raise BudgetLineNotFoundError(str(line_id))
    return line, budget


def _require_draft(budget: Budget, action: str) -> None:
    if budget.status != "draft":
        raise InvalidStateTransitionError("budget", budget.status, action)


# --- Budgets and lines --------------------------------------------------------


async def list_budgets(
    session: AsyncSession, org_id: uuid.UUID, fiscal_year_id: Optional[uuid.UUID], status: Optional[str],
    limit: int, cursor: Optional[str],
) -> PageResponse[BudgetResponse]:
    query = select(Budget).where(Budget.organization_id == org_id)
    if fiscal_year_id is not None:
        query = query.where(Budget.fiscal_year_id == fiscal_year_id)
    if status is not None:
        query = query.where(Budget.status == status)
    rows, page = await paginate_by_id(session, query, Budget, limit, cursor)
    return PageResponse(data=[await _budget_response(session, row) for row in rows], page=page)


async def create_budget(session: AsyncSession, org_id: uuid.UUID, data: BudgetCreate) -> BudgetResponse:
    year = await session.get(FiscalYear, data.fiscal_year_id)
    if year is None or year.organization_id != org_id:
        raise UnknownReferenceError("FISCAL_YEAR_NOT_FOUND", "fiscal_year_id", "Fiscal year not found.")
    if year.status == "closed":
        raise InvalidStateTransitionError("fiscal year", year.status, "budget for")
    exists = await session.execute(select(Budget.id).where(Budget.organization_id == org_id, Budget.code == data.code))
    if exists.first():
        raise DuplicateBudgetCodeError(data.code)
    budget = Budget(
        organization_id=org_id, fiscal_year_id=year.id, code=data.code, name=data.name, currency=data.currency,
        scope_unit_id=data.scope.unit_id, scope_vertical_id=data.scope.vertical_id, revision_no=1, status="draft",
    )
    session.add(budget)
    await session.flush()
    return await _budget_response(session, budget)


async def _apply_decision(session: AsyncSession, budget: Budget, control_status: str) -> None:
    new_status = _AFTER_DECISION.get(control_status)
    if new_status is None or budget.status != "pending_approval":
        return
    budget.status = new_status
    if new_status == "draft":
        budget.approval_request_id = None
    if new_status == "approved":
        for line in await _lines(session, budget.id):
            line.approved_amount = line.planned_amount
    await session.flush()


async def get_budget_response(
    session: AsyncSession, actor: Actor, control: ControlClient, budget_id: uuid.UUID
) -> BudgetResponse:
    """The budget; one waiting on control picks up control's decision when the caller may see it."""
    budget = await get_budget(session, actor.organization_id, budget_id)
    if budget.status == "pending_approval" and budget.approval_request_id is not None:
        state = await control.request_state(actor, budget.approval_request_id)
        if state is not None:
            await _apply_decision(session, budget, state.status)
    return await _budget_response(session, budget)


async def update_budget(session: AsyncSession, org_id: uuid.UUID, budget_id: uuid.UUID, data: BudgetUpdate) -> BudgetResponse:
    budget = await get_budget(session, org_id, budget_id)
    _require_draft(budget, "change")
    changes = data.model_dump(exclude_unset=True)
    scope = changes.pop("scope", None)
    if scope is not None:
        budget.scope_unit_id, budget.scope_vertical_id = scope.get("unit_id"), scope.get("vertical_id")
    for field_name, value in changes.items():
        setattr(budget, field_name, value)
    await session.flush()
    return await _budget_response(session, budget)


async def add_line(session: AsyncSession, org_id: uuid.UUID, budget_id: uuid.UUID, data: BudgetLineCreate) -> BudgetResponse:
    budget = await get_budget(session, org_id, budget_id)
    _require_draft(budget, "add a line to")
    session.add(BudgetLine(budget_id=budget.id, approved_amount=0, **data.model_dump()))
    await session.flush()
    return await _budget_response(session, budget)


async def update_line(session: AsyncSession, org_id: uuid.UUID, line_id: uuid.UUID, data: BudgetLineUpdate) -> BudgetResponse:
    line, budget = await _get_line(session, org_id, line_id)
    _require_draft(budget, "change a line of")
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(line, field_name, value)
    await session.flush()
    return await _budget_response(session, budget)


async def delete_line(session: AsyncSession, org_id: uuid.UUID, line_id: uuid.UUID) -> None:
    line, budget = await _get_line(session, org_id, line_id)
    _require_draft(budget, "remove a line from")
    has_money = await session.execute(
        select(BudgetActual.id).where(BudgetActual.budget_line_id == line.id).limit(1)
    )
    if has_money.first() or await _allocated_on(session, line.id) > 0:
        raise InvalidStateTransitionError("budget line", "in use", "remove")
    await session.delete(line)
    await session.flush()


async def submit_budget(
    session: AsyncSession, actor: Actor, control: ControlClient, budget_id: uuid.UUID
) -> BudgetResponse:
    budget = await get_budget(session, actor.organization_id, budget_id)
    _require_draft(budget, "submit")
    response = await _budget_response(session, budget)
    if not response.lines:
        raise ValidationFailedError("lines", "a budget needs at least one line before it is submitted")
    state = await control.raise_request(
        actor,
        subject_type=SUBJECT_TYPE,
        subject_id=budget.id,
        subject_version=str(budget.revision_no),
        request_type=REQUEST_TYPE,
        title=f"Budget {budget.code} (revision {budget.revision_no}): {response.totals.planned:,.2f} {budget.currency}",
        context={
            "code": budget.code,
            "fiscal_year": response.fiscal_year.code,
            "currency": budget.currency,
            "revision_no": budget.revision_no,
            "total_planned": response.totals.planned,
            "lines": [{"category": line.category, "planned_amount": line.planned_amount} for line in response.lines],
        },
    )
    budget.status = "pending_approval"
    budget.approval_request_id = state.id
    await session.flush()
    await _apply_decision(session, budget, state.status)
    return await _budget_response(session, budget)


async def revise_budget(session: AsyncSession, org_id: uuid.UUID, budget_id: uuid.UUID) -> BudgetResponse:
    budget = await get_budget(session, org_id, budget_id)
    if budget.status not in ("approved", "rejected"):
        raise InvalidStateTransitionError("budget", budget.status, "revise")
    budget.status = "draft"
    budget.revision_no += 1
    budget.approval_request_id = None
    await session.flush()
    return await _budget_response(session, budget)


# --- Allocations and actuals --------------------------------------------------


async def _allocated_on(session: AsyncSession, line_id: uuid.UUID) -> Decimal:
    total = (
        await session.execute(select(func.sum(BudgetAllocation.amount)).where(BudgetAllocation.budget_line_id == line_id))
    ).scalar_one_or_none()
    return Decimal(total or 0)


async def list_line_allocations(session: AsyncSession, org_id: uuid.UUID, line_id: uuid.UUID) -> list[BudgetAllocationResponse]:
    line, _ = await _get_line(session, org_id, line_id)
    rows = (await session.execute(select(BudgetAllocation).where(BudgetAllocation.budget_line_id == line.id))).scalars().all()
    return [
        BudgetAllocationResponse(id=row.id, budget_line_id=row.budget_line_id, target=BudgetTarget(type=row.target_type, id=row.target_id), amount=float(row.amount))
        for row in rows
    ]


async def allocate(
    session: AsyncSession, org_id: uuid.UUID, line_id: uuid.UUID, data: BudgetAllocationCreate
) -> BudgetAllocationResponse:
    line, budget = await _get_line(session, org_id, line_id)
    if budget.status != "approved":
        raise InvalidStateTransitionError("budget", budget.status, "allocate from")
    initiative = await session.get(Initiative, data.target.id)
    if initiative is None or initiative.organization_id != org_id:
        raise UnknownReferenceError("INITIATIVE_NOT_FOUND", "target.id", "Initiative not found.")
    left = Decimal(line.approved_amount) - await _allocated_on(session, line.id)
    requested = Decimal(str(data.amount))
    if requested > left:
        raise BudgetExceededError(str(line.id), float(left), data.amount)
    allocation = BudgetAllocation(budget_line_id=line.id, target_type=data.target.type, target_id=initiative.id, amount=requested)
    session.add(allocation)
    await session.flush()
    return BudgetAllocationResponse(id=allocation.id, budget_line_id=line.id, target=data.target, amount=float(requested))


async def _check_in_year(session: AsyncSession, budget: Budget, occurred_on: date) -> None:
    year = await session.get(FiscalYear, budget.fiscal_year_id)
    if not year.start_date <= occurred_on <= year.end_date:
        raise ValidationFailedError("occurred_on", f"must fall inside fiscal year {year.code}")


async def list_actuals(session: AsyncSession, org_id: uuid.UUID, line_id: uuid.UUID) -> list[BudgetActualResponse]:
    line, _ = await _get_line(session, org_id, line_id)
    rows = (
        await session.execute(
            select(BudgetActual).where(BudgetActual.budget_line_id == line.id).order_by(BudgetActual.occurred_on, BudgetActual.id)
        )
    ).scalars().all()
    return [_actual_response(row) for row in rows]


async def record_actual(session: AsyncSession, org_id: uuid.UUID, line_id: uuid.UUID, data: BudgetActualCreate) -> BudgetActualResponse:
    line, budget = await _get_line(session, org_id, line_id)
    await _check_in_year(session, budget, data.occurred_on)
    actual = BudgetActual(budget_line_id=line.id, amount=data.amount, occurred_on=data.occurred_on, source_type="manual")
    session.add(actual)
    await session.flush()
    return _actual_response(actual)


async def mirror_actual(session: AsyncSession, data: InternalBudgetActualCreate) -> tuple[BudgetActualResponse, bool]:
    """An actual from another service: the same `source_event_id` posted twice is one actual. Returns (actual, created)."""
    if data.budget_line_id is not None:
        line, budget = await _get_line(session, data.organization_id, data.budget_line_id)
    else:
        row = (
            await session.execute(
                select(BudgetLine, Budget).join(Budget, Budget.id == BudgetLine.budget_id).where(
                    Budget.organization_id == data.organization_id, Budget.code == data.budget_code,
                    BudgetLine.category == data.category,
                ).limit(1)
            )
        ).first()
        if row is None:
            raise BudgetLineNotFoundError(f"{data.budget_code}/{data.category}")
        line, budget = row
    existing = (
        await session.execute(
            select(BudgetActual).where(
                BudgetActual.budget_line_id == line.id, BudgetActual.source_event_id == data.source_event_id
            )
        )
    ).scalars().first()
    if existing is not None:
        return _actual_response(existing), False
    await _check_in_year(session, budget, data.occurred_on)
    actual = BudgetActual(
        budget_line_id=line.id, amount=data.amount, occurred_on=data.occurred_on, source_type=data.source_type,
        source_event_id=data.source_event_id,
    )
    session.add(actual)
    await session.flush()
    return _actual_response(actual), True


# --- Variance -----------------------------------------------------------------


async def _initiative_commitments(
    session: AsyncSession, org_id: uuid.UUID, initiative_ids: set[uuid.UUID], as_of: date
) -> tuple[dict[uuid.UUID, Decimal], int]:
    """Labour still to be spent on each initiative from `as_of`, at cost rates; and how many bookings had no rate."""
    commitments: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    unpriced = 0
    if not initiative_ids:
        return commitments, unpriced
    bookings = (
        await session.execute(
            select(Allocation, Resource).join(Resource, Resource.id == Allocation.resource_id).where(
                Allocation.organization_id == org_id, Allocation.status == "confirmed",
                Allocation.subject_type == INITIATIVE_SUBJECT, Allocation.subject_id.in_(initiative_ids),
                Allocation.end_date >= as_of,
            )
        )
    ).all()
    for booking, resource in bookings:
        if resource.internal_cost_rate is None:
            unpriced += 1
            continue
        # The booking counts on the days the ledger shows it booked (working days).
        days = (
            await session.execute(
                select(func.count()).select_from(CapacityLedger).where(
                    CapacityLedger.resource_id == resource.id, CapacityLedger.allocated_minutes > 0,
                    CapacityLedger.day >= max(as_of, booking.start_date), CapacityLedger.day <= booking.end_date,
                )
            )
        ).scalar_one()
        commitments[booking.subject_id] += Decimal(booking.minutes_per_day * days) / 60 * Decimal(resource.internal_cost_rate)
    return commitments, unpriced


async def _last_year_actuals(session: AsyncSession, budget: Budget) -> Optional[dict[str, Decimal]]:
    year = await session.get(FiscalYear, budget.fiscal_year_id)
    previous_year = (
        await session.execute(
            select(FiscalYear).where(FiscalYear.organization_id == budget.organization_id, FiscalYear.end_date < year.start_date)
            .order_by(FiscalYear.end_date.desc()).limit(1)
        )
    ).scalars().first()
    if previous_year is None:
        return None
    same_scope = [
        Budget.scope_unit_id == budget.scope_unit_id if budget.scope_unit_id else Budget.scope_unit_id.is_(None),
        Budget.scope_vertical_id == budget.scope_vertical_id if budget.scope_vertical_id else Budget.scope_vertical_id.is_(None),
    ]
    rows = (
        await session.execute(
            select(BudgetLine.category, func.sum(BudgetActual.amount))
            .join(Budget, Budget.id == BudgetLine.budget_id)
            .join(BudgetActual, BudgetActual.budget_line_id == BudgetLine.id)
            .where(Budget.fiscal_year_id == previous_year.id, *same_scope)
            .group_by(BudgetLine.category)
        )
    ).all()
    return {category: Decimal(total or 0) for category, total in rows}


def _variance_line(line_id: uuid.UUID, category: str, planned: Decimal, approved: Decimal, actual: Decimal,
                   committed: Decimal, last_year: Optional[Decimal]) -> VarianceLine:
    variance = actual - approved
    return VarianceLine(
        budget_line_id=line_id, category=category, planned=float(round(planned, 2)), approved=float(round(approved, 2)),
        actual=float(round(actual, 2)), committed=float(round(committed, 2)),
        available=float(round(approved - actual - committed, 2)), variance_abs=float(round(variance, 2)),
        variance_pct=float(round(variance / approved * 100, 2)) if approved > 0 else None,
        last_year_actual=float(round(last_year, 2)) if last_year is not None else None,
    )


async def variance(session: AsyncSession, org_id: uuid.UUID, budget_id: uuid.UUID, as_of: date) -> VarianceResponse:
    """Budget vs actual (accountability), vs committed (what is already promised) and vs last year (the trend)."""
    budget = await get_budget(session, org_id, budget_id)
    lines = await _lines(session, budget.id)
    line_ids = [line.id for line in lines]
    actual_sums, _ = await _line_sums(session, line_ids)

    funding = (
        await session.execute(select(BudgetAllocation).where(BudgetAllocation.budget_line_id.in_(line_ids)))
    ).scalars().all() if line_ids else []
    funded_total: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for row in funding:
        funded_total[row.target_id] += Decimal(row.amount)
    commitments, unpriced = await _initiative_commitments(session, org_id, set(funded_total), as_of)
    committed: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for row in funding:
        if funded_total[row.target_id] > 0:
            committed[row.budget_line_id] += commitments.get(row.target_id, ZERO) * Decimal(row.amount) / funded_total[row.target_id]

    last_year = await _last_year_actuals(session, budget)
    items = [
        _variance_line(
            line.id, line.category, Decimal(line.planned_amount), Decimal(line.approved_amount),
            Decimal(actual_sums.get(line.id) or 0), committed.get(line.id, ZERO),
            last_year.get(line.category, ZERO) if last_year is not None else None,
        )
        for line in lines
    ]
    totals = _variance_line(
        uuid.UUID(int=0), "total",
        sum((Decimal(str(i.planned)) for i in items), ZERO), sum((Decimal(str(i.approved)) for i in items), ZERO),
        sum((Decimal(str(i.actual)) for i in items), ZERO), sum((Decimal(str(i.committed)) for i in items), ZERO),
        sum(last_year.values(), ZERO) if last_year is not None else None,
    )
    return VarianceResponse(
        budget_id=budget.id, currency=budget.currency, as_of=as_of, unpriced_bookings=unpriced, lines=items, totals=totals
    )


# --- Summary --------------------------------------------------------------------


async def budget_summary(
    session: AsyncSession, org_id: uuid.UUID, fiscal_year_id: Optional[uuid.UUID], today: Optional[date] = None
) -> BudgetSummaryResponse:
    """Planned, approved and spent per budget, per category and per month of one fiscal year: the given
    one, else the one today falls in, else the latest. Rejected budgets count nothing approved."""
    year = await _summary_year(session, org_id, fiscal_year_id, today or date.today())
    budgets = (
        await session.execute(select(Budget).where(Budget.organization_id == org_id, Budget.fiscal_year_id == year.id))
    ).scalars().all()
    by_id = {b.id: b for b in budgets}
    line_rows = (
        await session.execute(
            select(BudgetLine.id, BudgetLine.budget_id, BudgetLine.category, BudgetLine.planned_amount, BudgetLine.approved_amount)
            .where(BudgetLine.budget_id.in_(list(by_id)))
        )
    ).all() if by_id else []
    actual_by_line, _ = await _line_sums(session, [row.id for row in line_rows])

    per_budget: dict[uuid.UUID, list[Decimal]] = {b.id: [ZERO, ZERO, ZERO] for b in budgets}
    per_category: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO])
    for line_id, budget_id, category, planned, approved in line_rows:
        approved_counts = by_id[budget_id].status != "rejected"
        values = (Decimal(planned or 0), Decimal(approved or 0) if approved_counts else ZERO, Decimal(actual_by_line.get(line_id) or 0))
        for bucket in (per_budget[budget_id], per_category[category]):
            for i, value in enumerate(values):
                bucket[i] += value

    month_rows = (
        await session.execute(
            select(BudgetActual.occurred_on, func.sum(BudgetActual.amount))
            .where(BudgetActual.budget_line_id.in_([row.id for row in line_rows]))
            .group_by(BudgetActual.occurred_on)
        )
    ).all() if line_rows else []
    months: dict[str, Decimal] = {}
    cursor = date(year.start_date.year, year.start_date.month, 1)
    while cursor <= year.end_date:
        months[f"{cursor.year:04d}-{cursor.month:02d}"] = ZERO
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    for day, amount in month_rows:
        key = f"{day.year:04d}-{day.month:02d}"
        if key in months:
            months[key] += Decimal(amount or 0)

    currencies = Counter(b.currency for b in budgets)
    currency = currencies.most_common(1)[0][0] if currencies else "INR"
    rows = sorted(
        (
            BudgetSummaryRow(
                budget_id=b.id, code=b.code, name=b.name, status=b.status, scope_unit_id=b.scope_unit_id,
                scope_vertical_id=b.scope_vertical_id, currency=b.currency,
                planned=float(per_budget[b.id][0]), approved=float(per_budget[b.id][1]), actual=float(per_budget[b.id][2]),
            )
            for b in budgets
        ),
        key=lambda r: (-r.actual, -r.approved, r.name),
    )
    return BudgetSummaryResponse(
        fiscal_year_id=year.id, fiscal_year_code=year.code, start_date=year.start_date, end_date=year.end_date,
        currency=currency, mixed_currencies=len(currencies) > 1,
        planned=sum(r.planned for r in rows), approved=sum(r.approved for r in rows), actual=sum(r.actual for r in rows),
        budgets=rows,
        by_category=sorted(
            (BudgetCategoryRow(category=c, planned=float(p), approved=float(a), actual=float(s)) for c, (p, a, s) in per_category.items()),
            key=lambda r: (-r.actual, -r.approved, r.category),
        ),
        actual_by_month=[BudgetMonth(month=k, actual=float(v)) for k, v in months.items()],
    )


async def _summary_year(session: AsyncSession, org_id: uuid.UUID, fiscal_year_id: Optional[uuid.UUID], today: date) -> FiscalYear:
    if fiscal_year_id is not None:
        year = await session.get(FiscalYear, fiscal_year_id)
        if year is None or year.organization_id != org_id:
            raise FiscalYearNotFoundError(fiscal_year_id)
        return year
    years = (
        await session.execute(select(FiscalYear).where(FiscalYear.organization_id == org_id).order_by(FiscalYear.start_date.desc()))
    ).scalars().all()
    current = next((y for y in years if y.start_date <= today <= y.end_date), None)
    if current is None and not years:
        raise FiscalYearNotFoundError(None)
    return current or years[0]
