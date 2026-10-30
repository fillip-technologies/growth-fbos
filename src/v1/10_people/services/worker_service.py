import uuid
from datetime import date
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.worker import Worker, WorkerDocument, WorkerTimelineEvent
from schemas.common import PageMeta
from schemas.worker import (
    TimelineEventCreate,
    WorkerCreate,
    WorkerDetailResponse,
    WorkerResponse,
    WorkerUpdate,
)
from services.codes import next_worker_code
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
        "bank_name": w.bank_name,

        "bank_account_no": w.bank_account_no,
        "ifsc_code": w.ifsc_code,
        "tax_id": w.tax_id,
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
        bank_name=data.bank_name,
        bank_account_no=data.bank_account_no,
        ifsc_code=data.ifsc_code,
        tax_id=data.tax_id,
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

    # Check for designation change to record timeline event
    if "designation" in update_dict and update_dict["designation"] != worker.designation:
        prev_desig = worker.designation
        new_desig = update_dict["designation"]
        timeline_event = WorkerTimelineEvent(
            organization_id=organization_id,
            worker_id=worker.id,
            event_category="promotion",
            title=f"Role changed from {prev_desig} to {new_desig}",
            effective_date=date.today(),
            previous_state={"designation": prev_desig},
            new_state={"designation": new_desig},
        )
        session.add(timeline_event)

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
        session, stmt, Worker, limit=limit, cursor=cursor, order_by=Worker.worker_code, descending=False
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
