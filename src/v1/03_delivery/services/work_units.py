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

List responses load related rows (types, templates, budgets, deliverables) for the whole
page in one query each, never one query per row.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    BaselineChangeRequiresCrError,
    BuiltInReadOnlyError,
    ChangeRequestNotFoundError,
    ClientRequiredError,
    DuplicateCodeError,
    InvalidStateTransitionError,
    MilestoneNotFoundError,
    PhaseNotFoundError,
    PreconditionRequiredError,
    RiskNotFoundError,
    TemplateNotFoundError,
    TemplateNotPublishedError,
    TemplateVersionNotFoundError,
    ValidationFailedError,
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
from models.work_unit_tracking import ProgressSnapshot, StatusHistory
from schemas.common import Money, PageResponse, SubjectRefInput
from schemas.work_units import (
    ChangeRequestApprove,
    ChangeRequestCreate,
    ChangeRequestResponse,
    DeliverableResponse,
    MemberResponse,
    MembersReplace,
    MilestoneAccept,
    MilestoneCreate,
    MilestoneReject,
    MilestoneResponse,
    MilestoneSubmit,
    MilestoneUpdate,
    ProgressResponse,
    RiskCreate,
    RiskResponse,
    RiskUpdate,
    WorkTemplateCreate,
    WorkTemplateResponse,
    WorkTemplateVersionCreate,
    WorkTemplateVersionResponse,
    WorkUnitCreate,
    WorkUnitResponse,
    WorkUnitStatusChange,
    WorkUnitSummaryResponse,
    WorkUnitTypeCreate,
    WorkUnitTypeResponse,
    WorkUnitTypeUpdate,
    WorkUnitUpdate,
)
from schemas.workflows import WorkflowInstanceStart
from services import workflow_instances
from services.codes import next_change_request_no, next_work_unit_code
from services.pagination import paginate
from services.refs import client_ref, unit_ref, user_ref, vertical_ref
from services.tasks import WORK_UNIT_SUBJECT, own_tasks

WORK_UNIT_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"planned", "active", "cancelled"},
    "planned": {"active", "on_hold", "cancelled"},
    "active": {"on_hold", "completed", "cancelled"},
    "on_hold": {"active", "cancelled"},
    "completed": {"closed"},
    "closed": set(),
    "cancelled": set(),
}
_CLOSED_RISK_STATUSES = ("closed", "occurred")
_CLOSED_CHANGE_REQUEST_STATUSES = ("implemented", "rejected", "withdrawn")


def _check_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


# --- Work unit types & templates -----------------------------------------


def _visible_types(org_id: uuid.UUID):
    """The organization's own work unit types plus the built-in ones every organization shares."""
    return or_(WorkUnitType.organization_id == org_id, WorkUnitType.organization_id.is_(None))


async def _find_work_unit_type(session: AsyncSession, org_id: uuid.UUID, code: str) -> WorkUnitType:
    unit_type = (
        await session.execute(select(WorkUnitType).where(_visible_types(org_id), WorkUnitType.code == code))
    ).scalars().first()
    if not unit_type:
        raise WorkUnitTypeNotFoundError(code)
    return unit_type


