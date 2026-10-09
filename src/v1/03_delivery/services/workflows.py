"""Workflow definitions and their versions: the stages, transitions and stage tasks a
workflow is drawn with, checked when a version is saved and again, fully, when published.
Running a workflow is services/workflow_instances.py.

Automation rules are stored and returned as drawn but not executed yet.
"""

from collections import Counter
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    DuplicateCodeError,
    PreconditionRequiredError,
    VersionNotDraftError,
    WorkflowDefinitionNotFoundError,
    WorkflowVersionInvalidError,
    WorkflowVersionNotFoundError,
)
from models.task_template import TaskTemplate
from models.task_type_workflow import TaskTypeWorkflow
from models.workflow_definition import WorkflowDefinition, WorkflowVersion
from models.workflow_stage import AutomationRule, Stage, StageTaskTemplate, Transition
from schemas.common import PageResponse
from schemas.workflows import (
    StageDef,
    StageTaskDef,
    TransitionDef,
    ValidationIssue,
    ValidationResult,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowVersionContent,
    WorkflowVersionResponse,
)
from services.json_logic import unknown_operators
from services.pagination import paginate
from services.refs import vertical_ref


def _require_if_match(if_match: Optional[str]) -> None:
    """WorkflowVersion has no int version column (only version_no/status),
    so publish/replace require the header (428 if missing) but cannot detect
    staleness (412) the way WorkUnit/Task/WorkflowInstance updates do."""
    if if_match is None:
        raise PreconditionRequiredError()


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
    rows, page = await paginate(session, query, WorkflowDefinition, limit, cursor, order_by=WorkflowDefinition.code)
    return PageResponse(data=await _definition_responses(session, rows), page=page)


async def _definition_responses(
    session: AsyncSession, definitions: list[WorkflowDefinition]
) -> list[WorkflowDefinitionResponse]:
    version_ids = {d.current_version_id for d in definitions if d.current_version_id is not None}
    version_nos = {}
    if version_ids:
        version_nos = dict(
            (
                await session.execute(
                    select(WorkflowVersion.id, WorkflowVersion.version_no).where(WorkflowVersion.id.in_(version_ids))
                )
            ).all()
        )
    return [
        WorkflowDefinitionResponse(
            id=definition.id,
            code=definition.code,
            name=definition.name,
            subject_type=definition.subject_type,
            vertical=vertical_ref(definition.vertical_id),
            status=definition.status,
            current_version_no=version_nos.get(definition.current_version_id),
        )
        for definition in definitions
    ]


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
    return (await _definition_responses(session, [definition]))[0]


async def get_definition_by_code(session: AsyncSession, org_id: uuid.UUID, definition_code: str) -> WorkflowDefinition:
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
    stage_tasks: dict[uuid.UUID, list[StageTaskDef]] = {s.id: [] for s in stages}
    if stages:
        stage_task_rows = await session.execute(
            select(StageTaskTemplate).where(StageTaskTemplate.stage_id.in_(stage_tasks)).order_by(StageTaskTemplate.title)
        )
        for row in stage_task_rows.scalars().all():
            stage_tasks[row.stage_id].append(
                StageTaskDef(
                    task_template_code=row.task_template_code,
                    title=row.title or None,
                    required=row.required,
                    assignee_selector=row.assignee_selector or {},
                    due_offset_minutes=row.due_offset_minutes,
                )
            )

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
                task_templates=stage_tasks[s.id],
                status_category=s.status_category,
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
    issues = _reference_issues(content)
    if issues:
        raise WorkflowVersionInvalidError([i.model_dump() for i in issues])
    # Clear any existing graph for this version (only draft versions reach here).
    stage_ids = select(Stage.id).where(Stage.version_id == version.id)
    for stage_task in (await session.execute(select(StageTaskTemplate).where(StageTaskTemplate.stage_id.in_(stage_ids)))).scalars().all():
        await session.delete(stage_task)
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
            status_category=stage_def.status_category,
        )
        session.add(stage)
        await session.flush()
        stage_id_by_code[stage_def.code] = stage.id
        for task_def in stage_def.task_templates:
            session.add(
                StageTaskTemplate(
                    stage_id=stage.id,
                    task_template_code=task_def.task_template_code,
                    title=task_def.title or "",
                    required=task_def.required,
                    assignee_selector=task_def.assignee_selector or None,
                    due_offset_minutes=task_def.due_offset_minutes,
                )
            )

    for transition_def in content.transitions:
        from_id = stage_id_by_code[transition_def.from_]
        to_id = stage_id_by_code[transition_def.to]
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
    definition = await get_definition_by_code(session, org_id, definition_code)

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
    definition = await get_definition_by_code(session, org_id, definition_code)
    version = await _get_version(session, definition, version_no)
    _require_if_match(if_match)

    if version.status != "draft":
        raise VersionNotDraftError(version_no)

    await _write_content(session, version, data)
    return await _to_version_response(session, version, definition.code)


def _duplicates(codes: list[str]) -> set[str]:
    return {code for code, uses in Counter(codes).items() if uses > 1}


