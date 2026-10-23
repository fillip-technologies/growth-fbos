"""
Delivery's answer to the documents service: may this user see, or attach files to, this
project / work unit or task?

Each attachable record type is one `SubjectRule`; making another delivery record take
documents means adding a rule here, nothing in the documents service.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import PermissionDeniedError, SubjectLockedError, SubjectNotFoundError
from schemas.subject_access import SubjectAccessResponse
from services.identity_client import Actor
from services.tasks import _get_task, ensure_task_visible
from services.views import project_view, task_view
from services.work_units import _get_work_unit, ensure_work_unit_visible

SubjectAction = Literal["read", "attach"]


@dataclass(frozen=True)
class LoadedSubject:
    status: str
    label: str


@dataclass(frozen=True)
class SubjectRule:
    read_permission: str
    attach_permission: str
    closed_statuses: frozenset[str]
    load: Callable[[AsyncSession, Actor, uuid.UUID], Awaitable[LoadedSubject]]


async def _load_project(session: AsyncSession, actor: Actor, work_unit_id: uuid.UUID) -> LoadedSubject:
    view = await project_view(session, actor)
    if view is not None:
        await ensure_work_unit_visible(session, actor.organization_id, work_unit_id, view)
    work_unit = await _get_work_unit(session, actor.organization_id, work_unit_id)
    return LoadedSubject(status=work_unit.status, label=work_unit.name)


async def _load_task(session: AsyncSession, actor: Actor, task_id: uuid.UUID) -> LoadedSubject:
    view = await task_view(session, actor)
    if view is not None:
        await ensure_task_visible(session, actor.organization_id, task_id, view)
    task = await _get_task(session, actor.organization_id, task_id)
    return LoadedSubject(status=task.status, label=task.title)


SUBJECT_RULES: dict[str, SubjectRule] = {
    "delivery.project": SubjectRule(
        read_permission=permissions.WORK_UNIT_READ,
        attach_permission=permissions.WORK_UNIT_WRITE,
        closed_statuses=frozenset({"completed", "closed", "cancelled"}),
        load=_load_project,
    ),
    "delivery.work_unit": SubjectRule(
        read_permission=permissions.WORK_UNIT_READ,
        attach_permission=permissions.WORK_UNIT_WRITE,
        closed_statuses=frozenset({"completed", "closed", "cancelled"}),
        load=_load_project,
    ),
    "work.work_unit": SubjectRule(
        read_permission=permissions.WORK_UNIT_READ,
        attach_permission=permissions.WORK_UNIT_WRITE,
        closed_statuses=frozenset({"completed", "closed", "cancelled"}),
        load=_load_project,
    ),
    "delivery.task": SubjectRule(
        read_permission=permissions.TASK_READ,
        attach_permission=permissions.TASK_WRITE,
        closed_statuses=frozenset({"done", "cancelled"}),
        load=_load_task,
    ),
    "task.task": SubjectRule(
        read_permission=permissions.TASK_READ,
        attach_permission=permissions.TASK_WRITE,
        closed_statuses=frozenset({"done", "cancelled"}),
        load=_load_task,
    ),
}


async def check_subject_access(
    session: AsyncSession,
    actor: Actor,
    subject_type: str,
    subject_id: uuid.UUID,
    action: SubjectAction,
) -> SubjectAccessResponse:
    rule = SUBJECT_RULES.get(subject_type)
    if not rule:
        raise SubjectNotFoundError(subject_type)

    permission = rule.attach_permission if action == "attach" else rule.read_permission
    if not actor.has(permission):
        raise PermissionDeniedError(permission)

    subject = await rule.load(session, actor, subject_id)
    if action == "attach" and subject.status in rule.closed_statuses:
        raise SubjectLockedError(subject_type, subject.status)

    return SubjectAccessResponse(
        type=subject_type, id=subject_id, organization_id=actor.organization_id, label=subject.label
    )
