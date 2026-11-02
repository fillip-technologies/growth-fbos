"""
Posts: the jobs one person holds (primary, concurrent, additional charge, acting).

A person always has exactly one active primary post. Its title, department and manager are copied
onto the worker record, so lists, filters and approvals keep working from the worker alone.
Posts are effective-dated: changing one ends the current version and adds a new one.

The rules live in `check_rules`, a pure function over a list of posts, so a role change can test
"what would the person's posts look like" before anything is written.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from config import settings
from exceptions import ConflictError, PostNotFoundError, ValidationFailedError
from models.job_architecture import Position
from models.worker import PositionAssignment, Worker
from models.worker_post import WorkerPost
from services.identity_client import Actor

ACTIVE, ENDED = "active", "ended"
PRIMARY, CONCURRENT, ADDITIONAL_CHARGE, ACTING = "primary", "concurrent", "additional_charge", "acting"
POST_TYPES = (PRIMARY, CONCURRENT, ADDITIONAL_CHARGE, ACTING)
SHARING_TYPES = (PRIMARY, CONCURRENT)  # these split the person's working time
FULL_TIME = Decimal(100)

# Fields a new version of a post carries over from the one it replaces.
CARRIED_FIELDS = ("post_type", "title", "unit_id", "position_id", "manager_id", "time_share", "monthly_allowance")


# --- Rules ----------------------------------------------------------------------------------------


def primary_share(posts: Iterable[WorkerPost]) -> Decimal:
    """The share of time the primary post gets: what it says, or whatever the concurrent posts leave."""
    posts = list(posts)
    primary = next((p for p in posts if p.post_type == PRIMARY), None)
    if primary is not None and primary.time_share is not None:
        return Decimal(primary.time_share)
    return FULL_TIME - sum((Decimal(p.time_share or 0) for p in posts if p.post_type == CONCURRENT), Decimal(0))


def check_rules(posts: list[WorkerPost]) -> None:
    """Raise unless this set of active posts is allowed. Used before a change is made and after."""
    primaries = [p for p in posts if p.post_type == PRIMARY]
    if len(primaries) != 1:
        raise ConflictError("A person must have exactly one primary post", code="POST_PRIMARY_REQUIRED")

    for post in posts:
        if post.post_type not in SHARING_TYPES and post.time_share is not None:
            raise ValidationFailedError("time_share", "An additional charge or acting post has no share of time")
        if post.time_share is not None and not Decimal(0) < Decimal(post.time_share) <= FULL_TIME:
            raise ValidationFailedError("time_share", "A share of time is between 0 and 100 percent")
        if post.post_type == CONCURRENT and post.time_share is None:
            raise ValidationFailedError("time_share", "A concurrent post needs a share of time")

    explicit = sum((Decimal(p.time_share) for p in posts if p.post_type in SHARING_TYPES and p.time_share is not None), Decimal(0))
    if explicit > FULL_TIME:
        raise ValidationFailedError("time_share", f"Shares of time add up to {explicit:g}%, more than 100%")
    if primary_share(posts) <= 0:
        raise ValidationFailedError("time_share", "The concurrent posts leave no time for the primary post")

    if len(posts) > settings.max_posts_per_worker:
        raise ConflictError(
            f"A person can hold at most {settings.max_posts_per_worker} posts at once", code="POST_LIMIT_REACHED"
        )

    seen: set[tuple[str, Optional[uuid.UUID]]] = set()
    for post in posts:
        key = (post.title.strip().lower(), post.unit_id)
        if key in seen:
            raise ConflictError(f"The person already holds '{post.title}' in that department", code="POST_DUPLICATE")
        seen.add(key)


# --- Reading --------------------------------------------------------------------------------------


async def live_posts(session: AsyncSession, worker: Worker) -> list[WorkerPost]:
    """The posts the person holds today, primary first."""
    posts = (
        await session.execute(
            select(WorkerPost).where(
                WorkerPost.organization_id == worker.organization_id,
                WorkerPost.worker_id == worker.id,
                WorkerPost.status == ACTIVE,
            )
        )
    ).scalars().all()
    return sorted(posts, key=lambda p: (p.post_type != PRIMARY, p.start_date))


async def get_post(session: AsyncSession, worker: Worker, post_ref: uuid.UUID) -> WorkerPost:
    """The active version of a post, by its stable reference."""
    for post in await live_posts(session, worker):
        if post.post_ref == post_ref:
            return post
    raise PostNotFoundError()


def can_see_allowance(actor: Actor) -> bool:
    return actor.has(permissions.COMPENSATION_READ) or actor.has(permissions.ROLE_CHANGE_APPROVE)


async def list_posts(session: AsyncSession, worker: Worker, include_ended: bool = False) -> list[WorkerPost]:
    if not include_ended:
        return await live_posts(session, worker)
    posts = (
        await session.execute(
            select(WorkerPost).where(
                WorkerPost.organization_id == worker.organization_id, WorkerPost.worker_id == worker.id
            )
        )
    ).scalars().all()
    return sorted(posts, key=lambda p: (p.status != ACTIVE, p.post_type != PRIMARY, p.start_date))


async def to_responses(session: AsyncSession, actor: Actor, posts: list[WorkerPost]) -> list[dict]:
    manager_ids = {p.manager_id for p in posts if p.manager_id}
    names: dict[uuid.UUID, str] = {}
    if manager_ids:
        names = {
            row.id: f"{row.first_name} {row.last_name}".strip()
            for row in await session.execute(
                select(Worker.id, Worker.first_name, Worker.last_name).where(Worker.id.in_(manager_ids))
            )
        }
    show_allowance = can_see_allowance(actor)
    return [
        {
            "id": p.id,
            "post_ref": p.post_ref,
            "worker_id": p.worker_id,
            "post_type": p.post_type,
            "title": p.title,
            "unit_id": p.unit_id,
            "position_id": p.position_id,
            "manager_id": p.manager_id,
            "manager_name": names.get(p.manager_id),
            "time_share": p.time_share,
            "has_allowance": p.monthly_allowance is not None,
            "monthly_allowance": p.monthly_allowance if show_allowance else None,
            "start_date": p.start_date,
            "end_date": p.end_date,
            "status": p.status,
            "role_change_id": p.role_change_id,
        }
        for p in posts
    ]


# --- Writing --------------------------------------------------------------------------------------


def copy_primary_to_worker(worker: Worker, primary: WorkerPost) -> None:
    """The worker record mirrors the primary post."""
    worker.designation = primary.title
    worker.job_title = primary.title
    worker.unit_id = primary.unit_id
    worker.manager_id = primary.manager_id


async def start_primary_post(
    session: AsyncSession, worker: Worker, position_id: Optional[uuid.UUID] = None, start_date: Optional[date] = None
) -> WorkerPost:
    """The first post of a new employee, from their record."""
    post = WorkerPost(
        organization_id=worker.organization_id,
        worker_id=worker.id,
        post_type=PRIMARY,
        title=worker.designation,
        unit_id=worker.unit_id,
        position_id=position_id,
        manager_id=worker.manager_id,
        start_date=start_date or worker.date_of_joining,
        status=ACTIVE,
    )
    session.add(post)
    await session.flush()
    return post


async def version_post(
    session: AsyncSession, post: WorkerPost, effective_date: date, role_change_id: Optional[uuid.UUID] = None, **changes
) -> WorkerPost:
    """
    Change a post as of a date. A post that started on or after that date is edited in place;
    otherwise the current version ends the day before and a new version starts.
    """
    if post.start_date >= effective_date:
        for field, value in changes.items():
            setattr(post, field, value)
        if role_change_id is not None:
            post.role_change_id = role_change_id
        await session.flush()
        return post

    planned_end = post.end_date  # an acting post keeps its planned end date in the new version
    post.status = ENDED
    post.end_date = effective_date - timedelta(days=1)
    carried = {field: getattr(post, field) for field in CARRIED_FIELDS}
    carried.update(changes)
    successor = WorkerPost(
        organization_id=post.organization_id,
        worker_id=post.worker_id,
        post_ref=post.post_ref,
        start_date=effective_date,
        end_date=planned_end,
        status=ACTIVE,
        role_change_id=role_change_id,
        **carried,
    )
    session.add(successor)
    await session.flush()
    return successor


async def sync_primary_post(session: AsyncSession, worker: Worker, effective_date: date) -> None:
    """
    Make the primary post match the worker record, for the places that still edit the record
    directly (department, manager, a title set by a promotion record).
    """
    posts = await live_posts(session, worker)
    primary = next((p for p in posts if p.post_type == PRIMARY), None)
    if primary is None:
        await start_primary_post(session, worker, start_date=min(effective_date, worker.date_of_joining))
        return
    if (primary.title, primary.unit_id, primary.manager_id) == (worker.designation, worker.unit_id, worker.manager_id):
        return
    await version_post(
        session, primary, effective_date, title=worker.designation, unit_id=worker.unit_id, manager_id=worker.manager_id
    )


async def end_post(session: AsyncSession, post: WorkerPost, end_date: date) -> None:
    post.status = ENDED
    post.end_date = end_date
    await session.flush()


async def end_all_posts(session: AsyncSession, worker: Worker, end_date: date) -> None:
    """An exit ends every post the person holds."""
    for post in await live_posts(session, worker):
        await end_post(session, post, end_date)


def post_fte(post: WorkerPost, live: list[WorkerPost]) -> Decimal:
    """
    How much of a seat's budget a post uses. A primary or concurrent post uses its share of the person's
    time (a primary without one uses what the concurrent posts leave); an additional-charge or acting
    post covers for the seat and adds no headcount, so it uses none.
    """
    if post.post_type not in SHARING_TYPES:
        return Decimal(0)
    if post.time_share is not None:
        return Decimal(post.time_share) / 100
    return primary_share(live) / 100 if post.post_type == PRIMARY else Decimal(1)


async def seat_used_fte(session: AsyncSession, position_id: uuid.UUID) -> Decimal:
    used = (
        await session.execute(
            select(func.coalesce(func.sum(PositionAssignment.assigned_fte), 0)).where(
                PositionAssignment.position_id == position_id, PositionAssignment.status == ACTIVE
            )
        )
    ).scalar_one()
    return Decimal(str(used))


async def refresh_seat(session: AsyncSession, position: Position) -> None:
    """A seat is filled once its budgeted FTE is fully used, and open while there is room (a frozen seat stays frozen)."""
    if position.hiring_status == "frozen":
        return
    used = await seat_used_fte(session, position.id)
    position.hiring_status = "filled" if used >= Decimal(str(position.budgeted_fte)) else "vacant"


async def occupy_seat(
    session: AsyncSession, worker: Worker, position: Position, start_date: date, is_primary: bool, fte: Decimal = Decimal(1)
) -> None:
    session.add(
        PositionAssignment(
            organization_id=worker.organization_id,
            worker_id=worker.id,
            position_id=position.id,
            is_primary=is_primary,
            assigned_fte=fte,
            effective_start_date=start_date,
            status=ACTIVE,
        )
    )
    await session.flush()
    await refresh_seat(session, position)


async def set_seat_fte(session: AsyncSession, worker: Worker, position_id: uuid.UUID, fte: Decimal) -> None:
    """The person's share of the seat changed (their time share did)."""
    held = (
        await session.execute(
            select(PositionAssignment).where(
                PositionAssignment.worker_id == worker.id,
                PositionAssignment.position_id == position_id,
                PositionAssignment.status == ACTIVE,
            )
        )
    ).scalars().all()
    for assignment in held:
        assignment.assigned_fte = fte
    await session.flush()
    position = await session.get(Position, position_id)
    if position is not None:
        await refresh_seat(session, position)


