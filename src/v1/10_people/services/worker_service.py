import uuid
from datetime import date
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.worker import Worker, WorkerDocument, WorkerTimelineEvent
from schemas.common import PageMeta
from schemas.worker import (
    ImportableUser,
    TimelineEventCreate,
    WorkerCreate,
    WorkerDetailResponse,
    WorkerImportItem,
    WorkerImportSkipped,
    WorkerResponse,
    WorkerUpdate,
)
from services.codes import next_worker_code
from services.identity_client import IdentityClient, IdentityEmployee
from services.pagination import paginate


def _worker_to_response(w: Worker) -> dict:
    d = {
        "id": w.id,
        "organization_id": w.organization_id,
        "worker_code": w.worker_code,
        "user_id": w.user_id,
        "name": f"{w.first_name} {w.last_name}".strip(),
        "first_name": w.first_name,
        "last_name": w.last_name,
        "work_email": w.work_email,
        "personal_email": w.personal_email,
        "phone": w.phone,
        "date_of_birth": w.date_of_birth,
        "gender": w.gender,
        "blood_group": w.blood_group,
        "residential_address": w.residential_address,
        "emergency_contact_name": w.emergency_contact_name,
        "emergency_contact_relation": w.emergency_contact_relation,
        "emergency_contact_phone": w.emergency_contact_phone,
        "unit_id": w.unit_id,
        "designation": w.designation,
        "job_title": w.job_title,
        "manager_id": w.manager_id,
        "employment_type": w.employment_type,
        "status": w.status,
        "date_of_joining": w.date_of_joining,
        "probation_end_date": w.probation_end_date,
        "confirmation_date": w.confirmation_date,
        "resignation_date": w.resignation_date,
        "last_working_date": w.last_working_date,
        "created_at": w.created_at,
        "updated_at": w.updated_at,
    }
    return d


async def create_worker(
    session: AsyncSession, organization_id: uuid.UUID, data: WorkerCreate
) -> Worker:
    # Check email uniqueness in organization
    existing_email = (
        await session.execute(
            select(Worker).where(
                Worker.organization_id == organization_id,
                Worker.work_email == data.work_email,
            )
        )
    ).scalar_one_or_none()
    if existing_email:
        raise ConflictError(f"Worker with work email '{data.work_email}' already exists")

    # Generate or assign worker code
    if data.custom_worker_code:
        worker_code = data.custom_worker_code.strip()
        existing_code = (
            await session.execute(
                select(Worker).where(
                    Worker.organization_id == organization_id,
                    Worker.worker_code == worker_code,
                )
            )
        ).scalar_one_or_none()
        if existing_code:
            raise ConflictError(f"Worker code '{worker_code}' is already assigned")
    else:
        worker_code = await next_worker_code(session, organization_id)

    # Validate manager if provided
    if data.manager_id:
        manager = (
            await session.execute(
                select(Worker).where(
                    Worker.organization_id == organization_id,
                    Worker.id == data.manager_id,
                )
            )
        ).scalar_one_or_none()
        if not manager:
            raise ValidationFailedError("manager_id", f"Manager '{data.manager_id}' not found in organization")

    worker = Worker(
        organization_id=organization_id,
        worker_code=worker_code,
        user_id=data.user_id,
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        work_email=data.work_email.strip(),
        personal_email=data.personal_email.strip() if data.personal_email else None,
        phone=data.phone.strip() if data.phone else None,
        date_of_birth=data.date_of_birth,
        gender=data.gender,
        blood_group=data.blood_group,
        residential_address=data.residential_address,
        emergency_contact_name=data.emergency_contact_name,
        emergency_contact_relation=data.emergency_contact_relation,
        emergency_contact_phone=data.emergency_contact_phone,
        unit_id=data.unit_id,
        designation=data.designation.strip(),
        job_title=data.job_title.strip() if data.job_title else data.designation.strip(),
        manager_id=data.manager_id,
        employment_type=data.employment_type,
        status=data.status,
        date_of_joining=data.date_of_joining,  # Fully supports past back-dated joining dates
        probation_end_date=data.probation_end_date,
        confirmation_date=data.confirmation_date,
    )
    session.add(worker)
    await session.flush()

    # Automatically create the initial hiring timeline event (with the effective joining date)
    join_event = WorkerTimelineEvent(
        organization_id=organization_id,
        worker_id=worker.id,
        event_category="hire",
        title=f"Joined as {worker.designation}",
        description=f"Joined organization on {worker.date_of_joining.isoformat()} under {worker.employment_type.replace('_', ' ')} status",
        effective_date=worker.date_of_joining,
        new_state={"designation": worker.designation, "unit_id": str(worker.unit_id) if worker.unit_id else None},
    )
    session.add(join_event)
    await session.flush()

    return worker