async def list_work_unit_types(
    session: AsyncSession, org_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[WorkUnitTypeResponse]:
    query = select(WorkUnitType).where(_visible_types(org_id))
    rows, page = await paginate(session, query, WorkUnitType, limit, cursor, order_by=WorkUnitType.code)
    return PageResponse(data=[_work_unit_type_response(r) for r in rows], page=page)


def _work_unit_type_response(unit_type: WorkUnitType) -> WorkUnitTypeResponse:
    return WorkUnitTypeResponse(
        id=unit_type.id,
        code=unit_type.code,
        name=unit_type.name,
        category=unit_type.category,
        requires_client=unit_type.requires_client,
        built_in=unit_type.organization_id is None,
    )


async def create_work_unit_type(
    session: AsyncSession, org_id: uuid.UUID, data: WorkUnitTypeCreate
) -> WorkUnitTypeResponse:
    # A code may exist once among the organization's types and the built-ins, so a lookup
    # by code always finds exactly one type.
    taken = (await session.execute(select(WorkUnitType.id).where(_visible_types(org_id), WorkUnitType.code == data.code))).first()
    if taken:
        raise DuplicateCodeError(data.code)
    unit_type = WorkUnitType(organization_id=org_id, **data.model_dump())
    session.add(unit_type)
    await session.flush()
    return _work_unit_type_response(unit_type)


async def update_work_unit_type(
    session: AsyncSession, org_id: uuid.UUID, type_id: uuid.UUID, data: WorkUnitTypeUpdate
) -> WorkUnitTypeResponse:
    unit_type = (
        await session.execute(select(WorkUnitType).where(_visible_types(org_id), WorkUnitType.id == type_id))
    ).scalars().first()
    if not unit_type:
        raise WorkUnitTypeNotFoundError(str(type_id))
    if unit_type.organization_id is None:
        raise BuiltInReadOnlyError(unit_type.code)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(unit_type, field, value)
    await session.flush()
    return _work_unit_type_response(unit_type)


async def create_template(session: AsyncSession, org_id: uuid.UUID, data: WorkTemplateCreate) -> WorkTemplateResponse:
    taken = (
        await session.execute(
            select(WorkTemplate.id).where(WorkTemplate.organization_id == org_id, WorkTemplate.code == data.code)
        )
    ).first()
    if taken:
        raise DuplicateCodeError(data.code)
    unit_type = await _find_work_unit_type(session, org_id, data.work_unit_type_code)
    template = WorkTemplate(
        organization_id=org_id, work_unit_type_id=unit_type.id, vertical_id=data.vertical_id,
        code=data.code, name=data.name, status="active",
    )
    session.add(template)
    await session.flush()
    return (await _template_responses(session, [template]))[0]


async def list_template_versions(
    session: AsyncSession, org_id: uuid.UUID, template_code: str, limit: int, cursor: Optional[str]
) -> PageResponse[WorkTemplateVersionResponse]:
    template = await _get_template_by_code(session, org_id, template_code)
    query = select(WorkTemplateVersion).where(WorkTemplateVersion.template_id == template.id)
    rows, page = await paginate(
        session, query, WorkTemplateVersion, limit, cursor, order_by=WorkTemplateVersion.version_no, descending=True
    )
    return PageResponse(data=[_to_template_version_response(v, template.code) for v in rows], page=page)


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
    rows, page = await paginate(session, query, WorkTemplate, limit, cursor, order_by=WorkTemplate.code)
    return PageResponse(data=await _template_responses(session, rows), page=page)


async def _get_template_by_code(session: AsyncSession, org_id: uuid.UUID, template_code: str) -> WorkTemplate:
    # Templates are always the organization's own: nothing global can be versioned from here.
    res = await session.execute(
        select(WorkTemplate).where(WorkTemplate.organization_id == org_id, WorkTemplate.code == template_code)
    )
    template = res.scalars().first()
    if not template:
        raise TemplateNotFoundError(template_code)
    return template


async def _template_responses(session: AsyncSession, templates: list[WorkTemplate]) -> list[WorkTemplateResponse]:
    if not templates:
        return []
    type_codes = dict(
        (
            await session.execute(
                select(WorkUnitType.id, WorkUnitType.code).where(
                    WorkUnitType.id.in_({t.work_unit_type_id for t in templates})
                )
            )
        ).all()
    )
    published_version_nos = dict(
        (
            await session.execute(
                select(WorkTemplateVersion.template_id, func.max(WorkTemplateVersion.version_no))
                .where(
                    WorkTemplateVersion.template_id.in_({t.id for t in templates}),
                    WorkTemplateVersion.status == "published",
                )
                .group_by(WorkTemplateVersion.template_id)
            )
        ).all()
    )
    return [
        WorkTemplateResponse(
            id=template.id,
            code=template.code,
            name=template.name,
            vertical=vertical_ref(template.vertical_id),
            work_unit_type_code=type_codes[template.work_unit_type_id],
            status=template.status,
            published_version_no=published_version_nos.get(template.id),
        )
        for template in templates
    ]


async def create_template_version(
    session: AsyncSession, org_id: uuid.UUID, template_code: str, data: WorkTemplateVersionCreate
) -> WorkTemplateVersionResponse:
    template = await _get_template_by_code(session, org_id, template_code)

    res = await session.execute(
        select(func.max(WorkTemplateVersion.version_no)).where(WorkTemplateVersion.template_id == template.id)
    )
    last_version_no = res.scalar_one() or 0

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


async def _published_version(
    session: AsyncSession, template: WorkTemplate, version_no: Optional[int]
) -> WorkTemplateVersion:
    """The version a new project copies: the one asked for, or the latest published."""
    if version_no is not None:
        version = await _get_template_version(session, template, version_no)
        if version.status != "published":
            raise TemplateNotPublishedError()
        return version
    version = (
        await session.execute(
            select(WorkTemplateVersion)
            .where(WorkTemplateVersion.template_id == template.id, WorkTemplateVersion.status == "published")
            .order_by(WorkTemplateVersion.version_no.desc())
        )
    ).scalars().first()
    if not version:
        raise TemplateNotPublishedError()
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


async def _work_unit_responses(session: AsyncSession, work_units: list[WorkUnit]) -> list[WorkUnitResponse]:
    """Responses for a page of work units, loading what they refer to once for the whole page."""
    if not work_units:
        return []
    work_unit_ids = [w.id for w in work_units]
    unit_types = {
        t.id: t
        for t in (
            await session.execute(
                select(WorkUnitType).where(WorkUnitType.id.in_({w.work_unit_type_id for w in work_units}))
            )
        ).scalars()
    }

    template_by_version: dict[uuid.UUID, WorkTemplate] = {}
    version_ids = {w.template_version_id for w in work_units if w.template_version_id is not None}
    if version_ids:
        template_by_version = dict(
            (
                await session.execute(
                    select(WorkTemplateVersion.id, WorkTemplate)
                    .join(WorkTemplate, WorkTemplate.id == WorkTemplateVersion.template_id)
                    .where(WorkTemplateVersion.id.in_(version_ids))
                )
            ).all()
        )
    templates = list({t.id: t for t in template_by_version.values()}.values())
    template_responses = {r.id: r for r in await _template_responses(session, templates)}

    # The latest budget version of each work unit.
    budgets = {
        b.work_unit_id: b
        for b in (
            await session.execute(
                select(WorkBudget).where(WorkBudget.work_unit_id.in_(work_unit_ids)).order_by(WorkBudget.version_no)
            )
        ).scalars()
    }

    running_workflows = await workflow_instances.running_instance_ids(session, WORK_UNIT_SUBJECT, work_unit_ids)

    responses = []
    for work_unit in work_units:
        template = template_by_version.get(work_unit.template_version_id)
        budget = budgets.get(work_unit.id)
        responses.append(
            WorkUnitResponse(
                id=work_unit.id,
                code=work_unit.code,
                name=work_unit.name,
                objective=work_unit.objective,
                type=_work_unit_type_response(unit_types[work_unit.work_unit_type_id]),
                template=template_responses[template.id] if template else None,
                status=work_unit.status,
                priority=work_unit.priority,
                health=work_unit.health,
                progress_pct=float(work_unit.progress_pct),
                owning_unit=unit_ref(work_unit.owning_unit_id),
                vertical=vertical_ref(work_unit.vertical_id),
                client=client_ref(work_unit.client_id),
                contract={"id": str(work_unit.contract_id)} if work_unit.contract_id else None,
                manager=user_ref(work_unit.manager_user_id),
                planned_start=work_unit.planned_start,
                planned_end=work_unit.planned_end,
                actual_start=work_unit.actual_start,
                actual_end=work_unit.actual_end,
                billable=work_unit.billable,
                budget=_budget_amounts(budget),
                workflow_instance_id=running_workflows.get(work_unit.id),
                attributes=work_unit.attributes or {},
                version=work_unit.version,
                created_at=work_unit.created_at,
                updated_at=work_unit.updated_at,
            )
        )
    return responses


def _budget_amounts(budget: Optional[WorkBudget]) -> dict:
    if budget is None:
        return {}
    return {
        "planned": Money(amount=budget.planned_amount, currency=budget.currency).model_dump(mode="json"),
        "approved": Money(amount=budget.approved_amount, currency=budget.currency).model_dump(mode="json"),
    }


async def _work_unit_response(session: AsyncSession, work_unit: WorkUnit) -> WorkUnitResponse:
    return (await _work_unit_responses(session, [work_unit]))[0]


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
    own_records_of: Optional[uuid.UUID] = None,
) -> PageResponse[WorkUnitResponse]:
    """Projects matching the filters; only `own_records_of`'s own ones when it is given."""
    query = select(WorkUnit).where(WorkUnit.organization_id == org_id)
    if own_records_of is not None:
        query = query.where(own_work_units(org_id, own_records_of))
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

    rows, page = await paginate(session, query, WorkUnit, limit, cursor, order_by=WorkUnit.created_at, descending=True)
    return PageResponse(data=await _work_unit_responses(session, rows), page=page)


