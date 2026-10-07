"""Task types: the built-in ones every organization shares, and an organization's own."""

import uuid
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import BuiltInReadOnlyError, DuplicateCodeError, TaskTypeNotFoundError
from models.task_template import TaskType
from models.task_type_profile import TaskTypeProfile
from schemas.common import PageResponse
from schemas.task_types import TaskTypeCreate, TaskTypeResponse, TaskTypeUpdate
from services.pagination import paginate
from services.task_profiles import Profile, load_profiles

_PROFILE_COLUMNS = (
    "discipline",
    "estimation_unit",
    "fields",
    "outcomes",
    "response_sla_minutes",
    "resolution_sla_minutes",
    "review_rounds_included",
    "archived",
)
_TYPE_COLUMNS = ("name", "category", "requires_review", "default_estimate_minutes")
# An explicit null on these means "leave it", since they can't be empty.
_NOT_CLEARABLE = {"name", "category", "requires_review", "discipline", "estimation_unit", "archived"}


def _visible_to(org_id: uuid.UUID):
    return or_(TaskType.organization_id == org_id, TaskType.organization_id.is_(None))


def _response(task_type: TaskType, profile: Profile) -> TaskTypeResponse:
    return TaskTypeResponse(
        id=task_type.id,
        code=task_type.code,
        name=task_type.name,
        category=task_type.category,
        requires_review=task_type.requires_review,
        default_estimate_minutes=task_type.default_estimate_minutes,
        is_builtin=task_type.organization_id is None,
        discipline=profile.discipline,
        estimation_unit=profile.estimation_unit,
        fields=profile.fields,
        outcomes=profile.outcomes,
        response_sla_minutes=profile.response_sla_minutes or None,
        resolution_sla_minutes=profile.resolution_sla_minutes or None,
        review_rounds_included=profile.review_rounds_included,
        archived=profile.archived,
    )


async def list_task_types(
    session: AsyncSession,
    org_id: uuid.UUID,
    discipline: Optional[str],
    include_archived: bool,
    limit: int,
    cursor: Optional[str],
) -> PageResponse[TaskTypeResponse]:
    query = select(TaskType).where(_visible_to(org_id))
    if discipline is not None or not include_archived:
        query = query.outerjoin(TaskTypeProfile, TaskTypeProfile.task_type_id == TaskType.id)
    if discipline is not None:
        # A type without a profile is a plain "general" one.
        query = query.where(
            TaskTypeProfile.discipline == discipline
            if discipline != "general"
            else or_(TaskTypeProfile.discipline == "general", TaskTypeProfile.task_type_id.is_(None))
        )
    if not include_archived:
        query = query.where(or_(TaskTypeProfile.archived.is_(False), TaskTypeProfile.task_type_id.is_(None)))
    rows, page = await paginate(session, query, TaskType, limit, cursor, order_by=TaskType.code)
    profiles = await load_profiles(session, {t.id for t in rows})
    return PageResponse(data=[_response(t, profiles[t.id]) for t in rows], page=page)


async def _get_visible(session: AsyncSession, org_id: uuid.UUID, task_type_id: uuid.UUID) -> TaskType:
    task_type = (
        await session.execute(select(TaskType).where(TaskType.id == task_type_id, _visible_to(org_id)))
    ).scalars().first()
    if not task_type:
        raise TaskTypeNotFoundError(str(task_type_id))
    return task_type


async def get_task_type(session: AsyncSession, org_id: uuid.UUID, task_type_id: uuid.UUID) -> TaskTypeResponse:
    task_type = await _get_visible(session, org_id, task_type_id)
    profiles = await load_profiles(session, {task_type.id})
    return _response(task_type, profiles[task_type.id])


async def create_task_type(session: AsyncSession, org_id: uuid.UUID, data: TaskTypeCreate) -> TaskTypeResponse:
    # Built-in codes are taken too: a task names its type by code.
    taken = (
        await session.execute(select(TaskType.id).where(_visible_to(org_id), TaskType.code == data.code))
    ).first()
    if taken:
        raise DuplicateCodeError(data.code)

    task_type = TaskType(organization_id=org_id, **data.model_dump(include=set(_TYPE_COLUMNS) | {"code"}))
    session.add(task_type)
    await session.flush()
    session.add(TaskTypeProfile(task_type_id=task_type.id, archived=False, **_profile_values(data, exclude={"archived"})))
    await session.flush()
    return await get_task_type(session, org_id, task_type.id)


async def update_task_type(
    session: AsyncSession, org_id: uuid.UUID, task_type_id: uuid.UUID, data: TaskTypeUpdate
) -> TaskTypeResponse:
    task_type = await _get_visible(session, org_id, task_type_id)
    if task_type.organization_id is None:
        raise BuiltInReadOnlyError(task_type.code)

    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k not in _NOT_CLEARABLE}
    for column in _TYPE_COLUMNS:
        if column in changes:
            setattr(task_type, column, changes[column])

    profile = await session.get(TaskTypeProfile, task_type.id)
    if profile is None:
        profile = TaskTypeProfile(task_type_id=task_type.id, discipline="general", estimation_unit="minutes", archived=False)
        session.add(profile)
    for column, value in _profile_values(data, exclude=set(), only_set=True).items():
        setattr(profile, column, value)
    await session.flush()
    return await get_task_type(session, org_id, task_type.id)


def _profile_values(data: TaskTypeCreate | TaskTypeUpdate, exclude: set[str], only_set: bool = False) -> dict:
    """The profile columns `data` carries, as stored (fields and outcomes as plain JSON)."""
    values = data.model_dump(include=set(_PROFILE_COLUMNS) - exclude, exclude_unset=only_set, mode="json")
    if only_set:
        # An omitted key keeps the stored value; an explicit null clears it (SLA targets, rounds).
        values = {
            k: v for k, v in values.items() if k in data.model_fields_set and (v is not None or k not in _NOT_CLEARABLE)
        }
    return values
