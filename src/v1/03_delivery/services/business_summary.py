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
from models.task import Task
from models.work_unit import WorkUnit, WorkUnitMember
from schemas.business_summary import (
    CategoryCost,
    ClientProjects,
    DeliveryBusinessSummary,
    PartnerWork,
    Period,
    ProjectCounts,
    Workload,
)
from services.stats import RUNNING_PROJECT_STATUSES
from services.tasks import _OPEN_TASK_STATUSES

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
        running_by_client=await _running_by_client(session, org_id),
    )


async def workload(
    session: AsyncSession, org_id: uuid.UUID, user_ids: list[uuid.UUID], today: Optional[date] = None
) -> Workload:
    """Which of these users have work: an open task, or a place on a running project."""
    if not user_ids:
        return Workload(working_user_ids=[], running_projects=0)
    today = today or date.today()
    running = (WorkUnit.organization_id == org_id, WorkUnit.status.in_(RUNNING_PROJECT_STATUSES))
    staffed_today = and_(
        WorkUnitMember.valid_from <= today, or_(WorkUnitMember.valid_to.is_(None), WorkUnitMember.valid_to >= today)
    )
    members = (
        await session.execute(
            select(WorkUnitMember.user_id, WorkUnit.id)
            .join(WorkUnit, WorkUnit.id == WorkUnitMember.work_unit_id)
            .where(*running, WorkUnitMember.user_id.in_(user_ids), staffed_today)
        )
    ).all()
    managers = (
        await session.execute(select(WorkUnit.manager_user_id, WorkUnit.id).where(*running, WorkUnit.manager_user_id.in_(user_ids)))
    ).all()
    with_tasks = (
        await session.execute(
            select(Task.assignee_user_id)
            .where(
                Task.organization_id == org_id,
                Task.assignee_user_id.in_(user_ids),
                Task.status.in_(_OPEN_TASK_STATUSES),
            )
            .distinct()
        )
    ).scalars().all()
    on_projects = [*members, *managers]
    working = {user_id for user_id, _ in on_projects} | set(with_tasks)
    return Workload(
        working_user_ids=sorted(working, key=str),
        running_projects=len({project_id for _, project_id in on_projects}),
    )


async def _running_by_client(session: AsyncSession, org_id: uuid.UUID) -> list[ClientProjects]:
    rows = (
        await session.execute(
            select(WorkUnit.client_id, func.count())
            .where(
                WorkUnit.organization_id == org_id,
                WorkUnit.status.in_(RUNNING_PROJECT_STATUSES),
                WorkUnit.parent_work_unit_id.is_(None),
            )
            .group_by(WorkUnit.client_id)
        )
    ).all()
    return sorted((ClientProjects(client_id=client_id, count=int(count)) for client_id, count in rows), key=lambda row: -row.count)


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
            ).where(
                WorkUnit.organization_id == org_id,
                WorkUnit.status.in_(RUNNING_PROJECT_STATUSES),
                # A project with workstreams is one project.
                WorkUnit.parent_work_unit_id.is_(None),
            )
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