async def update_worker(
    session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID, data: WorkerUpdate
) -> Worker:
    worker = (
        await session.execute(
            select(Worker).where(
                Worker.organization_id == organization_id,
                Worker.id == worker_id,
            )
        )
    ).scalar_one_or_none()
    if not worker:
        raise WorkerNotFoundError(str(worker_id))

    update_dict = data.model_dump(exclude_unset=True)

    # The employee code can be filled in later; a blank one clears it.
    if "worker_code" in update_dict:
        update_dict["worker_code"] = (update_dict["worker_code"] or "").strip() or None
        new_code = update_dict["worker_code"]
        if new_code and new_code != worker.worker_code and await _worker_code_taken(session, organization_id, new_code):
            raise ConflictError(f"Worker code '{new_code}' is already assigned")

    # Validate work email uniqueness if updated
    if "work_email" in update_dict and update_dict["work_email"] != worker.work_email:
        existing_email = (
            await session.execute(
                select(Worker).where(
                    Worker.organization_id == organization_id,
                    Worker.work_email == update_dict["work_email"],
                    Worker.id != worker.id,
                )
            )
        ).scalar_one_or_none()
        if existing_email:
            raise ConflictError(f"Worker with work email '{update_dict['work_email']}' already exists")

    # Validate manager if updated
    if "manager_id" in update_dict and update_dict["manager_id"] is not None:
        if update_dict["manager_id"] == worker.id:
            raise ValidationFailedError("manager_id", "A worker cannot be their own manager")
        manager = (
            await session.execute(
                select(Worker).where(
                    Worker.organization_id == organization_id,
                    Worker.id == update_dict["manager_id"],
                )
            )
        ).scalar_one_or_none()
        if not manager:
            raise ValidationFailedError("manager_id", f"Manager '{update_dict['manager_id']}' not found in organization")

    # A new designation is a promotion, demotion or correction: it goes through a role change so
    # that someone else approves it and the record of it is kept.
    if "designation" in update_dict and update_dict["designation"] != worker.designation:
        raise ConflictError(
            "Change the designation with a role change, so it is approved and recorded",
            code="ROLE_CHANGE_REQUIRED",
        )
    update_dict.pop("designation", None)

    for field, val in update_dict.items():
        setattr(worker, field, val)

    await session.flush()
    await session.refresh(worker)
    return worker


async def list_workers(
    session: AsyncSession,
    organization_id: uuid.UUID,
    unit_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 25,
    cursor: Optional[str] = None,
) -> tuple[list[dict], PageMeta]:
    stmt = select(Worker).where(Worker.organization_id == organization_id)
    if unit_id:
        stmt = stmt.where(Worker.unit_id == unit_id)
    if status:
        stmt = stmt.where(Worker.status == status)
    if search:
        s = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Worker.first_name.ilike(s),
                Worker.last_name.ilike(s),
                Worker.worker_code.ilike(s),
                Worker.work_email.ilike(s),
                Worker.designation.ilike(s),
            )
        )

    rows, page = await paginate(
        session, stmt, Worker, limit=limit, cursor=cursor, order_by=Worker.created_at, descending=False
    )
    return [_worker_to_response(w) for w in rows], page


async def get_worker_detail(
    session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID
) -> dict:
    worker = (
        await session.execute(
            select(Worker).where(
                Worker.organization_id == organization_id,
                Worker.id == worker_id,
            )
        )
    ).scalar_one_or_none()
    if not worker:
        raise WorkerNotFoundError(str(worker_id))

    data = _worker_to_response(worker)

    # Manager resolution
    if worker.manager_id:
        mgr = (
            await session.execute(
                select(Worker).where(
                    Worker.organization_id == organization_id,
                    Worker.id == worker.manager_id,
                )
            )
        ).scalar_one_or_none()
        if mgr:
            data["manager"] = {
                "id": mgr.id,
                "worker_code": mgr.worker_code,
                "name": f"{mgr.first_name} {mgr.last_name}".strip(),
                "designation": mgr.designation,
            }

    # Direct reports count
    report_count = (
        await session.execute(
            select(func.count(Worker.id)).where(
                Worker.organization_id == organization_id,
                Worker.manager_id == worker.id,
                Worker.status == "active",
            )
        )
    ).scalar_one()
    data["direct_reports_count"] = report_count

    # Timeline events
    timeline_rows = (
        await session.execute(
            select(WorkerTimelineEvent)
            .where(
                WorkerTimelineEvent.organization_id == organization_id,
                WorkerTimelineEvent.worker_id == worker.id,
            )
            .order_by(WorkerTimelineEvent.effective_date.desc(), WorkerTimelineEvent.recorded_at.desc())
        )
    ).scalars().all()
    data["timeline"] = timeline_rows

    return data


