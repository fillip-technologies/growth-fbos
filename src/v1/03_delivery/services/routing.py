"""
Routing: which team a kind of work goes to, and the requests people send to other teams.

A routing rule (models/routing.py) names a task type or a discipline, optionally a vertical,
and the team that does that work. For a task of type T (discipline D) for vertical V, the most
specific active rule decides:

1. the rule for T and V;
2. the rule for T, any vertical;
3. the rule for D and V;
4. the rule for D, any vertical.

So a rule naming the task type beats one naming its discipline, and then a rule naming the
vertical beats one for any vertical. Only one active rule may cover the same work, so this
order alone decides. Without rules nothing is routed: tasks keep the team they are given.

A request is a task someone asks another team for without managing tasks. It is allowed only
when the rule that routes that work accepts requests, and it lands unassigned in that rule's
team queue (`source="request"`). The person who asked watches it and finds it in "My requests".
"""
from datetime import datetime, timezone
from typing import Iterable, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import DuplicateRoutingRuleError, NotRequestableError, RoutingRuleNotFoundError
from models.routing import RoutingRule
from models.task import TaskWatcher
from models.task_template import TaskType
from schemas.common import PageResponse
from schemas.routing import (
    RequestableType,
    RequestableTypesResponse,
    RequestCreate,
    RouteResponse,
    RoutingRuleCreate,
    RoutingRuleResponse,
    RoutingRuleUpdate,
)
from schemas.tasks import TaskCreate, TaskResponse
from services.assignees import PeopleDirectory
from services.pagination import paginate
from services.refs import unit_ref, vertical_ref
from services.task_profiles import load_profiles
from services.tasks import WORK_UNIT_SUBJECT, create_task, subject_work_unit, task_type_by_code, visible_task_types
from services.versions import check_if_match

# How specifically a rule covers some work: (kind, vertical), lower first.
_BY_TYPE, _BY_DISCIPLINE = 0, 1
_FOR_VERTICAL, _FOR_ANY_VERTICAL = 0, 1


def _specificity(
    rule: RoutingRule, task_type_code: str, discipline: str, vertical_id: Optional[uuid.UUID]
) -> Optional[tuple[int, int]]:
    """Where `rule` stands for this work in the order above; None when it doesn't cover it."""
    if rule.task_type_code is not None:
        if rule.task_type_code != task_type_code:
            return None
        kind = _BY_TYPE
    elif rule.discipline == discipline:
        kind = _BY_DISCIPLINE
    else:
        return None
    if rule.vertical_id is None:
        return kind, _FOR_ANY_VERTICAL
    return (kind, _FOR_VERTICAL) if rule.vertical_id == vertical_id else None


def _deciding_rule(
    rules: Iterable[RoutingRule], task_type_code: str, discipline: str, vertical_id: Optional[uuid.UUID]
) -> Optional[RoutingRule]:
    """The most specific of the active `rules` covering the work, or None."""
    covering = [
        (rank, rule) for rule in rules if (rank := _specificity(rule, task_type_code, discipline, vertical_id)) is not None
    ]
    if not covering:
        return None
    # Duplicates are refused, but should two ever match equally the older one decides, every time.
    return min(covering, key=lambda pair: (pair[0], pair[1].created_at, str(pair[1].id)))[1]


async def _active_rules(session: AsyncSession, org_id: uuid.UUID) -> list[RoutingRule]:
    query = select(RoutingRule).where(RoutingRule.organization_id == org_id, RoutingRule.active.is_(True))
    return list((await session.execute(query)).scalars().all())


