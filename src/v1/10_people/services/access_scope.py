"""
Which employees a caller may act on, as Identity decides it.

Identity tells People, per permission code, whether the caller holds it company-wide, only within some
units (`unit_scopes`, the units at or below the ones granted), or only for their own records
(`own_records_only`). A route guard only checks that the code is held somewhere; this module narrows
every read and write to the employees inside that reach. Outside it an employee answers 404, so a
scoped user never learns whether a record exists.

Several codes may allow the same screen (a picker open to attendance, leave and payroll users): the
reach is the union of what each held code allows.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import PermissionDeniedError, SelfApprovalError, WorkerNotFoundError
from models.worker import Worker
from services.identity_client import Actor


@dataclass(frozen=True)
class WorkerScope:
    """Everyone in the organization, or the employees of some units plus the caller's own record."""

    everyone: bool
    unit_ids: frozenset[uuid.UUID]
    own_user_id: Optional[uuid.UUID]

    def covers(self, worker: Worker) -> bool:
        if self.everyone:
            return True
        if self.own_user_id is not None and worker.user_id == self.own_user_id:
            return True
        return worker.unit_id is not None and worker.unit_id in self.unit_ids

    def condition(self) -> Optional[ColumnElement[bool]]:
        """A filter on `Worker` for this reach; None when it is the whole organization."""
        if self.everyone:
            return None
        clauses = []
        if self.unit_ids:
            clauses.append(Worker.unit_id.in_(self.unit_ids))
        if self.own_user_id is not None:
            clauses.append(Worker.user_id == self.own_user_id)
        return or_(*clauses) if clauses else false()


NOBODY = WorkerScope(everyone=False, unit_ids=frozenset(), own_user_id=None)


def worker_scope(actor: Actor, *permissions: str) -> WorkerScope:
    """The employees the caller reaches through any of `permissions` they hold."""
    if actor.is_superuser:
        return WorkerScope(everyone=True, unit_ids=frozenset(), own_user_id=None)
    held = [code for code in permissions if code in actor.permissions]
    if not held:
        return NOBODY
    unit_ids: set[uuid.UUID] = set()
    for code in held:
        if actor.only_own(code):
            continue  # their own record only, added below
        units = actor.units_for(code)
        if units is None:
            return WorkerScope(everyone=True, unit_ids=frozenset(), own_user_id=None)  # company-wide
        unit_ids |= units
    return WorkerScope(everyone=False, unit_ids=frozenset(unit_ids), own_user_id=actor.user_id)


def self_service_scope(actor: Actor, manage_permission: str) -> WorkerScope:
    """The caller's own record, plus whoever they reach through `manage_permission`."""
    scope = worker_scope(actor, manage_permission)
    if scope.everyone:
        return scope
    return WorkerScope(everyone=False, unit_ids=scope.unit_ids, own_user_id=actor.user_id)


def is_organization_wide(actor: Actor, *permissions: str) -> bool:
    return worker_scope(actor, *permissions).everyone


def require_organization_wide(actor: Actor, permission: str) -> None:
    """For actions over the whole organization (a payroll run): a unit-limited grant is not enough."""
    if not is_organization_wide(actor, permission):
        raise PermissionDeniedError(permission)


def worker_ids_in(scope: WorkerScope, organization_id: uuid.UUID):
    """A subquery of the worker ids inside `scope`, or None for the whole organization."""
    condition = scope.condition()
    if condition is None:
        return None
    return select(Worker.id).where(Worker.organization_id == organization_id, condition)


def scoped_worker_ids(actor: Actor, organization_id: uuid.UUID, *permissions: str):
    """A subquery of the worker ids the caller reaches through `permissions`, or None for the whole organization."""
    return worker_ids_in(worker_scope(actor, *permissions), organization_id)


async def load_worker(session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID) -> Worker:
    worker = await session.get(Worker, worker_id)
    if worker is None or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")
    return worker


async def worker_in_scope(session: AsyncSession, actor: Actor, worker_id: uuid.UUID, *permissions: str) -> Worker:
    """The employee, when the caller reaches them through one of `permissions`; 404 otherwise."""
    worker = await load_worker(session, actor.organization_id, worker_id)
    if not worker_scope(actor, *permissions).covers(worker):
        raise WorkerNotFoundError("Worker not found")
    return worker


def is_own_record(actor: Actor, worker: Worker) -> bool:
    return worker.user_id is not None and worker.user_id == actor.user_id


async def own_or_managed_worker(
    session: AsyncSession, actor: Actor, worker_id: uuid.UUID, manage_permission: str
) -> Worker:
    """
    Self-service: anyone may act on their own record; acting for someone else needs `manage_permission`
    over that person (an HR user filing on an employee's behalf).
    """
    worker = await load_worker(session, actor.organization_id, worker_id)
    if is_own_record(actor, worker):
        return worker
    if not worker_scope(actor, manage_permission).covers(worker):
        raise WorkerNotFoundError("Worker not found")
    return worker


def refuse_self_decision(actor: Actor, worker: Optional[Worker], what: str) -> None:
    """Nobody approves or rejects their own request."""
    if worker is not None and is_own_record(actor, worker):
        raise SelfApprovalError(f"Your own {what} must be decided by someone else")