async def add_timeline_event(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
    data: TimelineEventCreate,
) -> WorkerTimelineEvent:
    worker = (
        await session.execute(
            select(Worker).where(
                Worker.organization_id == organization_id,
                Worker.id == worker_id,
            )
        )
    ).scalar_one_or_none()
    if not worker:
        raise WorkerNotFoundError(str(worker_id))

    event = WorkerTimelineEvent(
        organization_id=organization_id,
        worker_id=worker.id,
        event_category=data.event_category,
        title=data.title,
        description=data.description,
        effective_date=data.effective_date,  # Supports past back-dating or future dates!
        previous_state=data.previous_state,
        new_state=data.new_state,
    )
    session.add(event)
    await session.flush()
    return event


# --- Creating workers from identity users -------------------------------------------------------

IDENTITY_FETCH_SIZE = 100
# Pages of identity users read for one importable list; most may already be linked.
MAX_IDENTITY_FETCHES = 5

SKIP_NOT_ACTIVE_EMPLOYEE = "not_an_active_employee"
SKIP_ALREADY_LINKED = "already_linked"
SKIP_DUPLICATE_IN_REQUEST = "duplicate_in_request"
SKIP_EMAIL_TAKEN = "work_email_taken"
SKIP_CODE_TAKEN = "worker_code_taken"


async def _worker_code_taken(session: AsyncSession, organization_id: uuid.UUID, code: str) -> bool:
    found = await session.execute(
        select(Worker.id).where(Worker.organization_id == organization_id, Worker.worker_code == code)
    )
    return found.first() is not None