async def vacate_seat(session: AsyncSession, worker: Worker, position_id: uuid.UUID, end_date: date) -> None:
    held = (
        await session.execute(
            select(PositionAssignment).where(
                PositionAssignment.organization_id == worker.organization_id,
                PositionAssignment.worker_id == worker.id,
                PositionAssignment.position_id == position_id,
                PositionAssignment.status == ACTIVE,
            )
        )
    ).scalars().all()
    for assignment in held:
        assignment.status = ENDED
        assignment.effective_end_date = end_date
    await session.flush()
    position = await session.get(Position, position_id)
    if position is not None:
        await refresh_seat(session, position)


async def expire_posts(session: AsyncSession, today: date) -> list[WorkerPost]:
    """End the acting / additional / concurrent posts whose end date has passed, and free their seats. The primary post is never ended here."""
    due = (
        await session.execute(
            select(WorkerPost).where(
                WorkerPost.status == ACTIVE,
                WorkerPost.post_type != PRIMARY,
                WorkerPost.end_date.is_not(None),
                WorkerPost.end_date < today,
            )
        )
    ).scalars().all()
    for post in due:
        post.status = ENDED
        if post.position_id is not None:
            worker = await session.get(Worker, post.worker_id)
            await vacate_seat(session, worker, post.position_id, post.end_date)
    await session.flush()
    return list(due)


