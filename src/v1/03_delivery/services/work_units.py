"""Business logic for the Work units module (work unit types, templates,
work units, milestones, risks and change requests).

Simplification note: creating a work unit from a template is documented as
copying "phases, milestones and packages from the published template
version". The spec types the template version's ``structure`` field as a
bare JSON ``object`` with no published schema, so there is no fixed shape to
copy from. This service accepts an optional, best-effort shape
(``{"phases": [...], "milestones": [...], "packages": [...]}``, each item
using the same field names as the corresponding response schema) and copies
whatever is present; an organization free to shape ``structure`` however it
likes would need a real template-authoring contract, which is out of scope
here.
"""

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    BaselineChangeRequiresCrError,
    ChangeRequestNotFoundError,
    ClientRequiredError,
    DuplicateCodeError,
    InvalidStateTransitionError,
    MilestoneNotFoundError,
    PreconditionRequiredError,
    TemplateNotFoundError,
    TemplateNotPublishedError,
    TemplateVersionNotFoundError,
    VersionConflictError,
    VersionNotDraftError,
    WorkUnitHasOpenItemsError,
    WorkUnitNotFoundError,
    WorkUnitTypeNotFoundError,
)
from models.control_register import ChangeRequest, Closure, Risk
from models.delivery import Deliverable, Milestone, Phase, WorkPackage
from models.financial import WorkBudget
from models.task import Task
from models.work_unit import WorkUnit, WorkUnitMember
from models.work_unit_template import WorkTemplate, WorkTemplateVersion, WorkUnitType
from models.work_unit_tracking import ProgressSnapshot
from schemas.common import Money, PageResponse
from schemas.work_units import (
    ChangeRequestCreate,
    ChangeRequestResponse,
    DeliverableResponse,
    MembersReplace,
    MilestoneAccept,
    MilestoneReject,
    MilestoneResponse,
    MilestoneSubmit,
    MilestoneUpdate,
    ProgressResponse,
    RiskCreate,
    RiskResponse,
    WorkTemplateResponse,
    WorkTemplateVersionCreate,
    WorkTemplateVersionResponse,
    WorkUnitCreate,
    WorkUnitResponse,
    WorkUnitStatusChange,
    WorkUnitSummaryResponse,
    WorkUnitTypeResponse,
    WorkUnitUpdate,
)
from services.pagination import paginate_by_id
from services.refs import client_ref, unit_ref, user_ref, vertical_ref

WORK_UNIT_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"planned", "active", "cancelled"},
    "planned": {"active", "on_hold", "cancelled"},
    "active": {"on_hold", "completed", "cancelled"},
    "on_hold": {"active", "cancelled"},
    "completed": {"closed"},
    "closed": set(),
    "cancelled": set(),
}


def _check_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


# --- Work unit types & templates -----------------------------------------