def _rule_response(rule: RoutingRule) -> RoutingRuleResponse:
    return RoutingRuleResponse(
        id=rule.id,
        task_type_code=rule.task_type_code,
        discipline=rule.discipline,
        vertical=vertical_ref(rule.vertical_id),
        unit=unit_ref(rule.unit_id),
        accepts_requests=rule.accepts_requests,
        active=rule.active,
        version=rule.version,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


# --- Routing -----------------------------------------------------------------


async def route(
    session: AsyncSession, org_id: uuid.UUID, task_type_code: str, vertical_id: Optional[uuid.UUID]
) -> RouteResponse:
    """The team this kind of work goes to (none without a rule covering it), for the task forms."""
    task_type, profile = await task_type_by_code(session, org_id, task_type_code)
    rule = _deciding_rule(await _active_rules(session, org_id), task_type.code, profile.discipline, vertical_id)
    if rule is None:
        return RouteResponse()
    return RouteResponse(unit=unit_ref(rule.unit_id), rule_id=rule.id, accepts_requests=rule.accepts_requests)


# --- Rules -------------------------------------------------------------------


async def list_rules(
    session: AsyncSession, org_id: uuid.UUID, include_inactive: bool, limit: int, cursor: Optional[str]
) -> PageResponse[RoutingRuleResponse]:
    """The organization's rules, oldest first."""
    query = select(RoutingRule).where(RoutingRule.organization_id == org_id)
    if not include_inactive:
        query = query.where(RoutingRule.active.is_(True))
    rows, page = await paginate(session, query, RoutingRule, limit, cursor, order_by=RoutingRule.created_at)
    return PageResponse(data=[_rule_response(rule) for rule in rows], page=page)


async def _refuse_duplicate(session: AsyncSession, org_id: uuid.UUID, rule: RoutingRule | RoutingRuleCreate) -> None:
    """Only one active rule may cover the same work: same task type or discipline, same vertical."""

    def same(column, value):
        return column.is_(None) if value is None else column == value

    query = select(RoutingRule.id).where(
        RoutingRule.organization_id == org_id,
        RoutingRule.active.is_(True),
        same(RoutingRule.task_type_code, rule.task_type_code),
        same(RoutingRule.discipline, rule.discipline),
        same(RoutingRule.vertical_id, rule.vertical_id),
    )
    if isinstance(rule, RoutingRule):
        query = query.where(RoutingRule.id != rule.id)
    existing = (await session.execute(query.limit(1))).scalar_one_or_none()
    if existing is not None:
        raise DuplicateRoutingRuleError(str(existing))


async def create_rule(session: AsyncSession, org_id: uuid.UUID, data: RoutingRuleCreate) -> RoutingRuleResponse:
    if data.task_type_code:
        await task_type_by_code(session, org_id, data.task_type_code)
    await _refuse_duplicate(session, org_id, data)
    rule = RoutingRule(
        organization_id=org_id,
        task_type_code=data.task_type_code,
        discipline=data.discipline,
        vertical_id=data.vertical_id,
        unit_id=data.unit_id,
        accepts_requests=data.accepts_requests,
        active=True,
        version=1,
    )
    session.add(rule)
    await session.flush()
    return _rule_response(rule)


async def update_rule(
    session: AsyncSession, org_id: uuid.UUID, rule_id: uuid.UUID, data: RoutingRuleUpdate, if_match: Optional[str]
) -> RoutingRuleResponse:
    """Change a rule's team or whether it takes requests, or turn it off and on (If-Match: its version)."""
    rule = (
        await session.execute(select(RoutingRule).where(RoutingRule.id == rule_id, RoutingRule.organization_id == org_id))
    ).scalars().first()
    if rule is None:
        raise RoutingRuleNotFoundError(str(rule_id))
    check_if_match(if_match, rule.version)
    if data.active and not rule.active:
        await _refuse_duplicate(session, org_id, rule)

    # None means "leave it": none of these can be empty.
    for key, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(rule, key, value)
    rule.version += 1
    rule.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return _rule_response(rule)


# --- Requests ----------------------------------------------------------------


async def requestable_types(session: AsyncSession, org_id: uuid.UUID) -> RequestableTypesResponse:
    """
    What people may ask other teams for: each usable task type, for each vertical the rules name
    (and for any other), whose deciding rule takes requests. Worked out with the same order as
    routing, so a type listed here is one a request for it is accepted.
    """
    rules = await _active_rules(session, org_id)
    if not any(rule.accepts_requests for rule in rules):
        return RequestableTypesResponse(data=[])

    task_types = list(
        (await session.execute(select(TaskType).where(visible_task_types(org_id)).order_by(TaskType.name))).scalars().all()
    )
    profiles = await load_profiles(session, {t.id for t in task_types})
    verticals: list[Optional[uuid.UUID]] = [None, *sorted({r.vertical_id for r in rules if r.vertical_id}, key=str)]

    offered: list[RequestableType] = []
    for task_type in task_types:
        profile = profiles[task_type.id]
        if profile.archived:
            continue
        for vertical_id in verticals:
            rule = _deciding_rule(rules, task_type.code, profile.discipline, vertical_id)
            if rule is None or not rule.accepts_requests:
                continue
            # Decided by a rule for any vertical: the same as the entry for any vertical.
            if vertical_id is not None and rule.vertical_id is None:
                continue
            offered.append(
                RequestableType(
                    task_type_code=task_type.code,
                    name=task_type.name,
                    discipline=profile.discipline,
                    vertical=vertical_ref(vertical_id),
                    unit=unit_ref(rule.unit_id),
                )
            )
    return RequestableTypesResponse(data=offered)


async def create_request(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: RequestCreate, people: PeopleDirectory
) -> TaskResponse:
    """Ask the team that does this kind of work for it: a task in that team's queue, which the asker watches."""
    task_type, profile = await task_type_by_code(session, org_id, data.task_type_code)
    vertical_id = data.vertical_id
    if data.subject and data.subject.type == WORK_UNIT_SUBJECT:
        # Work on a project is for the project's vertical (as its custom fields are).
        project = await subject_work_unit(session, org_id, data.subject.type, data.subject.id)
        vertical_id = project.vertical_id if project else None

    rule = _deciding_rule(await _active_rules(session, org_id), task_type.code, profile.discipline, vertical_id)
    if rule is None or not rule.accepts_requests:
        raise NotRequestableError(task_type.code)

    task = await create_task(
        session,
        org_id,
        user_id,
        TaskCreate(
            title=data.title,
            description=data.description,
            task_type_code=task_type.code,
            subject=data.subject,
            owning_unit_id=rule.unit_id,
            priority=data.priority,
            due_at=data.due_at,
            attributes=data.attributes,
        ),
        people,
        source="request",
    )
    session.add(TaskWatcher(task_id=task.id, user_id=user_id))
    await session.flush()
    return task