def _reference_issues(content: WorkflowVersionContent) -> list[ValidationIssue]:
    """Problems that keep a version from being stored at all: transitions are saved against
    their stages, so every stage they name must exist, once."""
    issues = [
        ValidationIssue(code="DUPLICATE_STAGE", message=f"Stage code '{code}' is used more than once.")
        for code in sorted(_duplicates([s.code for s in content.stages]))
    ]
    issues += [
        ValidationIssue(code="DUPLICATE_TRANSITION", message=f"Transition code '{code}' is used more than once.")
        for code in sorted(_duplicates([t.code for t in content.transitions]))
    ]
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

    return issues


def _validate_content(content: WorkflowVersionContent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    start_stages = [s for s in content.stages if s.stage_type == "start"]
    end_stages = [s for s in content.stages if s.stage_type == "end"]

    if len(start_stages) != 1:
        issues.append(ValidationIssue(code="START_STAGE_COUNT", message="Exactly one start stage is required."))
    if not end_stages:
        issues.append(ValidationIssue(code="END_STAGE_MISSING", message="At least one end stage is required."))

    issues.extend(_reference_issues(content))

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


def _rule_issues(content: WorkflowVersionContent) -> list[ValidationIssue]:
    """Conditions and exit criteria may only use operators the engine can evaluate."""
    issues = []
    rules = [(f"transitions[{i}].condition", t.condition) for i, t in enumerate(content.transitions)]
    rules += [(f"stages[{i}].exit_criteria", s.exit_criteria) for i, s in enumerate(content.stages)]
    for path, rule in rules:
        unknown = unknown_operators(rule) if rule else set()
        if unknown:
            issues.append(
                ValidationIssue(code="UNKNOWN_OPERATOR", message=f"Unsupported operator(s): {', '.join(sorted(unknown))}.", path=path)
            )
    return issues


async def _stage_task_issues(session: AsyncSession, org_id: uuid.UUID, content: WorkflowVersionContent) -> list[ValidationIssue]:
    """Stage tasks are made from the organization's task templates, so each must exist."""
    codes = {t.task_template_code for s in content.stages for t in s.task_templates}
    if not codes:
        return []
    known = set(
        (
            await session.execute(
                select(TaskTemplate.code).where(TaskTemplate.organization_id == org_id, TaskTemplate.code.in_(codes))
            )
        ).scalars().all()
    )
    return [
        ValidationIssue(code="UNKNOWN_TASK_TEMPLATE", message=f"There is no task template '{code}'.")
        for code in sorted(codes - known)
    ]


async def _publish_issues(session: AsyncSession, org_id: uuid.UUID, content: WorkflowVersionContent) -> list[ValidationIssue]:
    return _validate_content(content) + _rule_issues(content) + await _stage_task_issues(session, org_id, content)


async def validate_workflow_version(
    session: AsyncSession, org_id: uuid.UUID, definition_code: str, version_no: int
) -> ValidationResult:
    definition = await get_definition_by_code(session, org_id, definition_code)
    version = await _get_version(session, definition, version_no)
    content = await _load_content(session, version)
    issues = await _publish_issues(session, org_id, content)
    return ValidationResult(valid=not issues, errors=issues)


def task_readiness_issues(stages: list[tuple[str, str, Optional[str]]]) -> list[str]:
    """
    Why a version can't be one a task type follows, from its stages' (name, type, status
    category): it needs a start stage, every stage a status category, and every end stage done
    or cancelled (so the task finishes with it).
    """
    issues = []
    if not any(stage_type == "start" for _, stage_type, _ in stages):
        issues.append("it has no start stage")
    uncategorized = [name for name, _, category in stages if not category]
    if uncategorized:
        issues.append("give these stages the task status they stand for: " + ", ".join(uncategorized))
    open_ends = [name for name, stage_type, category in stages if stage_type == "end" and category not in ("done", "cancelled")]
    if open_ends:
        issues.append("an end stage must stand for done or cancelled: " + ", ".join(open_ends))
    return issues


async def publish_workflow_version(
    session: AsyncSession, org_id: uuid.UUID, definition_code: str, version_no: int, if_match: Optional[str]
) -> WorkflowVersionResponse:
    definition = await get_definition_by_code(session, org_id, definition_code)
    version = await _get_version(session, definition, version_no)
    _require_if_match(if_match)

    if version.status != "draft":
        raise VersionNotDraftError(version_no)

    content = await _load_content(session, version)
    issues = await _publish_issues(session, org_id, content)
    # Task types follow the workflow: a new version must still suit them.
    followed = await session.execute(select(TaskTypeWorkflow.task_type_id).where(TaskTypeWorkflow.definition_id == definition.id))
    if followed.first() is not None:
        issues += [
            ValidationIssue(code="NOT_READY_FOR_TASKS", message=message)
            for message in task_readiness_issues([(s.name, s.stage_type, s.status_category) for s in content.stages])
        ]
    if issues:
        raise WorkflowVersionInvalidError([i.model_dump() for i in issues])

    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    definition.current_version_id = version.id
    definition.status = "active"
    await session.flush()
    return await _to_version_response(session, version, definition.code)