async def list_work_unit_types(
    session: AsyncSession, org_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[WorkUnitTypeResponse]:
    query = select(WorkUnitType).where(WorkUnitType.organization_id == org_id)
    rows, page = await paginate_by_id(session, query, WorkUnitType, limit, cursor)
    return PageResponse(data=[WorkUnitTypeResponse.model_validate(r) for r in rows], page=page)


async def list_templates(
    session: AsyncSession,
    org_id: uuid.UUID,
    vertical_id: Optional[uuid.UUID],
    status: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[WorkTemplateResponse]:
    query = select(WorkTemplate).where(WorkTemplate.organization_id == org_id)
    if vertical_id is not None:
        query = query.where(WorkTemplate.vertical_id == vertical_id)
    if status is not None:
        query = query.where(WorkTemplate.status == status)
    rows, page = await paginate_by_id(session, query, WorkTemplate, limit, cursor)
    data = [await _build_template_response(session, t) for t in rows]
    return PageResponse(data=data, page=page)


async def _get_template_by_code(session: AsyncSession, org_id: uuid.UUID, template_code: str) -> WorkTemplate:
    res = await session.execute(
        select(WorkTemplate).where(WorkTemplate.organization_id == org_id, WorkTemplate.code == template_code)
    )
    template = res.scalars().first()
    if not template:
        raise TemplateNotFoundError(template_code)
    return template


async def _build_template_response(session: AsyncSession, template: WorkTemplate) -> WorkTemplateResponse:
    published_version_no: Optional[int] = None
    res = await session.execute(
        select(WorkTemplateVersion)
        .where(WorkTemplateVersion.template_id == template.id, WorkTemplateVersion.status == "published")
        .order_by(WorkTemplateVersion.version_no.desc())
    )
    published = res.scalars().first()
    if published:
        published_version_no = published.version_no

    unit_type = await session.get(WorkUnitType, template.work_unit_type_id)
    return WorkTemplateResponse(
        id=template.id,
        code=template.code,
        name=template.name,
        vertical=vertical_ref(template.vertical_id),
        work_unit_type_code=unit_type.code if unit_type else "",
        status=template.status,
        published_version_no=published_version_no,
    )


async def create_template_version(
    session: AsyncSession, org_id: uuid.UUID, template_code: str, data: WorkTemplateVersionCreate
) -> WorkTemplateVersionResponse:
    template = await _get_template_by_code(session, org_id, template_code)

    res = await session.execute(
        select(WorkTemplateVersion.version_no)
        .where(WorkTemplateVersion.template_id == template.id)
        .order_by(WorkTemplateVersion.version_no.desc())
    )
    last_version_no = res.scalars().first() or 0

    version = WorkTemplateVersion(
        template_id=template.id,
        version_no=last_version_no + 1,
        structure=data.structure,
        workflow_definition_code=data.workflow_definition_code,
        status="draft",
    )
    session.add(version)
    await session.flush()
    return _to_template_version_response(version, template.code)


async def publish_template_version(
    session: AsyncSession, org_id: uuid.UUID, template_code: str, version_no: int, if_match: Optional[str]
) -> WorkTemplateVersionResponse:
    template = await _get_template_by_code(session, org_id, template_code)
    version = await _get_template_version(session, template, version_no)

    if if_match is None:
        raise PreconditionRequiredError()

    if version.status != "draft":
        raise VersionNotDraftError(version_no)

    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    template.status = "active"
    await session.flush()
    return _to_template_version_response(version, template.code)


async def _get_template_version(session: AsyncSession, template: WorkTemplate, version_no: int) -> WorkTemplateVersion:
    res = await session.execute(
        select(WorkTemplateVersion).where(
            WorkTemplateVersion.template_id == template.id, WorkTemplateVersion.version_no == version_no
        )
    )
    version = res.scalars().first()
    if not version:
        raise TemplateVersionNotFoundError(version_no)
    return version


def _to_template_version_response(version: WorkTemplateVersion, template_code: str) -> WorkTemplateVersionResponse:
    return WorkTemplateVersionResponse(
        id=version.id,
        template_code=template_code,
        version_no=version.version_no,
        status=version.status,
        workflow_definition_code=version.workflow_definition_code,
        structure=version.structure or {},
        published_at=version.published_at,
    )


# --- Work units --------------------------------------------------------


async def _build_work_unit_response(session: AsyncSession, work_unit: WorkUnit) -> WorkUnitResponse:
    unit_type = await session.get(WorkUnitType, work_unit.work_unit_type_id)
    template_response: WorkTemplateResponse
    if work_unit.template_version_id is not None:
        version = await session.get(WorkTemplateVersion, work_unit.template_version_id)
        template = await session.get(WorkTemplate, version.template_id) if version else None
        template_response = await _build_template_response(session, template) if template else _empty_template_response()
    else:
        template_response = _empty_template_response()

    budget_row = (
        (await session.execute(select(WorkBudget).where(WorkBudget.work_unit_id == work_unit.id)))
        .scalars()
        .first()
    )
    budget = (
        {
            "planned": Money(amount=budget_row.planned_amount, currency=budget_row.currency).model_dump(mode="json"),
            "approved": Money(amount=budget_row.approved_amount, currency=budget_row.currency).model_dump(mode="json"),
        }
        if budget_row
        else {}
    )

    return WorkUnitResponse(
        id=work_unit.id,
        code=work_unit.code,
        name=work_unit.name,
        objective=work_unit.objective,
        type=WorkUnitTypeResponse.model_validate(unit_type) if unit_type else _empty_type_response(),
        template=template_response,
        status=work_unit.status,
        priority=work_unit.priority,
        health=work_unit.health,
        progress_pct=float(work_unit.progress_pct),
        owning_unit=unit_ref(work_unit.owning_unit_id, "Owning Unit"),
        vertical=vertical_ref(work_unit.vertical_id, "Vertical"),
        client=client_ref(work_unit.client_id),
        contract={"id": str(work_unit.contract_id)} if work_unit.contract_id else None,
        manager=user_ref(work_unit.manager_user_id, "Manager"),
        planned_start=work_unit.planned_start,
        planned_end=work_unit.planned_end,
        actual_start=work_unit.actual_start,
        actual_end=work_unit.actual_end,
        billable=work_unit.billable,
        budget=budget,
        workflow_instance_id=None,
        attributes=work_unit.attributes or {},
        version=work_unit.version,
        created_at=work_unit.created_at,
        updated_at=work_unit.updated_at,
    )


def _empty_type_response() -> WorkUnitTypeResponse:
    return WorkUnitTypeResponse(id=uuid.uuid4(), code="", name="", category="internal_project", requires_client=False)


def _empty_template_response() -> WorkTemplateResponse:
    return WorkTemplateResponse(id=uuid.uuid4(), code="", name="", work_unit_type_code="", status="active")


async def list_work_units(
    session: AsyncSession,
    org_id: uuid.UUID,
    status: Optional[str],
    owning_unit_id: Optional[uuid.UUID],
    vertical_id: Optional[uuid.UUID],
    client_id: Optional[uuid.UUID],
    manager_user_id: Optional[uuid.UUID],
    health: Optional[str],
    q: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[WorkUnitResponse]:
    query = select(WorkUnit).where(WorkUnit.organization_id == org_id)
    if status is not None:
        query = query.where(WorkUnit.status == status)
    if owning_unit_id is not None:
        query = query.where(WorkUnit.owning_unit_id == owning_unit_id)
    if vertical_id is not None:
        query = query.where(WorkUnit.vertical_id == vertical_id)
    if client_id is not None:
        query = query.where(WorkUnit.client_id == client_id)
    if manager_user_id is not None:
        query = query.where(WorkUnit.manager_user_id == manager_user_id)
    if health is not None:
        query = query.where(WorkUnit.health == health)
    if q:
        term = f"%{q}%"
        query = query.where((WorkUnit.name.ilike(term)) | (WorkUnit.code.ilike(term)))

    rows, page = await paginate_by_id(session, query, WorkUnit, limit, cursor)
    data = [await _build_work_unit_response(session, w) for w in rows]
    return PageResponse(data=data, page=page)


async def create_work_unit(session: AsyncSession, org_id: uuid.UUID, data: WorkUnitCreate) -> WorkUnitResponse:
    template = await _get_template_by_code(session, org_id, data.template_code)

    if data.template_version_no is not None:
        version = await _get_template_version(session, template, data.template_version_no)
        if version.status != "published":
            raise TemplateNotPublishedError()
    else:
        res = await session.execute(
            select(WorkTemplateVersion)
            .where(WorkTemplateVersion.template_id == template.id, WorkTemplateVersion.status == "published")
            .order_by(WorkTemplateVersion.version_no.desc())
        )
        version = res.scalars().first()
        if not version:
            raise TemplateNotPublishedError()

    unit_type = await session.get(WorkUnitType, template.work_unit_type_id)
    if unit_type and unit_type.requires_client and data.client_id is None:
        raise ClientRequiredError()

    code = await _generate_work_unit_code(session, org_id)
    existing = await session.execute(select(WorkUnit).where(WorkUnit.organization_id == org_id, WorkUnit.code == code))
    if existing.scalars().first():
        raise DuplicateCodeError(code)

    work_unit = WorkUnit(
        organization_id=org_id,
        code=code,
        name=data.name,
        objective=data.objective,
        work_unit_type_id=template.work_unit_type_id,
        template_version_id=version.id,
        vertical_id=data.vertical_id,
        owning_unit_id=data.owning_unit_id,
        client_id=data.client_id,
        contract_id=data.contract_id,
        manager_user_id=data.manager_user_id,
        planned_start=data.planned_start,
        planned_end=data.planned_end,
        status="planned",
        priority=data.priority or "medium",
        billable=data.billable if data.billable is not None else True,
        attributes=data.attributes or {},
        version=1,
    )
    session.add(work_unit)
    await session.flush()

    await _copy_template_structure(session, work_unit, version.structure or {})

    return await _build_work_unit_response(session, work_unit)


async def _generate_work_unit_code(session: AsyncSession, org_id: uuid.UUID) -> str:
    year = datetime.now(timezone.utc).year
    res = await session.execute(select(WorkUnit).where(WorkUnit.organization_id == org_id))
    count = len(res.scalars().all())
    return f"WU-{year}-{count + 1:04d}"


async def _copy_template_structure(session: AsyncSession, work_unit: WorkUnit, structure: dict) -> None:
    """Best-effort copy of phases/milestones/packages from the template
    version's freeform ``structure`` JSON. See module docstring."""

    phase_id_by_seq: dict[int, uuid.UUID] = {}
    for item in structure.get("phases", []) if isinstance(structure, dict) else []:
        phase = Phase(
            work_unit_id=work_unit.id,
            seq=item.get("seq", 0),
            name=item.get("name", "Phase"),
            planned_start=item.get("planned_start"),
            planned_end=item.get("planned_end"),
            status="pending",
        )
        session.add(phase)
        await session.flush()
        phase_id_by_seq[phase.seq] = phase.id

    for item in structure.get("milestones", []) if isinstance(structure, dict) else []:
        session.add(
            Milestone(
                work_unit_id=work_unit.id,
                phase_id=phase_id_by_seq.get(item.get("phase_seq")),
                code=item.get("code", f"MS-{item.get('seq', 0)}"),
                name=item.get("name", "Milestone"),
                seq=item.get("seq", 0),
                weight=item.get("weight", 0),
                planned_date=item.get("planned_date") or work_unit.planned_end,
                is_billing_milestone=item.get("is_billing_milestone", False),
                requires_client_acceptance=item.get("requires_client_acceptance", False),
                status="pending",
            )
        )

    for item in structure.get("packages", []) if isinstance(structure, dict) else []:
        session.add(
            WorkPackage(
                work_unit_id=work_unit.id,
                phase_id=phase_id_by_seq.get(item.get("phase_seq")),
                name=item.get("name", "Work package"),
                estimated_hours=item.get("estimated_hours", 0),
                status="planned",
            )
        )

    await session.flush()


async def _get_work_unit(session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID) -> WorkUnit:
    res = await session.execute(
        select(WorkUnit).where(WorkUnit.id == work_unit_id, WorkUnit.organization_id == org_id)
    )
    work_unit = res.scalars().first()
    if not work_unit:
        raise WorkUnitNotFoundError(str(work_unit_id))
    return work_unit


async def get_work_unit(session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID) -> WorkUnitResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)
    return await _build_work_unit_response(session, work_unit)


async def update_work_unit(
    session: AsyncSession,
    org_id: uuid.UUID,
    work_unit_id: uuid.UUID,
    data: WorkUnitUpdate,
    if_match: Optional[str],
) -> WorkUnitResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)
    _check_if_match(if_match, work_unit.version)

    if data.planned_end is not None and work_unit.status not in ("draft", "planned"):
        raise BaselineChangeRequiresCrError()

    if data.name is not None:
        work_unit.name = data.name
    if data.objective is not None:
        work_unit.objective = data.objective
    if data.manager_user_id is not None:
        work_unit.manager_user_id = data.manager_user_id
    if data.planned_end is not None:
        work_unit.planned_end = data.planned_end
    if data.priority is not None:
        work_unit.priority = data.priority
    if data.attributes is not None:
        merged = dict(work_unit.attributes or {})
        merged.update(data.attributes)
        work_unit.attributes = merged

    work_unit.version += 1
    await session.flush()
    return await _build_work_unit_response(session, work_unit)


async def change_work_unit_status(
    session: AsyncSession,
    org_id: uuid.UUID,
    work_unit_id: uuid.UUID,
    data: WorkUnitStatusChange,
    if_match: Optional[str],
) -> WorkUnitResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)
    _check_if_match(if_match, work_unit.version)

    allowed = WORK_UNIT_TRANSITIONS.get(work_unit.status, set())
    if data.to_status not in allowed:
        raise InvalidStateTransitionError(work_unit.status, data.to_status)

    if data.to_status == "completed":
        await _require_all_milestones_completed(session, work_unit.id)

    if data.to_status == "closed":
        await _require_no_open_items(session, work_unit.id)
        session.add(Closure(work_unit_id=work_unit.id, summary=data.reason, closed_by=None))

    work_unit.status = data.to_status
    if data.to_status == "active" and work_unit.actual_start is None:
        work_unit.actual_start = date.today()
    if data.to_status in ("completed", "closed") and work_unit.actual_end is None:
        work_unit.actual_end = date.today()

    work_unit.version += 1
    await session.flush()
    return await _build_work_unit_response(session, work_unit)


