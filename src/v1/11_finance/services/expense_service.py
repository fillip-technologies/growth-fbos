"""
Operating expenses.

Approval: when the organization sets a threshold, an expense whose total (amount + tax) is above
it waits (`pending_approval`) for someone with `finance.expense.approve` who did not record it.
Changing what was approved (amount, tax, category, date) or editing a rejected expense sends it
through the same rule again. Only approved expenses count in totals.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ExpenseNotFoundError, ExpenseNotPendingError, SelfApprovalError, ValidationFailedError
from models.finance import Expense, ExpenseCategory
from schemas.common import PageMeta
from schemas.finance import CategoryRef, ExpenseCreate, ExpenseDecision, ExpenseResponse, ExpenseUpdate
from services import categories, settings_service
from services.identity_client import Actor
from services.pagination import paginate

PENDING, APPROVED, REJECTED = "pending_approval", "approved", "rejected"
# Changing any of these on an approved expense means what was approved no longer stands.
APPROVED_FIELDS = ("amount", "tax_amount", "category_id", "expense_date")
REQUIRED_FIELDS = ("category_id", "description", "expense_date", "amount", "tax_amount", "currency", "payment_status")


def total_of(expense: Expense) -> Decimal:
    return Decimal(expense.amount) + Decimal(expense.tax_amount or 0)


def needs_approval(total: Decimal, threshold: Optional[Decimal]) -> bool:
    return threshold is not None and total > Decimal(threshold)


def to_response(expense: Expense, category: ExpenseCategory) -> ExpenseResponse:
    return ExpenseResponse.model_validate(
        {
            **{column.key: getattr(expense, column.key) for column in Expense.__table__.columns},
            "category": CategoryRef.model_validate(category),
            "total": total_of(expense),
        }
    )


def _settle_payment(expense: Expense) -> None:
    """A paid expense has a payment date (the expense date unless given); an unpaid one has none."""
    if expense.payment_status == "paid":
        expense.paid_on = expense.paid_on or expense.expense_date
        return
    expense.paid_on = None
    expense.payment_reference = None


async def _apply_approval_rule(session: AsyncSession, expense: Expense) -> None:
    threshold = await settings_service.approval_threshold(session, expense.organization_id)
    expense.approval_status = PENDING if needs_approval(total_of(expense), threshold) else APPROVED
    expense.decided_by = None
    expense.decided_at = None
    expense.decision_comment = None


async def get_expense(session: AsyncSession, organization_id: uuid.UUID, expense_id: uuid.UUID) -> Expense:
    expense = await session.get(Expense, expense_id)
    if expense is None or expense.organization_id != organization_id:
        raise ExpenseNotFoundError()
    return expense


async def read_expense(session: AsyncSession, organization_id: uuid.UUID, expense_id: uuid.UUID) -> ExpenseResponse:
    expense = await get_expense(session, organization_id, expense_id)
    return to_response(expense, await categories.get_category(session, organization_id, expense.category_id))


async def create_expense(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, body: ExpenseCreate
) -> ExpenseResponse:
    category = await categories.usable_category(session, organization_id, body.category_id)
    values = body.model_dump()
    values["currency"] = body.currency or await settings_service.default_currency(session, organization_id)
    expense = Expense(organization_id=organization_id, created_by=user_id, **values)
    _settle_payment(expense)
    await _apply_approval_rule(session, expense)
    session.add(expense)
    await session.commit()
    await session.refresh(expense)
    return to_response(expense, category)


async def update_expense(
    session: AsyncSession, organization_id: uuid.UUID, expense_id: uuid.UUID, body: ExpenseUpdate
) -> ExpenseResponse:
    expense = await get_expense(session, organization_id, expense_id)
    changes = body.model_dump(exclude_unset=True)
    for field in REQUIRED_FIELDS:
        if field in changes and changes[field] is None:
            raise ValidationFailedError(field, "cannot be empty")
    if "category_id" in changes and changes["category_id"] != expense.category_id:
        await categories.usable_category(session, organization_id, changes["category_id"])

    approved_terms_changed = any(
        field in changes and changes[field] != getattr(expense, field) for field in APPROVED_FIELDS
    )
    for field, value in changes.items():
        setattr(expense, field, value)
    _settle_payment(expense)
    if approved_terms_changed or expense.approval_status == REJECTED:
        await _apply_approval_rule(session, expense)

    await session.commit()
    await session.refresh(expense)
    return to_response(expense, await categories.get_category(session, organization_id, expense.category_id))


async def decide_expense(
    session: AsyncSession, actor: Actor, expense_id: uuid.UUID, body: ExpenseDecision
) -> ExpenseResponse:
    expense = await get_expense(session, actor.organization_id, expense_id)
    if expense.approval_status != PENDING:
        raise ExpenseNotPendingError(expense.approval_status)
    if expense.created_by == actor.user_id and not actor.is_superuser:
        raise SelfApprovalError()
    expense.approval_status = APPROVED if body.decision == "approve" else REJECTED
    expense.decided_by = actor.user_id
    expense.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    expense.decision_comment = body.comment
    await session.commit()
    await session.refresh(expense)
    return to_response(expense, await categories.get_category(session, actor.organization_id, expense.category_id))


async def delete_expense(session: AsyncSession, organization_id: uuid.UUID, expense_id: uuid.UUID) -> None:
    expense = await get_expense(session, organization_id, expense_id)
    await session.delete(expense)
    await session.commit()


async def list_expenses(
    session: AsyncSession,
    organization_id: uuid.UUID,
    *,
    limit: int,
    cursor: Optional[str],
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    category_id: Optional[uuid.UUID] = None,
    approval_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    work_unit_id: Optional[uuid.UUID] = None,
    org_unit_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
) -> tuple[list[ExpenseResponse], PageMeta]:
    """Newest expense date first."""
    query = select(Expense).where(Expense.organization_id == organization_id)
    filters = {
        Expense.category_id: category_id,
        Expense.approval_status: approval_status,
        Expense.payment_status: payment_status,
        Expense.work_unit_id: work_unit_id,
        Expense.org_unit_id: org_unit_id,
    }
    for column, value in filters.items():
        if value is not None:
            query = query.where(column == value)
    if from_date:
        query = query.where(Expense.expense_date >= from_date)
    if to_date:
        query = query.where(Expense.expense_date <= to_date)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(Expense.description.ilike(pattern) | Expense.vendor_name.ilike(pattern))

    rows, page = await paginate(session, query, Expense, limit, cursor, order_by=Expense.expense_date, descending=True)
    by_id = {c.id: c for c in await categories.list_categories(session, organization_id, active_only=False)}
    return [to_response(row, by_id[row.category_id]) for row in rows], page
