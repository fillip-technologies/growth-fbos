"""Business logic for the Workflow module: workflow definitions, versions,
running instances and transitions.

Simplification note (rule engine): the spec's ``TransitionDef.condition``,
``StageDef.exit_criteria`` and ``WorkflowVersionContent.automation_rules``
are documented as JSON Logic expressions evaluated against the instance
context, and gated transitions are meant to open an approval request in the
Control service (a different microservice) and wait for its decision. Both
of those are substantial pieces of infrastructure (a JSON Logic evaluator,
and a synchronous cross-service call with its own retry/idempotency
contract) that are out of scope for this pass. This service stores
conditions/automation rules verbatim and exposes them unchanged, but:
  * a transition's ``condition`` is not evaluated -- it is treated as always
    satisfied (so ``TRANSITION_CONDITION_FAILED`` is defined but never
    raised by this implementation);
  * a transition that carries ``approval_policy_code`` still reports
    ``requires_approval: true`` and, when performed, returns
    ``outcome: "approval_pending"`` and parks the instance in
    ``waiting_approval`` without actually calling the Control service.
The CRUD/data-shape surface (definitions, versions, stages, transitions,
instances, transition history) is fully implemented against the local
models.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    DuplicateCodeError,
    InstanceAlreadyRunningError,
    InstanceNotRunningError,
    InvalidStateTransitionError,
    PreconditionRequiredError,
    SubjectNotFoundError,
    SubjectTypeMismatchError,
    TransitionConditionFailedError,
    TransitionNotAvailableError,
    VersionConflictError,
    VersionNotDraftError,
    WorkflowDefinitionNotFoundError,
    WorkflowInstanceNotFoundError,
    WorkflowVersionInvalidError,
    WorkflowVersionNotFoundError,
)
from models.work_unit import WorkUnit
from models.workflow_definition import WorkflowDefinition, WorkflowVersion
from models.workflow_execution import TransitionLog
from models.workflow_instance import StageRun, WorkflowInstance
from models.workflow_stage import AutomationRule, Stage, Transition
from schemas.common import PageMeta, PageResponse
from schemas.workflows import (
    AvailableTransitionResponse,
    HoldRequest,
    InstanceHistoryItemResponse,
    StageDef,
    StageRunSummary,
    TransitionDef,
    TransitionRequest,
    TransitionResult,
    ValidationIssue,
    ValidationResult,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowInstanceResponse,
    WorkflowInstanceStart,
    WorkflowVersionContent,
    WorkflowVersionResponse,
)
from services.pagination import paginate_by_id
from services.refs import unit_ref, vertical_ref

_TERMINAL_INSTANCE_STATUSES = {"completed", "cancelled", "failed"}


def _require_if_match(if_match: Optional[str]) -> None:
    """WorkflowVersion has no int version column (only version_no/status),
    so publish/replace require the header (428 if missing) but cannot detect
    staleness (412) the way WorkUnit/Task/WorkflowInstance updates do."""
    if if_match is None:
        raise PreconditionRequiredError()


def _check_instance_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


# --- Definitions -----------------------------------------------------------


async def list_workflow_definitions(
    session: AsyncSession,
    org_id: uuid.UUID,
    subject_type: Optional[str],
    vertical_id: Optional[uuid.UUID],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[WorkflowDefinitionResponse]:
    query = select(WorkflowDefinition).where(WorkflowDefinition.organization_id == org_id)
    if subject_type is not None:
        query = query.where(WorkflowDefinition.subject_type == subject_type)
    if vertical_id is not None:
        query = query.where(WorkflowDefinition.vertical_id == vertical_id)
    rows, page = await paginate_by_id(session, query, WorkflowDefinition, limit, cursor)
    data = [await _to_definition_response(session, d) for d in rows]
    return PageResponse(data=data, page=page)


async def _to_definition_response(session: AsyncSession, definition: WorkflowDefinition) -> WorkflowDefinitionResponse:
    current_version_no = None
    if definition.current_version_id is not None:
        version = await session.get(WorkflowVersion, definition.current_version_id)
        current_version_no = version.version_no if version else None
    return WorkflowDefinitionResponse(
        id=definition.id,
        code=definition.code,
        name=definition.name,
        subject_type=definition.subject_type,
        vertical=vertical_ref(definition.vertical_id),
        status=definition.status,
        current_version_no=current_version_no,
    )


async def create_workflow_definition(
    session: AsyncSession, org_id: uuid.UUID, data: WorkflowDefinitionCreate
) -> WorkflowDefinitionResponse:
    existing = await session.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.organization_id == org_id, WorkflowDefinition.code == data.code)
    )
    if existing.scalars().first():
        raise DuplicateCodeError(data.code)

    definition = WorkflowDefinition(
        organization_id=org_id,
        vertical_id=data.vertical_id,
        code=data.code,
        name=data.name,
        subject_type=data.subject_type,
        status="active",
    )
    session.add(definition)
    await session.flush()
    return await _to_definition_response(session, definition)


async def _get_definition_by_code(session: AsyncSession, org_id: uuid.UUID, definition_code: str) -> WorkflowDefinition:
    res = await session.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.organization_id == org_id, WorkflowDefinition.code == definition_code
        )
    )
    definition = res.scalars().first()
    if not definition:
        raise WorkflowDefinitionNotFoundError(definition_code)
    return definition


# --- Versions ----------------------------------------------------------


async def _get_version(session: AsyncSession, definition: WorkflowDefinition, version_no: int) -> WorkflowVersion:
    res = await session.execute(
        select(WorkflowVersion).where(
            WorkflowVersion.definition_id == definition.id, WorkflowVersion.version_no == version_no
        )
    )
    version = res.scalars().first()
    if not version:
        raise WorkflowVersionNotFoundError(version_no)
    return version


async def _load_content(session: AsyncSession, version: WorkflowVersion) -> WorkflowVersionContent:
    stages_res = await session.execute(select(Stage).where(Stage.version_id == version.id).order_by(Stage.seq))
    stages = list(stages_res.scalars().all())
    transitions_res = await session.execute(select(Transition).where(Transition.version_id == version.id))
    transitions = list(transitions_res.scalars().all())
    rules_res = await session.execute(select(AutomationRule).where(AutomationRule.version_id == version.id))
    rules = list(rules_res.scalars().all())

    stage_name_by_id = {s.id: s.code for s in stages}
    return WorkflowVersionContent(
        stages=[
            StageDef(
                code=s.code,
                name=s.name,
                seq=s.seq,
                stage_type=s.stage_type,
                owner_unit_selector=s.owner_unit_selector or {},
                sla_policy_code=s.sla_policy_code,
                exit_criteria=s.exit_criteria,
                allow_parallel=s.allow_parallel,
                task_templates=None,
            )
            for s in stages
        ],
        transitions=[
            TransitionDef(
                code=t.code,
                name=t.name,
                from_=stage_name_by_id.get(t.from_stage_id, ""),
                to=stage_name_by_id.get(t.to_stage_id, ""),
                trigger_type=t.trigger_type,
                condition=t.condition,
                approval_policy_code=t.approval_policy_code,
                allowed_permission=t.allowed_permission,
                priority=t.priority,
            )
            for t in transitions
        ],
        automation_rules=[{"trigger": r.trigger, "condition": r.condition, "actions": r.actions} for r in rules] or None,
    )


async def _to_version_response(session: AsyncSession, version: WorkflowVersion, definition_code: str) -> WorkflowVersionResponse:
    content = await _load_content(session, version)
    return WorkflowVersionResponse(
        id=version.id,
        definition_code=definition_code,
        version_no=version.version_no,
        status=version.status,
        checksum=version.checksum,
        published_at=version.published_at,
        content=content,
    )


async def _write_content(session: AsyncSession, version: WorkflowVersion, content: WorkflowVersionContent) -> None:
    # Clear any existing graph for this version (only draft versions reach here).
    for model in (AutomationRule, Transition, Stage):
        rows = (await session.execute(select(model).where(model.version_id == version.id))).scalars().all()
        for row in rows:
            await session.delete(row)
    await session.flush()

    stage_id_by_code: dict[str, uuid.UUID] = {}
    for stage_def in content.stages:
        stage = Stage(
            version_id=version.id,
            code=stage_def.code,
            name=stage_def.name,
            seq=stage_def.seq,
            stage_type=stage_def.stage_type,
            owner_unit_selector=stage_def.owner_unit_selector,
            sla_policy_code=stage_def.sla_policy_code,
            exit_criteria=stage_def.exit_criteria,
            allow_parallel=stage_def.allow_parallel or False,
        )
        session.add(stage)
        await session.flush()
        stage_id_by_code[stage_def.code] = stage.id

    for transition_def in content.transitions:
        from_id = stage_id_by_code.get(transition_def.from_)
        to_id = stage_id_by_code.get(transition_def.to)
        if from_id is None or to_id is None:
            continue
        session.add(
            Transition(
                version_id=version.id,
                code=transition_def.code,
                name=transition_def.name,
                trigger_type=transition_def.trigger_type,
                from_stage_id=from_id,
                to_stage_id=to_id,
                condition=transition_def.condition,
                approval_policy_code=transition_def.approval_policy_code,
                allowed_permission=transition_def.allowed_permission,
                priority=transition_def.priority or 0,
            )
        )

    for rule in content.automation_rules or []:
        session.add(
            AutomationRule(
                version_id=version.id,
                trigger=rule.get("trigger", "on_stage_enter"),
                condition=rule.get("condition"),
                actions=rule.get("actions", {}),
            )
        )

    await session.flush()


async def create_workflow_version(
    session: AsyncSession, org_id: uuid.UUID, definition_code: str, data: WorkflowVersionContent
) -> WorkflowVersionResponse:
    definition = await _get_definition_by_code(session, org_id, definition_code)

    last_res = await session.execute(
        select(WorkflowVersion.version_no)
        .where(WorkflowVersion.definition_id == definition.id)
        .order_by(WorkflowVersion.version_no.desc())
    )
    last_version_no = last_res.scalars().first() or 0

    content = data
    if not content.stages and definition.current_version_id is not None:
        current = await session.get(WorkflowVersion, definition.current_version_id)
        if current:
            content = await _load_content(session, current)

    version = WorkflowVersion(definition_id=definition.id, version_no=last_version_no + 1, status="draft")
    session.add(version)
    await session.flush()

    await _write_content(session, version, content)
    return await _to_version_response(session, version, definition.code)


async def replace_workflow_version(
    session: AsyncSession,
    org_id: uuid.UUID,
    definition_code: str,
    version_no: int,
    data: WorkflowVersionContent,
    if_match: Optional[str],
) -> WorkflowVersionResponse:
    definition = await _get_definition_by_code(session, org_id, definition_code)
    version = await _get_version(session, definition, version_no)
    _require_if_match(if_match)

    if version.status != "draft":
        raise VersionNotDraftError(version_no)

    await _write_content(session, version, data)
    return await _to_version_response(session, version, definition.code)


def _validate_content(content: WorkflowVersionContent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    start_stages = [s for s in content.stages if s.stage_type == "start"]
    end_stages = [s for s in content.stages if s.stage_type == "end"]

    if len(start_stages) != 1:
        issues.append(ValidationIssue(code="START_STAGE_COUNT", message="Exactly one start stage is required."))
    if not end_stages:
        issues.append(ValidationIssue(code="END_STAGE_MISSING", message="At least one end stage is required."))

    stage_codes = {s.code for s in content.stages}
    for index, transition in enumerate(content.transitions):
        if transition.from_ not in stage_codes:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_FROM_STAGE",
                    message=f"Transition '{transition.code}' references unknown from-stage '{transition.from_}'.",
                    path=f"transitions[{index}]",
                )
            )
        if transition.to not in stage_codes:
            issues.append(
                ValidationIssue(
                    code="UNKNOWN_TO_STAGE",
                    message=f"Transition '{transition.code}' references unknown to-stage '{transition.to}'.",
                    path=f"transitions[{index}]",
                )
            )

    if start_stages:
        reachable = {start_stages[0].code}
        changed = True
        while changed:
            changed = False
            for transition in content.transitions:
                if transition.from_ in reachable and transition.to not in reachable:
                    reachable.add(transition.to)
                    changed = True
        for stage in content.stages:
            if stage.code not in reachable:
                issues.append(
                    ValidationIssue(code="UNREACHABLE_STAGE", message=f"Stage '{stage.code}' cannot be reached from the start stage.")
                )

    return issues


async def validate_workflow_version(
    session: AsyncSession, org_id: uuid.UUID, definition_code: str, version_no: int
) -> ValidationResult:
    definition = await _get_definition_by_code(session, org_id, definition_code)
    version = await _get_version(session, definition, version_no)
    content = await _load_content(session, version)
    issues = _validate_content(content)
    return ValidationResult(valid=not issues, errors=issues)


async def publish_workflow_version(
    session: AsyncSession, org_id: uuid.UUID, definition_code: str, version_no: int, if_match: Optional[str]
) -> WorkflowVersionResponse:
    definition = await _get_definition_by_code(session, org_id, definition_code)
    version = await _get_version(session, definition, version_no)
    _require_if_match(if_match)

    if version.status != "draft":
        raise VersionNotDraftError(version_no)

    content = await _load_content(session, version)
    issues = _validate_content(content)
    if issues:
        raise WorkflowVersionInvalidError([i.model_dump() for i in issues])

    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    definition.current_version_id = version.id
    definition.status = "active"
    await session.flush()
    return await _to_version_response(session, version, definition.code)


# --- Instances ---------------------------------------------------------


async def _subject_exists(session: AsyncSession, org_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID) -> bool:
    """Only work.work_unit subjects are locally verifiable; every other
    subject type belongs to another service and is trusted as-is (see
    module docstring)."""
    if subject_type != "work.work_unit":
        return True
    res = await session.execute(select(WorkUnit).where(WorkUnit.id == subject_id, WorkUnit.organization_id == org_id))
    return res.scalars().first() is not None


async def start_workflow_instance(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: WorkflowInstanceStart
) -> WorkflowInstanceResponse:
    definition = await _get_definition_by_code(session, org_id, data.definition_code)

    if definition.subject_type != data.subject.type:
        raise SubjectTypeMismatchError()
    if not await _subject_exists(session, org_id, data.subject.type, data.subject.id):
        raise SubjectNotFoundError()

    running_res = await session.execute(
        select(WorkflowInstance).where(
            WorkflowInstance.organization_id == org_id,
            WorkflowInstance.version_id.in_(
                select(WorkflowVersion.id).where(WorkflowVersion.definition_id == definition.id)
            ),
            WorkflowInstance.subject_type == data.subject.type,
            WorkflowInstance.subject_id == data.subject.id,
            WorkflowInstance.status.notin_(_TERMINAL_INSTANCE_STATUSES),
        )
    )
    if running_res.scalars().first():
        raise InstanceAlreadyRunningError()

    if definition.current_version_id is None:
        raise WorkflowVersionNotFoundError()
    version = await session.get(WorkflowVersion, definition.current_version_id)

    instance = WorkflowInstance(
        version_id=version.id,
        organization_id=org_id,
        subject_type=data.subject.type,
        subject_id=data.subject.id,
        status="running",
        context=data.context or {},
        started_by=user_id,
        version=1,
    )
    session.add(instance)
    await session.flush()

    start_stage_res = await session.execute(
        select(Stage).where(Stage.version_id == version.id, Stage.stage_type == "start")
    )
    start_stage = start_stage_res.scalars().first()
    if start_stage:
        session.add(StageRun(instance_id=instance.id, stage_id=start_stage.id, status="active"))
        await session.flush()

    return await _to_instance_response(session, instance, version.version_no)


async def _to_instance_response(session: AsyncSession, instance: WorkflowInstance, version_no: int) -> WorkflowInstanceResponse:
    stage_runs_res = await session.execute(
        select(StageRun).where(StageRun.instance_id == instance.id, StageRun.exited_at.is_(None))
    )
    current_stages = []
    for stage_run in stage_runs_res.scalars().all():
        stage = await session.get(Stage, stage_run.stage_id)
        current_stages.append(
            StageRunSummary(
                stage_run_id=stage_run.id,
                stage_code=stage.code if stage else "",
                stage_name=stage.name if stage else "",
                entered_at=stage_run.entered_at,
                iteration=stage_run.iteration,
                owner_unit=unit_ref(stage_run.owner_unit_id, "Owning Unit") if stage_run.owner_unit_id else None,
            )
        )

    definition = await session.get(WorkflowDefinition, (await session.get(WorkflowVersion, instance.version_id)).definition_id)

    return WorkflowInstanceResponse(
        id=instance.id,
        definition={"code": definition.code, "name": definition.name} if definition else {},
        version_no=version_no,
        subject={"type": instance.subject_type, "id": instance.subject_id},
        status=instance.status,
        current_stages=current_stages,
        context=instance.context or {},
        started_at=instance.started_at,
        completed_at=instance.completed_at,
        version=instance.version,
    )


async def list_workflow_instances(
    session: AsyncSession,
    org_id: uuid.UUID,
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    status: Optional[str],
    definition_code: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[WorkflowInstanceResponse]:
    query = select(WorkflowInstance).where(WorkflowInstance.organization_id == org_id)
    if subject_type is not None:
        query = query.where(WorkflowInstance.subject_type == subject_type)
    if subject_id is not None:
        query = query.where(WorkflowInstance.subject_id == subject_id)
    if status is not None:
        query = query.where(WorkflowInstance.status == status)
    if definition_code is not None:
        definition = await _get_definition_by_code(session, org_id, definition_code)
        query = query.where(
            WorkflowInstance.version_id.in_(select(WorkflowVersion.id).where(WorkflowVersion.definition_id == definition.id))
        )

    rows, page = await paginate_by_id(session, query, WorkflowInstance, limit, cursor)
    data = []
    for instance in rows:
        version = await session.get(WorkflowVersion, instance.version_id)
        data.append(await _to_instance_response(session, instance, version.version_no if version else 0))
    return PageResponse(data=data, page=page)


async def _get_instance(session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID) -> WorkflowInstance:
    res = await session.execute(
        select(WorkflowInstance).where(WorkflowInstance.id == instance_id, WorkflowInstance.organization_id == org_id)
    )
    instance = res.scalars().first()
    if not instance:
        raise WorkflowInstanceNotFoundError(str(instance_id))
    return instance


async def get_workflow_instance(session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id)
    version = await session.get(WorkflowVersion, instance.version_id)
    return await _to_instance_response(session, instance, version.version_no if version else 0)


async def list_available_transitions(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[AvailableTransitionResponse]:
    instance = await _get_instance(session, org_id, instance_id)

    stage_runs_res = await session.execute(
        select(StageRun).where(StageRun.instance_id == instance.id, StageRun.exited_at.is_(None))
    )
    active_stage_ids = [sr.stage_id for sr in stage_runs_res.scalars().all()]

    transitions: list[Transition] = []
    if active_stage_ids and instance.status == "running":
        transitions_res = await session.execute(select(Transition).where(Transition.from_stage_id.in_(active_stage_ids)))
        transitions = list(transitions_res.scalars().all())

    page_rows = transitions[:limit]
    data = []
    for transition in page_rows:
        to_stage = await session.get(Stage, transition.to_stage_id)
        data.append(
            AvailableTransitionResponse(
                code=transition.code,
                name=transition.name,
                to_stage=to_stage.code if to_stage else "",
                requires_approval=bool(transition.approval_policy_code),
                allowed=True,
                blocked_reasons=[],
            )
        )

    page = PageMeta(next_cursor=None, has_more=len(transitions) > limit, limit=limit)
    return PageResponse(data=data, page=page)


async def perform_transition(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, data: TransitionRequest, if_match: Optional[str]
) -> TransitionResult:
    instance = await _get_instance(session, org_id, instance_id)
    _check_instance_if_match(if_match, instance.version)

    if instance.status != "running":
        raise InstanceNotRunningError(instance.status)

    stage_runs_res = await session.execute(
        select(StageRun).where(StageRun.instance_id == instance.id, StageRun.exited_at.is_(None))
    )
    active_stage_runs = list(stage_runs_res.scalars().all())
    active_stage_ids = [sr.stage_id for sr in active_stage_runs]

    transition_res = await session.execute(
        select(Transition).where(Transition.code == data.transition_code, Transition.from_stage_id.in_(active_stage_ids))
    )
    transition = transition_res.scalars().first()
    if not transition:
        raise TransitionNotAvailableError(data.transition_code)

    if data.context_patch:
        merged = dict(instance.context or {})
        merged.update(data.context_patch)
        instance.context = merged

    version = await session.get(WorkflowVersion, instance.version_id)

    if transition.approval_policy_code:
        instance.status = "waiting_approval"
        await session.flush()
        return TransitionResult(
            outcome="approval_pending",
            instance=await _to_instance_response(session, instance, version.version_no if version else 0),
            approval_request_id=None,
        )

    from_run = next((sr for sr in active_stage_runs if sr.stage_id == transition.from_stage_id), None)
    if from_run:
        from_run.exited_at = datetime.now(timezone.utc)
        from_run.exited_via_transition_id = transition.id
        from_run.status = "completed"

    to_stage = await session.get(Stage, transition.to_stage_id)
    new_run = StageRun(instance_id=instance.id, stage_id=transition.to_stage_id, status="active", entered_via_transition_id=transition.id)
    session.add(new_run)
    await session.flush()

    session.add(
        TransitionLog(
            instance_id=instance.id,
            transition_id=transition.id,
            from_stage_run_id=from_run.id if from_run else None,
            to_stage_run_id=new_run.id,
            reason=data.reason,
        )
    )

    if to_stage and to_stage.stage_type == "end":
        instance.status = "completed"
        instance.completed_at = datetime.now(timezone.utc)
        new_run.exited_at = instance.completed_at
        new_run.status = "completed"

    instance.version += 1
    await session.flush()

    return TransitionResult(
        outcome="transitioned",
        instance=await _to_instance_response(session, instance, version.version_no if version else 0),
        approval_request_id=None,
    )


async def hold_instance(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, data: HoldRequest, if_match: Optional[str]
) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id)
    _check_instance_if_match(if_match, instance.version)

    if instance.status != "running":
        raise InstanceNotRunningError(instance.status)

    instance.status = "on_hold"
    instance.version += 1
    await session.flush()
    version = await session.get(WorkflowVersion, instance.version_id)
    return await _to_instance_response(session, instance, version.version_no if version else 0)


async def resume_instance(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, if_match: Optional[str]
) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id)
    _check_instance_if_match(if_match, instance.version)

    if instance.status != "on_hold":
        raise InvalidStateTransitionError(instance.status, "running")

    instance.status = "running"
    instance.version += 1
    await session.flush()
    version = await session.get(WorkflowVersion, instance.version_id)
    return await _to_instance_response(session, instance, version.version_no if version else 0)


async def cancel_instance(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, data: HoldRequest, if_match: Optional[str]
) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id)
    _check_instance_if_match(if_match, instance.version)

    if instance.status in _TERMINAL_INSTANCE_STATUSES:
        raise InvalidStateTransitionError(instance.status, "cancelled")

    instance.status = "cancelled"
    instance.completed_at = datetime.now(timezone.utc)
    instance.version += 1
    await session.flush()
    version = await session.get(WorkflowVersion, instance.version_id)
    return await _to_instance_response(session, instance, version.version_no if version else 0)


async def get_instance_history(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[InstanceHistoryItemResponse]:
    instance = await _get_instance(session, org_id, instance_id)

    query = select(TransitionLog).where(TransitionLog.instance_id == instance.id)
    rows, page = await paginate_by_id(session, query, TransitionLog, limit, cursor)

    data = []
    for log in rows:
        transition = await session.get(Transition, log.transition_id)
        to_stage = await session.get(Stage, transition.to_stage_id) if transition else None
        data.append(
            InstanceHistoryItemResponse(
                at=log.performed_at,
                type="transition",
                stage_code=to_stage.code if to_stage else None,
                details={"transition_code": transition.code if transition else None, "reason": log.reason},
            )
        )
    return PageResponse(data=data, page=page)