async def _require_all_milestones_completed(session: AsyncSession, work_unit_id: uuid.UUID) -> None:
    res = await session.execute(
        select(Milestone).where(Milestone.work_unit_id == work_unit_id, Milestone.status != "completed")
    )
    if res.scalars().first():
        raise WorkUnitHasOpenItemsError()


async def _require_no_open_items(session: AsyncSession, work_unit_id: uuid.UUID) -> None:
    open_tasks = await session.execute(
        select(Task).where(Task.work_unit_id == work_unit_id, Task.status.notin_(["done", "cancelled"]))
    )
    if open_tasks.scalars().first():
        raise WorkUnitHasOpenItemsError()

    open_risks = await session.execute(
        select(Risk).where(Risk.work_unit_id == work_unit_id, Risk.status.notin_(["closed", "occurred"]))
    )
    if open_risks.scalars().first():
        raise WorkUnitHasOpenItemsError()

    open_crs = await session.execute(
        select(ChangeRequest).where(
            ChangeRequest.work_unit_id == work_unit_id,
            ChangeRequest.status.notin_(["implemented", "rejected", "withdrawn"]),
        )
    )
    if open_crs.scalars().first():
        raise WorkUnitHasOpenItemsError()

    await _require_all_milestones_completed(session, work_unit_id)


