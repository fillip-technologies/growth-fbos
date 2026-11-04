"""Projects and their costs for one organization over a period (the CEO Command Center).

Running and at-risk follow the project stats (services/stats.py) so the two screens agree.
Cost entries have no organization of their own; they belong to it through their work unit.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.financial import CostEntry
from models.work_unit import WorkUnit
from schemas.business_summary import CategoryCost, DeliveryBusinessSummary, PartnerWork, Period, ProjectCounts
from services.stats import RUNNING_PROJECT_STATUSES

DEFAULT_CURRENCY = "INR"
AT_RISK_HEALTH = ("red", "amber")
# What the client pays an associate for work is recorded as cost entries of this category.
SUBCONTRACT_CATEGORY = "subcontract"


def previous_period(from_date: date, to_date: date) -> tuple[date, date]:
    """The same number of days immediately before the period."""
    days = (to_date - from_date).days + 1
    return from_date - timedelta(days=days), from_date - timedelta(days=1)


async def delivery_summary(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date, today: Optional[date] = None
) -> DeliveryBusinessSummary:
    today = today or date.today()
    previous_from, previous_to = previous_period(from_date, to_date)
    currency, mixed = await _main_currency(session, org_id)
    by_category = await _costs_by_category(session, org_id, from_date, to_date)
    previous_by_category = await _costs_by_category(session, org_id, previous_from, previous_to)
    return DeliveryBusinessSummary(
        currency=currency,
        mixed_currencies=mixed,
        period=Period(from_date=from_date, to_date=to_date),
        previous_period=Period(from_date=previous_from, to_date=previous_to),
        projects=await _project_counts(session, org_id, today),
        costs=_round(sum(by_category.values(), Decimal(0))),
        costs_previous=_round(sum(previous_by_category.values(), Decimal(0))),
        costs_by_category=[
            CategoryCost(category=category, amount=_round(amount))
            for category, amount in sorted(by_category.items(), key=lambda item: -item[1])
        ],
        partners=await _partners(session, org_id, from_date, to_date),
    )


def _round(amount: Decimal) -> float:
    return round(float(amount), 2)


async def _project_counts(session: AsyncSession, org_id: uuid.UUID, today: date) -> ProjectCounts:
    late = and_(WorkUnit.planned_end.is_not(None), WorkUnit.planned_end < today)
    running, at_risk, late_count = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(case((or_(WorkUnit.health.in_(AT_RISK_HEALTH), late), 1), else_=0)), 0),
                func.coalesce(func.sum(case((late, 1), else_=0)), 0),
            ).where(WorkUnit.organization_id == org_id, WorkUnit.status.in_(RUNNING_PROJECT_STATUSES))
        )
    ).one()
    return ProjectCounts(running=int(running), at_risk=int(at_risk), late=int(late_count))


async def _costs_by_category(
    session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date
) -> dict[str, Decimal]:
    rows = (
        await session.execute(
            select(CostEntry.category, func.coalesce(func.sum(CostEntry.amount), 0))
            .join(WorkUnit, WorkUnit.id == CostEntry.work_unit_id)
            .where(
                WorkUnit.organization_id == org_id,
                CostEntry.occurred_on >= from_date,
                CostEntry.occurred_on <= to_date,
            )
            .group_by(CostEntry.category)
        )
    ).all()
    return {category: Decimal(str(amount)) for category, amount in rows}


async def _main_currency(session: AsyncSession, org_id: uuid.UUID) -> tuple[str, bool]:
    rows = (
        await session.execute(
            select(CostEntry.currency, func.count())
            .join(WorkUnit, WorkUnit.id == CostEntry.work_unit_id)
            .where(WorkUnit.organization_id == org_id)
            .group_by(CostEntry.currency)
        )
    ).all()
    if not rows:
        return DEFAULT_CURRENCY, False
    return max(rows, key=lambda row: row[1])[0] or DEFAULT_CURRENCY, len(rows) > 1


async def _partners(session: AsyncSession, org_id: uuid.UUID, from_date: date, to_date: date) -> list[PartnerWork]:
    projects = (
        await session.execute(
            select(WorkUnit.id, WorkUnit.partner_organization_id, WorkUnit.status).where(
                WorkUnit.organization_id == org_id, WorkUnit.partner_organization_id.is_not(None)
            )
        )
    ).all()
    if not projects:
        return []
    paid = dict(
        (
            await session.execute(
                select(CostEntry.work_unit_id, func.coalesce(func.sum(CostEntry.amount), 0))
                .where(
                    CostEntry.work_unit_id.in_([row.id for row in projects]),
                    CostEntry.category == SUBCONTRACT_CATEGORY,
                    CostEntry.occurred_on >= from_date,
                    CostEntry.occurred_on <= to_date,
                )
                .group_by(CostEntry.work_unit_id)
            )
        ).all()
    )
    by_partner: dict[uuid.UUID, dict] = {}
    for project_id, partner_id, status in projects:
        partner = by_partner.setdefault(partner_id, {"ids": [], "running": 0, "paid": Decimal(0)})
        partner["ids"].append(project_id)
        partner["running"] += status in RUNNING_PROJECT_STATUSES
        partner["paid"] += Decimal(str(paid.get(project_id, 0)))
    return sorted(
        (
            PartnerWork(
                organization_id=partner_id,
                projects=len(work["ids"]),
                running=work["running"],
                subcontract_costs=_round(work["paid"]),
                work_unit_ids=work["ids"],
            )
            for partner_id, work in by_partner.items()
        ),
        key=lambda p: -p.subcontract_costs,
    )