async def extra_post_counts(session: AsyncSession, worker_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many posts besides the primary each of these people holds today."""
    if not worker_ids:
        return {}
    rows = await session.execute(
        select(WorkerPost.worker_id, func.count(WorkerPost.id))
        .where(WorkerPost.worker_id.in_(worker_ids), WorkerPost.status == ACTIVE, WorkerPost.post_type != PRIMARY)
        .group_by(WorkerPost.worker_id)
    )
    return {worker_id: count for worker_id, count in rows}


ORG_CHART_LIMIT = 2000


async def org_chart(session: AsyncSession, organization_id: uuid.UUID) -> dict:
    """
    Everyone who has not left, with their primary manager (a solid line) and the managers of their
    other posts (dotted lines). `truncated` says the organization is larger than one answer carries.
    """
    workers = (
        await session.execute(
            select(Worker)
            .where(Worker.organization_id == organization_id, Worker.status != "exited")
            .order_by(Worker.first_name, Worker.last_name)
            .limit(ORG_CHART_LIMIT + 1)
        )
    ).scalars().all()
    truncated = len(workers) > ORG_CHART_LIMIT
    workers = workers[:ORG_CHART_LIMIT]
    ids = {w.id for w in workers}

    dotted: dict[uuid.UUID, list[uuid.UUID]] = {}
    extra_titles: dict[uuid.UUID, list[str]] = {}
    extra_posts = (
        await session.execute(
            select(WorkerPost).where(
                WorkerPost.organization_id == organization_id, WorkerPost.status == ACTIVE, WorkerPost.post_type != PRIMARY
            )
        )
    ).scalars()
    for post in extra_posts:
        extra_titles.setdefault(post.worker_id, []).append(post.title)
        if post.manager_id is not None and post.manager_id in ids:
            dotted.setdefault(post.worker_id, [])
            if post.manager_id not in dotted[post.worker_id]:
                dotted[post.worker_id].append(post.manager_id)
    return {
        "truncated": truncated,
        "data": [
            {
                "worker_id": w.id,
                "name": f"{w.first_name} {w.last_name}".strip(),
                "designation": w.designation,
                "unit_id": w.unit_id,
                "status": w.status,
                "manager_id": w.manager_id if w.manager_id in ids else None,
                "dotted_manager_ids": [m for m in dotted.get(w.id, []) if m != w.manager_id],
                "extra_post_titles": extra_titles.get(w.id, []),
            }
            for w in workers
        ],
    }


async def allowance_lines_for_month(
    session: AsyncSession, worker_id: uuid.UUID, month_start: date, month_end: date
) -> list[dict]:
    """
    The allowance each post paid in a month: its monthly amount for the days it was held within the
    month, over the days in the month. A post that changed during the month counts each version for its own days.
    """
    versions = (
        await session.execute(
            select(WorkerPost).where(
                WorkerPost.worker_id == worker_id,
                WorkerPost.monthly_allowance.is_not(None),
                WorkerPost.start_date <= month_end,
                or_(WorkerPost.end_date.is_(None), WorkerPost.end_date >= month_start),
            )
        )
    ).scalars().all()
    days_in_month = (month_end - month_start).days + 1
    lines = []
    for post in versions:
        if post.status == ENDED and post.end_date is None:
            continue  # ended without a date (nothing to say how long it was held)
        first = max(post.start_date, month_start)
        last = min(post.end_date or month_end, month_end)
        days = (last - first).days + 1
        if days <= 0:
            continue
        lines.append(
            {
                "title": post.title,
                "post_type": post.post_type,
                "days": days,
                "amount": str((Decimal(post.monthly_allowance) * days / days_in_month).quantize(Decimal("0.01"))),
            }
        )
    return lines


async def posts_report(session: AsyncSession, organization_id: uuid.UUID) -> dict:
    """
    Posts and FTE by department: how many people hold a post there, the posts by kind, the FTE they
    allocate, and the seats' budget against what is used. A post belongs to the department it names;
    a seat to the department it sits in. Posts and seats with no department are grouped under none.
    """
    live = (
        await session.execute(
            select(WorkerPost)
            .join(Worker, Worker.id == WorkerPost.worker_id)
            .where(WorkerPost.organization_id == organization_id, WorkerPost.status == ACTIVE, Worker.status != "exited")
        )
    ).scalars().all()
    by_worker: dict[uuid.UUID, list[WorkerPost]] = {}
    for post in live:
        by_worker.setdefault(post.worker_id, []).append(post)

    def blank(unit_id):
        return {
            "unit_id": unit_id, "people": 0, "primary_posts": 0, "concurrent_posts": 0, "additional_charge_posts": 0,
            "acting_posts": 0, "allocated_fte": Decimal(0), "budgeted_fte": Decimal(0), "seat_used_fte": Decimal(0),
        }

    rows: dict[Optional[uuid.UUID], dict] = {}
    people_in: dict[Optional[uuid.UUID], set[uuid.UUID]] = {}
    for post in live:
        row = rows.setdefault(post.unit_id, blank(post.unit_id))
        row[f"{post.post_type}_posts"] += 1
        row["allocated_fte"] += post_fte(post, by_worker[post.worker_id])
        people_in.setdefault(post.unit_id, set()).add(post.worker_id)
    for unit_id, people in people_in.items():
        rows[unit_id]["people"] = len(people)

    used_by_position = {
        position_id: Decimal(str(used))
        for position_id, used in await session.execute(
            select(PositionAssignment.position_id, func.sum(PositionAssignment.assigned_fte))
            .where(PositionAssignment.organization_id == organization_id, PositionAssignment.status == ACTIVE)
            .group_by(PositionAssignment.position_id)
        )
    }
    for position in (await session.execute(select(Position).where(Position.organization_id == organization_id))).scalars():
        row = rows.setdefault(position.unit_id, blank(position.unit_id))
        row["budgeted_fte"] += Decimal(str(position.budgeted_fte))
        row["seat_used_fte"] += used_by_position.get(position.id, Decimal(0))

    data = sorted(rows.values(), key=lambda r: (r["unit_id"] is None, str(r["unit_id"])))
    for row in data:
        row["open_fte"] = max(row["budgeted_fte"] - row["seat_used_fte"], Decimal(0))
    return {
        "data": data,
        "totals": {
            "people": len(by_worker),
            "posts": len(live),
            "allocated_fte": sum((r["allocated_fte"] for r in data), Decimal(0)),
            "budgeted_fte": sum((r["budgeted_fte"] for r in data), Decimal(0)),
            "seat_used_fte": sum((r["seat_used_fte"] for r in data), Decimal(0)),
        },
    }