async def get_work_unit_summary(session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID) -> WorkUnitSummaryResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)
    work_unit_response = await _build_work_unit_response(session, work_unit)

    phases_res = await session.execute(select(Phase).where(Phase.work_unit_id == work_unit_id).order_by(Phase.seq))
    phases = [
        {
            "id": str(p.id),
            "seq": p.seq,
            "name": p.name,
            "status": p.status,
            "planned_start": p.planned_start.isoformat() if p.planned_start else None,
            "planned_end": p.planned_end.isoformat() if p.planned_end else None,
        }
        for p in phases_res.scalars().all()
    ]

    milestones = await _list_milestone_responses(session, work_unit_id)

    tasks_res = await session.execute(select(Task).where(Task.work_unit_id == work_unit_id))
    tasks_by_status: dict[str, int] = {}
    for task in tasks_res.scalars().all():
        tasks_by_status[task.status] = tasks_by_status.get(task.status, 0) + 1

    risks_open_res = await session.execute(
        select(Risk).where(Risk.work_unit_id == work_unit_id, Risk.status.notin_(["closed", "occurred"]))
    )
    risks_open = len(risks_open_res.scalars().all())

    crs_open_res = await session.execute(
        select(ChangeRequest).where(
            ChangeRequest.work_unit_id == work_unit_id,
            ChangeRequest.status.notin_(["implemented", "rejected", "withdrawn"]),
        )
    )
    pending_approvals = len(crs_open_res.scalars().all())

    return WorkUnitSummaryResponse(
        work_unit=work_unit_response,
        phases=phases,
        milestones=milestones,
        tasks_by_status=tasks_by_status,
        sla={},
        risks_open=risks_open,
        issues_open=0,
        pending_approvals=pending_approvals,
    )