async def _linked_user_ids(session: AsyncSession, organization_id: uuid.UUID, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not user_ids:
        return set()
    rows = await session.execute(
        select(Worker.user_id).where(Worker.organization_id == organization_id, Worker.user_id.in_(user_ids))
    )
    return set(rows.scalars().all())


def _to_importable(employee: IdentityEmployee) -> ImportableUser:
    return ImportableUser(
        user_id=employee.id,
        name=employee.name,
        email=employee.email,
        phone=employee.phone,
        employee_code=employee.employee_code,
        unit_id=employee.home_unit_id,
        manager_user_id=employee.manager_user_id,
    )


def _parse_offset(cursor: Optional[str]) -> int:
    try:
        offset = int(cursor) if cursor else 0
    except ValueError:
        raise ValidationFailedError("cursor", "Malformed cursor") from None
    if offset < 0:
        raise ValidationFailedError("cursor", "Malformed cursor")
    return offset


async def list_importable_users(
    session: AsyncSession,
    identity: IdentityClient,
    organization_id: uuid.UUID,
    search: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> tuple[list[ImportableUser], PageMeta]:
    """
    Identity's active employee users that have no worker yet. Identity pages the users; the ones
    already linked are dropped here, so several identity pages may be read to fill one answer.
    The cursor is the position in identity's list.
    """
    next_offset = _parse_offset(cursor)
    rows: list[ImportableUser] = []

    for _ in range(MAX_IDENTITY_FETCHES):
        page = await identity.list_employees(
            organization_id, search=search, limit=IDENTITY_FETCH_SIZE, offset=next_offset
        )
        linked = await _linked_user_ids(session, organization_id, [employee.id for employee in page.data])
        for position, employee in enumerate(page.data, start=1):
            if employee.id in linked:
                continue
            rows.append(_to_importable(employee))
            if len(rows) == limit:
                has_more = position < len(page.data) or page.has_more
                return rows, _page_meta(next_offset + position, has_more, limit)
        next_offset += len(page.data)
        if not page.has_more:
            return rows, _page_meta(next_offset, False, limit)

    return rows, _page_meta(next_offset, True, limit)


def _page_meta(next_offset: int, has_more: bool, limit: int) -> PageMeta:
    return PageMeta(next_cursor=str(next_offset) if has_more else None, has_more=has_more, limit=limit)


def _split_name(name: str) -> tuple[str, str]:
    first, _, last = name.strip().partition(" ")
    return first, last.strip()


async def import_workers_from_users(
    session: AsyncSession,
    identity: IdentityClient,
    organization_id: uuid.UUID,
    items: list[WorkerImportItem],
) -> tuple[list[Worker], list[WorkerImportSkipped]]:
    """
    Create a worker for each requested identity user. Every user is checked with identity again
    (active, employee type, this organization), so the ids sent by the client are never trusted.
    Users that cannot be imported are reported with a reason; the rest still are.
    """
    skipped: list[WorkerImportSkipped] = []
    unique_items: dict[uuid.UUID, WorkerImportItem] = {}
    for item in items:
        if item.user_id in unique_items:
            skipped.append(WorkerImportSkipped(user_id=item.user_id, reason=SKIP_DUPLICATE_IN_REQUEST))
        else:
            unique_items[item.user_id] = item

    page = await identity.list_employees(
        organization_id, user_ids=list(unique_items), limit=len(unique_items)
    )
    employees = {employee.id: employee for employee in page.data}
    linked = await _linked_user_ids(session, organization_id, list(unique_items))

    created: list[Worker] = []
    for user_id, item in unique_items.items():
        employee = employees.get(user_id)
        if employee is None:
            skipped.append(WorkerImportSkipped(user_id=user_id, reason=SKIP_NOT_ACTIVE_EMPLOYEE))
        elif user_id in linked:
            skipped.append(WorkerImportSkipped(user_id=user_id, reason=SKIP_ALREADY_LINKED))
        elif reason := await _import_one(session, organization_id, employee, item, created):
            skipped.append(WorkerImportSkipped(user_id=user_id, reason=reason))

    await _link_managers(session, organization_id, created, employees)
    return created, skipped


async def _import_one(
    session: AsyncSession,
    organization_id: uuid.UUID,
    employee: IdentityEmployee,
    item: WorkerImportItem,
    created: list[Worker],
) -> Optional[str]:
    """Create one worker and append it to `created`; the reason it was skipped, if it was."""
    email_taken = await session.execute(
        select(Worker.id).where(Worker.organization_id == organization_id, Worker.work_email == employee.email)
    )
    if email_taken.first():
        return SKIP_EMAIL_TAKEN

    explicit_code = (item.worker_code or "").strip() or None
    worker_code = explicit_code or (employee.employee_code or "").strip() or None
    if worker_code and await _worker_code_taken(session, organization_id, worker_code):
        if explicit_code:
            return SKIP_CODE_TAKEN
        worker_code = None  # identity's own code collides; the code can be filled in later

    first_name, last_name = _split_name(employee.name)
    worker = Worker(
        organization_id=organization_id,
        worker_code=worker_code,
        user_id=employee.id,
        first_name=first_name,
        last_name=last_name,
        work_email=employee.email,
        phone=employee.phone,
        unit_id=employee.home_unit_id,
        designation=item.designation.strip(),
        employment_type=item.employment_type,
        status="active",
        date_of_joining=item.date_of_joining,
    )
    try:
        async with session.begin_nested():
            session.add(worker)
            await session.flush()
    except IntegrityError:
        return SKIP_ALREADY_LINKED  # a concurrent import linked this user first

    session.add(
        WorkerTimelineEvent(
            organization_id=organization_id,
            worker_id=worker.id,
            event_category="hire",
            title=f"Joined as {worker.designation}",
            description="Created from an existing user",
            effective_date=worker.date_of_joining,
            new_state={
                "designation": worker.designation,
                "unit_id": str(worker.unit_id) if worker.unit_id else None,
                "source": "identity_import",
            },
        )
    )
    created.append(worker)
    return None


async def _link_managers(
    session: AsyncSession,
    organization_id: uuid.UUID,
    created: list[Worker],
    employees: dict[uuid.UUID, IdentityEmployee],
) -> None:
    """Point each new worker at their manager's worker, when the manager (a user) has one."""
    manager_user_ids = {
        employees[worker.user_id].manager_user_id
        for worker in created
        if worker.user_id and employees[worker.user_id].manager_user_id
    }
    if not manager_user_ids:
        return
    rows = await session.execute(
        select(Worker.user_id, Worker.id).where(
            Worker.organization_id == organization_id, Worker.user_id.in_(manager_user_ids)
        )
    )
    worker_by_user = {user_id: worker_id for user_id, worker_id in rows.all()}
    for worker in created:
        manager_user_id = employees[worker.user_id].manager_user_id if worker.user_id else None
        manager_worker_id = worker_by_user.get(manager_user_id) if manager_user_id else None
        if manager_worker_id and manager_worker_id != worker.id:
            worker.manager_id = manager_worker_id
            await session.flush()
            await session.refresh(worker)  # the update refreshed `updated_at` server-side