async def _type_and_template_version(
    session: AsyncSession, org_id: uuid.UUID, data: WorkUnitCreate
) -> tuple[WorkUnitType, Optional[WorkTemplateVersion]]:
    """What a new work unit is: a template's type and published version, or just a type."""
    if not data.template_code:
        return await _find_work_unit_type(session, org_id, data.work_unit_type_code), None

    template = await _get_template_by_code(session, org_id, data.template_code)
    version = await _published_version(session, template, data.template_version_no)
    unit_type = await session.get(WorkUnitType, template.work_unit_type_id)
    if data.work_unit_type_code and data.work_unit_type_code != unit_type.code:
        raise ValidationFailedError("work_unit_type_code", f"The template makes '{unit_type.code}' projects")
    return unit_type, version


async def create_work_unit(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: WorkUnitCreate
) -> WorkUnitResponse:
    unit_type, template_version = await _type_and_template_version(session, org_id, data)
    workflow_code = template_version.workflow_definition_code if template_version else None
    if data.start_workflow and not workflow_code:
        raise ValidationFailedError("start_workflow", "Only a project made from a template with a workflow can start one")
    if unit_type.requires_client and data.client_id is None:
        raise ClientRequiredError()

    work_unit = WorkUnit(
        organization_id=org_id,
        code=await next_work_unit_code(session, org_id),
        name=data.name,
        objective=data.objective,
        work_unit_type_id=unit_type.id,
        template_version_id=template_version.id if template_version else None,
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
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(work_unit)
    await session.flush()
    session.add(StatusHistory(work_unit_id=work_unit.id, from_status=None, to_status=work_unit.status, changed_by=user_id))

    if template_version:
        await _copy_template_structure(session, work_unit, template_version.structure or {})
    if data.start_workflow:
        start = WorkflowInstanceStart(
            definition_code=workflow_code, subject=SubjectRefInput(type=WORK_UNIT_SUBJECT, id=work_unit.id)
        )
        await workflow_instances.start_workflow_instance(session, org_id, user_id, start)

    return await _work_unit_response(session, work_unit)


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


def own_work_units(org_id: uuid.UUID, user_id: uuid.UUID) -> ColumnElement[bool]:
    """Someone's own projects: they manage it, are on its team, or have a task in it."""
    on_the_team = select(WorkUnitMember.work_unit_id).where(
        WorkUnitMember.user_id == user_id,
        or_(WorkUnitMember.valid_to.is_(None), WorkUnitMember.valid_to >= date.today()),
    )
    with_own_tasks = select(Task.work_unit_id).where(
        Task.organization_id == org_id, Task.work_unit_id.is_not(None), own_tasks(user_id)
    )
    return or_(WorkUnit.manager_user_id == user_id, WorkUnit.id.in_(on_the_team), WorkUnit.id.in_(with_own_tasks))


async def ensure_own_work_unit(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Anyone else's project is "not found" for someone who may see only their own."""
    found = await session.execute(
        select(WorkUnit.id).where(
            WorkUnit.id == work_unit_id, WorkUnit.organization_id == org_id, own_work_units(org_id, user_id)
        )
    )
    if found.scalar_one_or_none() is None:
        raise WorkUnitNotFoundError(str(work_unit_id))


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
    return await _work_unit_response(session, work_unit)


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

    work_unit.updated_at = datetime.now(timezone.utc)
    work_unit.version += 1
    await session.flush()
    return await _work_unit_response(session, work_unit)


async def change_work_unit_status(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
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
        session.add(Closure(work_unit_id=work_unit.id, summary=data.reason, closed_by=user_id))

    session.add(
        StatusHistory(
            work_unit_id=work_unit.id, from_status=work_unit.status, to_status=data.to_status,
            changed_by=user_id, reason=data.reason,
        )
    )
    work_unit.status = data.to_status
    effective_on = data.effective_on or date.today()
    if data.to_status == "active" and work_unit.actual_start is None:
        work_unit.actual_start = effective_on
    if data.to_status in ("completed", "closed") and work_unit.actual_end is None:
        work_unit.actual_end = effective_on

    work_unit.updated_at = datetime.now(timezone.utc)
    work_unit.version += 1
    await session.flush()
    return await _work_unit_response(session, work_unit)


async def _require_all_milestones_completed(session: AsyncSession, work_unit_id: uuid.UUID) -> None:
    res = await session.execute(
        select(Milestone.id).where(Milestone.work_unit_id == work_unit_id, Milestone.status != "completed")
    )
    if res.first():
        raise WorkUnitHasOpenItemsError()


async def _require_no_open_items(session: AsyncSession, work_unit_id: uuid.UUID) -> None:
    open_items = (
        select(Task.id).where(Task.work_unit_id == work_unit_id, Task.status.notin_(["done", "cancelled"])),
        select(Risk.id).where(Risk.work_unit_id == work_unit_id, Risk.status.notin_(_CLOSED_RISK_STATUSES)),
        select(ChangeRequest.id).where(
            ChangeRequest.work_unit_id == work_unit_id, ChangeRequest.status.notin_(_CLOSED_CHANGE_REQUEST_STATUSES)
        ),
    )
    for query in open_items:
        if (await session.execute(query.limit(1))).first():
            raise WorkUnitHasOpenItemsError()
    await _require_all_milestones_completed(session, work_unit_id)


async def _count(session: AsyncSession, query) -> int:
    return int((await session.execute(query)).scalar_one() or 0)


async def get_work_unit_summary(session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID) -> WorkUnitSummaryResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)
    work_unit_response = await _work_unit_response(session, work_unit)

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

    milestones_res = await session.execute(
        select(Milestone).where(Milestone.work_unit_id == work_unit_id).order_by(Milestone.seq, Milestone.id)
    )
    milestones = await _milestone_responses(session, list(milestones_res.scalars().all()))

    tasks_by_status = dict(
        (
            await session.execute(
                select(Task.status, func.count(Task.id)).where(Task.work_unit_id == work_unit_id).group_by(Task.status)
            )
        ).all()
    )
    risks_open = await _count(
        session,
        select(func.count(Risk.id)).where(Risk.work_unit_id == work_unit_id, Risk.status.notin_(_CLOSED_RISK_STATUSES)),
    )
    # Change requests waiting for a decision (drafts aren't asking for one yet).
    pending_approvals = await _count(
        session,
        select(func.count(ChangeRequest.id)).where(
            ChangeRequest.work_unit_id == work_unit_id, ChangeRequest.status == "submitted"
        ),
    )

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


async def _milestone_responses(session: AsyncSession, milestones: list[Milestone]) -> list[MilestoneResponse]:
    deliverables: dict[uuid.UUID, list[DeliverableResponse]] = {m.id: [] for m in milestones}
    if milestones:
        res = await session.execute(select(Deliverable).where(Deliverable.milestone_id.in_(deliverables)))
        for deliverable in res.scalars().all():
            deliverables[deliverable.milestone_id].append(DeliverableResponse.model_validate(deliverable))
    return [
        MilestoneResponse(
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
            deliverables=deliverables[milestone.id],
        )
        for milestone in milestones
    ]


async def _milestone_response(session: AsyncSession, milestone: Milestone) -> MilestoneResponse:
    return (await _milestone_responses(session, [milestone]))[0]


async def list_milestones(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[MilestoneResponse]:
    await _get_work_unit(session, org_id, work_unit_id)
    query = select(Milestone).where(Milestone.work_unit_id == work_unit_id)
    rows, page = await paginate(session, query, Milestone, limit, cursor, order_by=Milestone.seq)
    return PageResponse(data=await _milestone_responses(session, rows), page=page)


async def create_milestone(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, data: MilestoneCreate
) -> MilestoneResponse:
    await _get_work_unit(session, org_id, work_unit_id)
    taken = (
        await session.execute(select(Milestone.id).where(Milestone.work_unit_id == work_unit_id, Milestone.code == data.code))
    ).first()
    if taken:
        raise DuplicateCodeError(data.code)
    if data.phase_id is not None:
        phase = await session.get(Phase, data.phase_id)
        if not phase or phase.work_unit_id != work_unit_id:
            raise PhaseNotFoundError(str(data.phase_id))
    last_seq = (
        await session.execute(select(func.max(Milestone.seq)).where(Milestone.work_unit_id == work_unit_id))
    ).scalar_one()
    milestone = Milestone(work_unit_id=work_unit_id, seq=(last_seq or 0) + 1, status="pending", **data.model_dump())
    session.add(milestone)
    await session.flush()
    return await _milestone_response(session, milestone)


async def _get_milestone(session: AsyncSession, org_id: uuid.UUID, milestone_id: uuid.UUID) -> Milestone:
    milestone = await session.get(Milestone, milestone_id)
    if not milestone:
        raise MilestoneNotFoundError(str(milestone_id))
    # Ownership check via the parent work unit's organization.
    await _get_work_unit(session, org_id, milestone.work_unit_id)
    return milestone


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
    return await _milestone_response(session, milestone)


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
    return await _milestone_response(session, milestone)


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
    return await _milestone_response(session, milestone)


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
    return await _milestone_response(session, milestone)


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
        status="open",
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
        owner=user_ref(risk.owner_user_id),
        status=risk.status,
    )


async def list_risks(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[RiskResponse]:
    await _get_work_unit(session, org_id, work_unit_id)
    query = select(Risk).where(Risk.work_unit_id == work_unit_id)
    rows, page = await paginate(session, query, Risk, limit, cursor, order_by=Risk.score, descending=True)
    return PageResponse(data=[_to_risk_response(r) for r in rows], page=page)


async def update_risk(session: AsyncSession, org_id: uuid.UUID, risk_id: uuid.UUID, data: RiskUpdate) -> RiskResponse:
    risk = await session.get(Risk, risk_id)
    if not risk:
        raise RiskNotFoundError(str(risk_id))
    await _get_work_unit(session, org_id, risk.work_unit_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None or field in ("mitigation", "owner_user_id"):
            setattr(risk, field, value)
    risk.score = risk.probability * risk.impact
    await session.flush()
    return _to_risk_response(risk)


def _in_project_currency(work_unit: WorkUnit, cost: Money) -> Decimal:
    """A change's cost goes into the project's budget, so it must be in the project's currency."""
    if cost.currency != work_unit.currency:
        raise ValidationFailedError("cost_impact.currency", f"Use the project's currency, {work_unit.currency}")
    return Decimal(str(cost.amount))


async def create_change_request(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, data: ChangeRequestCreate
) -> ChangeRequestResponse:
    work_unit = await _get_work_unit(session, org_id, work_unit_id)
    cr = ChangeRequest(
        work_unit_id=work_unit_id,
        cr_no=await next_change_request_no(session, org_id, work_unit_id),
        title=data.title,
        reason=data.reason,
        scope_impact=data.scope_impact,
        schedule_impact_days=data.schedule_impact_days,
        cost_impact=_in_project_currency(work_unit, data.cost_impact),
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
        decided_by=user_ref(cr.decided_by),
        decided_at=cr.decided_at,
        decision_note=cr.decision_note,
        approved_schedule_impact_days=cr.approved_schedule_impact_days,
        approved_cost_impact=Money(amount=cr.approved_cost_impact) if cr.approved_cost_impact is not None else None,
    )


async def list_change_requests(
    session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[ChangeRequestResponse]:
    await _get_work_unit(session, org_id, work_unit_id)
    query = select(ChangeRequest).where(ChangeRequest.work_unit_id == work_unit_id)
    rows, page = await paginate(session, query, ChangeRequest, limit, cursor, order_by=ChangeRequest.cr_no)
    return PageResponse(data=[_to_change_request_response(cr) for cr in rows], page=page)


async def _get_change_request(session: AsyncSession, org_id: uuid.UUID, change_request_id: uuid.UUID) -> ChangeRequest:
    cr = await session.get(ChangeRequest, change_request_id)
    if not cr:
        raise ChangeRequestNotFoundError(str(change_request_id))
    await _get_work_unit(session, org_id, cr.work_unit_id)
    return cr


async def _submitted_change_request(
    session: AsyncSession, org_id: uuid.UUID, change_request_id: uuid.UUID, decision: str, if_match: Optional[str]
) -> ChangeRequest:
    cr = await _get_change_request(session, org_id, change_request_id)
    if if_match is None:
        raise PreconditionRequiredError()
    if cr.status != "submitted":
        raise InvalidStateTransitionError(cr.status, decision)
    return cr


def _record_decision(cr: ChangeRequest, decision: str, user_id: uuid.UUID, note: Optional[str]) -> None:
    cr.status = decision
    cr.decided_by = user_id
    cr.decided_at = datetime.now(timezone.utc)
    cr.decision_note = note


async def approve_change_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    change_request_id: uuid.UUID,
    data: ChangeRequestApprove,
    if_match: Optional[str],
) -> ChangeRequestResponse:
    """
    Approve a submitted change request with the impact the approver decided from the change in
    work (what was asked for when they don't say). The approved impact applies at once: the
    project's due date moves by its days, and its cost is added to the budget as a new version.
    """
    cr = await _submitted_change_request(session, org_id, change_request_id, "approved", if_match)
    work_unit = await _get_work_unit(session, org_id, cr.work_unit_id)
    if work_unit.status in ("closed", "cancelled"):
        raise InvalidStateTransitionError(work_unit.status, "change approved")

    days = data.schedule_impact_days if data.schedule_impact_days is not None else cr.schedule_impact_days
    cost = _in_project_currency(work_unit, data.cost_impact) if data.cost_impact is not None else Decimal(str(cr.cost_impact))
    _record_decision(cr, "approved", user_id, data.note)
    cr.approved_schedule_impact_days = days
    cr.approved_cost_impact = cost

    if days and work_unit.planned_end is not None:
        work_unit.planned_end = work_unit.planned_end + timedelta(days=days)
    if cost:
        await _add_to_budget(session, work_unit, cost)
    work_unit.updated_at = datetime.now(timezone.utc)
    work_unit.version += 1
    await session.flush()
    return _to_change_request_response(cr)


async def _add_to_budget(session: AsyncSession, work_unit: WorkUnit, amount: Decimal) -> None:
    """A new budget version with `amount` on top of the latest one; earlier versions stay."""
    latest = (
        await session.execute(
            select(WorkBudget).where(WorkBudget.work_unit_id == work_unit.id).order_by(WorkBudget.version_no.desc())
        )
    ).scalars().first()
    planned = Decimal(str(latest.planned_amount)) if latest else Decimal("0")
    approved = Decimal(str(latest.approved_amount)) if latest else Decimal("0")
    session.add(
        WorkBudget(
            work_unit_id=work_unit.id,
            currency=latest.currency if latest else work_unit.currency,
            planned_amount=planned + amount,
            approved_amount=approved + amount,
            version_no=(latest.version_no + 1) if latest else 1,
        )
    )


async def reject_change_request(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    change_request_id: uuid.UUID,
    reason: str,
    if_match: Optional[str],
) -> ChangeRequestResponse:
    """Reject a submitted change request; nothing about the project changes."""
    cr = await _submitted_change_request(session, org_id, change_request_id, "rejected", if_match)
    _record_decision(cr, "rejected", user_id, reason)
    await session.flush()
    return _to_change_request_response(cr)


async def submit_change_request(
    session: AsyncSession, org_id: uuid.UUID, change_request_id: uuid.UUID, if_match: Optional[str]
) -> ChangeRequestResponse:
    cr = await _get_change_request(session, org_id, change_request_id)

    if if_match is None:
        raise PreconditionRequiredError()
    if cr.status != "draft":
        raise InvalidStateTransitionError(cr.status, "submitted")

    cr.status = "submitted"
    await session.flush()
    return _to_change_request_response(cr)


# --- Members ---------------------------------------------------------------


async def list_members(session: AsyncSession, org_id: uuid.UUID, work_unit_id: uuid.UUID) -> list[MemberResponse]:
    await _get_work_unit(session, org_id, work_unit_id)
    members = await session.execute(
        select(WorkUnitMember).where(WorkUnitMember.work_unit_id == work_unit_id).order_by(WorkUnitMember.valid_from)
    )
    return [
        MemberResponse(
            user=user_ref(m.user_id), member_role=m.member_role, allocation_pct=float(m.allocation_pct),
            valid_from=m.valid_from, valid_to=m.valid_to,
        )
        for m in members.scalars().all()
    ]


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

    work_unit.updated_at = datetime.now(timezone.utc)
    work_unit.version += 1
    await session.flush()
    return await _work_unit_response(session, work_unit)


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