# --- Milestones ----------------------------------------------------------


async def _list_milestone_responses(session: AsyncSession, work_unit_id: uuid.UUID) -> list[MilestoneResponse]:
    res = await session.execute(select(Milestone).where(Milestone.work_unit_id == work_unit_id).order_by(Milestone.seq))
    milestones = res.scalars().all()
    return [await _build_milestone_response(session, m) for m in milestones]


async def _build_milestone_response(session: AsyncSession, milestone: Milestone) -> MilestoneResponse:
    res = await session.execute(select(Deliverable).where(Deliverable.milestone_id == milestone.id))
    deliverables = [DeliverableResponse.model_validate(d) for d in res.scalars().all()]
    return MilestoneResponse(
        id=milestone.id,
        code=milestone.code,
        name=milestone.name,
        phase_id=milestone.phase_id,
        seq=milestone.seq,
        weight=float(milestone.weight),
        planned_date=milestone.planned_date,
        forecast_date=milestone.forecast_date,
        actual_date=milestone.actual_date,
        is_billing_milestone=milestone.is_billing_milestone,
        requires_client_acceptance=milestone.requires_client_acceptance,
        status=milestone.status,
        deliverables=deliverables,
    )


async def list_milestones(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[MilestoneResponse]:
    await _get_work_unit(session, org_id, work_unit_id)
    query = select(Milestone).where(Milestone.work_unit_id == work_unit_id)
    rows, page = await paginate_by_id(session, query, Milestone, limit, cursor)
    data = [await _build_milestone_response(session, m) for m in rows]
    return PageResponse(data=data, page=page)


async def _get_milestone(session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID) -> Milestone:
    milestone = await session.get(Milestone, milestone_id)
    if not milestone:
        raise MilestoneNotFoundError(str(milestone_id))
    # Ownership check via the parent work unit's organization.
    await _get_work_unit(session, org_id, milestone.work_unit_id)
    return milestone


MILESTONE_ETAG = "1"  # Milestone has no version column; see report's concurrency note.


async def update_milestone(
    session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID, data: MilestoneUpdate, if_match: Optional[str]
) -> MilestoneResponse:
    milestone = await _get_milestone(session, org_id, milestone_id)
    if if_match is None:
        raise PreconditionRequiredError()

    if data.planned_date is not None and milestone.status != "pending":
        raise BaselineChangeRequiresCrError()

    if data.forecast_date is not None:
        milestone.forecast_date = data.forecast_date
    if data.planned_date is not None:
        milestone.planned_date = data.planned_date

    await session.flush()
    return await _build_milestone_response(session, milestone)


async def submit_milestone(
    session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID, data: MilestoneSubmit, if_match: Optional[str]
) -> MilestoneResponse:
    milestone = await _get_milestone(session, org_id, milestone_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if milestone.status not in ("pending", "in_progress", "rejected"):
        raise InvalidStateTransitionError(milestone.status, "submitted")

    for document_id in data.deliverable_document_ids:
        session.add(Deliverable(milestone_id=milestone.id, name="Deliverable", document_id=document_id, status="submitted"))

    milestone.status = "submitted"
    await session.flush()
    return await _build_milestone_response(session, milestone)


async def accept_milestone(
    session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID, data: MilestoneAccept, if_match: Optional[str]
) -> MilestoneResponse:
    milestone = await _get_milestone(session, org_id, milestone_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if milestone.status != "submitted":
        raise InvalidStateTransitionError(milestone.status, "accepted")

    milestone.status = "completed" if not milestone.requires_client_acceptance else "accepted"
    milestone.actual_date = data.accepted_on

    deliverables_res = await session.execute(select(Deliverable).where(Deliverable.milestone_id == milestone.id))
    for deliverable in deliverables_res.scalars().all():
        deliverable.status = "accepted"
        deliverable.accepted_by = data.accepted_by_name
        deliverable.accepted_at = datetime.now(timezone.utc)

    await session.flush()
    return await _build_milestone_response(session, milestone)


async def reject_milestone(
    session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID, data: MilestoneReject, if_match: Optional[str]
) -> MilestoneResponse:
    milestone = await _get_milestone(session, org_id, milestone_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if milestone.status != "submitted":
        raise InvalidStateTransitionError(milestone.status, "rejected")

    milestone.status = "rejected"
    await session.flush()
    return await _build_milestone_response(session, milestone)


# --- Risks & change requests ------------------------------------------------


async def create_risk(session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, data: RiskCreate) -> RiskResponse:
    await _get_work_unit(session, org_id, work_unit_id)
    risk = Risk(
        work_unit_id=work_unit_id,
        title=data.title,
        probability=data.probability,
        impact=data.impact,
        score=data.probability * data.impact,
        mitigation=data.mitigation,
        owner_user_id=data.owner_user_id,
        status="identified",
    )
    session.add(risk)
    await session.flush()
    return _to_risk_response(risk)


def _to_risk_response(risk: Risk) -> RiskResponse:
    return RiskResponse(
        id=risk.id,
        title=risk.title,
        probability=risk.probability,
        impact=risk.impact,
        score=risk.score,
        mitigation=risk.mitigation,
        owner=user_ref(risk.owner_user_id, "Risk Owner"),
        status="open" if risk.status == "identified" else risk.status,
    )


async def create_change_request(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, data: ChangeRequestCreate
) -> ChangeRequestResponse:
    await _get_work_unit(session, org_id, work_unit_id)
    res = await session.execute(select(ChangeRequest).where(ChangeRequest.work_unit_id == work_unit_id))
    seq = len(res.scalars().all()) + 1
    cr = ChangeRequest(
        work_unit_id=work_unit_id,
        cr_no=f"CR-{seq:03d}",
        title=data.title,
        reason=data.reason,
        scope_impact=data.scope_impact,
        schedule_impact_days=data.schedule_impact_days,
        cost_impact=data.cost_impact.amount,
        status="draft",
        amends_contract=data.amends_contract,
    )
    session.add(cr)
    await session.flush()
    return _to_change_request_response(cr)


def _to_change_request_response(cr: ChangeRequest) -> ChangeRequestResponse:
    return ChangeRequestResponse(
        id=cr.id,
        cr_no=cr.cr_no,
        title=cr.title,
        reason=cr.reason or "",
        scope_impact=cr.scope_impact or "",
        schedule_impact_days=cr.schedule_impact_days,
        cost_impact=Money(amount=cr.cost_impact),
        status=cr.status,
        approval_request_id=cr.approval_request_id,
        amends_contract=cr.amends_contract,
    )


async def submit_change_request(
    session: AsyncSession, org_id: uuid.UUID, change_request_id: uuid.UUID, if_match: Optional[str]
) -> ChangeRequestResponse:
    cr = await session.get(ChangeRequest, change_request_id)
    if not cr:
        raise ChangeRequestNotFoundError(str(change_request_id))
    await _get_work_unit(session, org_id, cr.work_unit_id)

    if if_match is None:
        raise PreconditionRequiredError()
    if cr.status != "draft":
        raise InvalidStateTransitionError(cr.status, "submitted")

    cr.status = "submitted"
    await session.flush()
    return _to_change_request_response(cr)


# --- Members ---------------------------------------------------------------


async def replace_members(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, data: MembersReplace, if_match: Optional[str]
) -> WorkUnitResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)
    _check_if_match(if_match, work_unit.version)

    existing_res = await session.execute(select(WorkUnitMember).where(WorkUnitMember.work_unit_id == work_unit_id))
    for member in existing_res.scalars().all():
        await session.delete(member)
    await session.flush()

    today = date.today()
    for member_input in data.members:
        session.add(
            WorkUnitMember(
                work_unit_id=work_unit_id,
                user_id=member_input.user_id,
                member_role=member_input.member_role,
                allocation_pct=member_input.allocation_pct if member_input.allocation_pct is not None else 100.0,
                valid_from=today,
            )
        )

    work_unit.version += 1
    await session.flush()
    return await _build_work_unit_response(session, work_unit)


# --- Progress --------------------------------------------------------------


async def get_progress(session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID) -> ProgressResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)

    res = await session.execute(
        select(ProgressSnapshot)
        .where(ProgressSnapshot.work_unit_id == work_unit_id)
        .order_by(ProgressSnapshot.as_of.desc())
    )
    snapshot = res.scalars().first()

    trend_res = await session.execute(
        select(ProgressSnapshot)
        .where(ProgressSnapshot.work_unit_id == work_unit_id)
        .order_by(ProgressSnapshot.as_of.asc())
        .limit(12)
    )
    trend = [
        {"as_of": s.as_of.isoformat(), "planned_pct": float(s.planned_pct), "actual_pct": float(s.actual_pct)}
        for s in trend_res.scalars().all()
    ]

    if snapshot:
        return ProgressResponse(
            as_of=snapshot.as_of,
            planned_pct=float(snapshot.planned_pct),
            actual_pct=float(snapshot.actual_pct),
            spi=float(snapshot.spi) if snapshot.spi is not None else 1.0,
            cpi=float(snapshot.cpi) if snapshot.cpi is not None else 1.0,
            health={
                "overall": snapshot.health_overall,
                "schedule": snapshot.health_schedule,
                "cost": snapshot.health_cost,
                "resource": snapshot.health_resource,
                "risk": snapshot.health_risk,
            },
            trend=trend,
        )

    # No snapshot recorded yet: fall back to the work unit's own progress_pct.
    return ProgressResponse(
        as_of=date.today(),
        planned_pct=0.0,
        actual_pct=float(work_unit.progress_pct),
        spi=1.0,
        cpi=1.0,
        health={"overall": work_unit.health},
        trend=trend,
    )
