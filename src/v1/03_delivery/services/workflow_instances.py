"""
Running workflows: an instance moves its subject (a project, a task) through the stages of a
published workflow version.

- A transition may be blocked: by the permission it names, by its condition, by the exit
  criteria of the stage it leaves (JSON Logic against the instance's context), or by the
  stage's required tasks that are still open.
- A transition with an approval policy waits for a decision (a pending "approval" signal)
  and moves only when it is approved. Until approvals live in the control service, the
  decision is taken here (`delivery.workflow.approve`).
- Entering a stage creates its stage tasks from the organization's task templates. The
  owning team is the stage's `owner_unit_selector.unit_id`, else the project's team; the
  assignee is `assignee_selector.user_id`, else nobody (the team's queue); the due date is
  `due_offset_minutes` after the stage is entered.
- An instance that governs its task (started because the task's type follows the workflow,
  services/task_workflows.py) moves the task with it: each stage sets the task's status by its
  category, and a stage of another team moves the task there (services/tasks.py,
  `enter_task_stage`). A task has at most one such workflow, and nothing else runs beside it.
  Steps into a stage the task isn't ready for (blocked, waiting on other tasks, fields or
  checklist missing for review) are blocked, and cancelling either ends the other.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    InstanceAlreadyRunningError,
    InstanceNotRunningError,
    InvalidStateTransitionError,
    PermissionDeniedError,
    PreconditionRequiredError,
    SubjectNotFoundError,
    SubjectTypeMismatchError,
    TransitionConditionFailedError,
    TransitionNotAvailableError,
    VersionConflictError,
    WorkflowInstanceNotFoundError,
    WorkflowVersionNotFoundError,
)
from models.task import Task
from models.task_template import TaskTemplate
from models.work_unit import WorkUnit
from models.workflow_definition import WorkflowDefinition, WorkflowVersion
from models.workflow_execution import TransitionLog
from models.workflow_instance import PendingSignal, StageRun, WorkflowInstance
from models.workflow_stage import Stage, StageTaskTemplate, Transition
from schemas.common import PageMeta, PageResponse
from schemas.workflows import (
    AvailableTransitionResponse,
    HoldRequest,
    InstanceHistoryItemResponse,
    StageRunSummary,
    TransitionRequest,
    TransitionResult,
    WorkflowInstanceResponse,
    WorkflowInstanceStart,
)
from services.identity_client import Actor
from services.json_logic import evaluate, truthy
from services.pagination import paginate
from services.refs import unit_ref
from services.assignees import PeopleDirectory
from services.tasks import (
    TASK_SUBJECT,
    WORK_UNIT_SUBJECT,
    cancel_task_with_workflow,
    create_stage_task,
    enter_task_stage,
    governing_stage,
    open_required_stage_tasks,
    stage_entry_issues,
    workflow_step_waits,
)
from services.workflows import get_definition_by_code

TERMINAL_STATUSES = {"completed", "cancelled", "failed"}
APPROVAL_SIGNAL = "approval"


def _check_if_match(if_match: Optional[str], current_version: int) -> None:
    if if_match is None:
        raise PreconditionRequiredError()
    expected = if_match.strip(' "').replace("W/", "")
    if not expected.isdigit() or int(expected) != current_version:
        raise VersionConflictError(current_version)


def _uuid_or_none(value: object) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


# --- Starting -------------------------------------------------------------------


async def _subject_exists(session: AsyncSession, org_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID) -> bool:
    """Projects and tasks are delivery's own and checked; other subjects belong to other
    services and are taken as given."""
    model = {WORK_UNIT_SUBJECT: WorkUnit, TASK_SUBJECT: Task}.get(subject_type)
    if model is None:
        return True
    found = await session.execute(select(model.id).where(model.id == subject_id, model.organization_id == org_id))
    return found.first() is not None


async def start_workflow_instance(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, data: WorkflowInstanceStart
) -> WorkflowInstanceResponse:
    definition = await get_definition_by_code(session, org_id, data.definition_code)

    if definition.subject_type != data.subject.type:
        raise SubjectTypeMismatchError()
    if not await _subject_exists(session, org_id, data.subject.type, data.subject.id):
        raise SubjectNotFoundError()

    running_res = await session.execute(
        select(WorkflowInstance.id).where(
            WorkflowInstance.organization_id == org_id,
            WorkflowInstance.version_id.in_(
                select(WorkflowVersion.id).where(WorkflowVersion.definition_id == definition.id)
            ),
            WorkflowInstance.subject_type == data.subject.type,
            WorkflowInstance.subject_id == data.subject.id,
            WorkflowInstance.status.notin_(TERMINAL_STATUSES),
        )
    )
    if running_res.first():
        raise InstanceAlreadyRunningError()
    # A task its type's workflow governs follows that one only.
    if data.subject.type == TASK_SUBJECT and await governing_stage(session, data.subject.id) is not None:
        raise InstanceAlreadyRunningError()

    if definition.current_version_id is None:
        raise WorkflowVersionNotFoundError()

    instance = WorkflowInstance(
        version_id=definition.current_version_id,
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

    start_stage = (
        await session.execute(
            select(Stage).where(Stage.version_id == definition.current_version_id, Stage.stage_type == "start")
        )
    ).scalars().first()
    if start_stage:
        await _enter_stage(session, instance, start_stage, via_transition_id=None)

    return await _instance_response(session, instance)


async def start_governing_workflow(
    session: AsyncSession,
    people: Optional[PeopleDirectory],
    task: Task,
    definition: WorkflowDefinition,
    user_id: Optional[uuid.UUID],
) -> Optional[WorkflowInstance]:
    """Starts the workflow a new task's type follows, on its current version, and puts the task in its first stage."""
    if definition.current_version_id is None:
        return None
    start_stage = (
        await session.execute(
            select(Stage).where(Stage.version_id == definition.current_version_id, Stage.stage_type == "start")
        )
    ).scalars().first()
    if start_stage is None:
        return None
    instance = WorkflowInstance(
        version_id=definition.current_version_id,
        organization_id=task.organization_id,
        subject_type=TASK_SUBJECT,
        subject_id=task.id,
        status="running",
        context={},
        started_by=user_id,
        version=1,
        governs_status=True,
    )
    session.add(instance)
    await session.flush()
    await _enter_stage(session, instance, start_stage, via_transition_id=None, people=people, user_id=user_id)
    return instance


async def _enter_stage(
    session: AsyncSession,
    instance: WorkflowInstance,
    stage: Stage,
    via_transition_id: Optional[uuid.UUID],
    people: Optional[PeopleDirectory] = None,
    user_id: Optional[uuid.UUID] = None,
    note: Optional[str] = None,
) -> StageRun:
    stage_run = StageRun(
        instance_id=instance.id,
        stage_id=stage.id,
        status="active",
        owner_unit_id=_uuid_or_none((stage.owner_unit_selector or {}).get("unit_id")),
        entered_via_transition_id=via_transition_id,
    )
    session.add(stage_run)
    await session.flush()

    if instance.governs_status and instance.subject_type == TASK_SUBJECT:
        task = await session.get(Task, instance.subject_id)
        if task is not None:
            await enter_task_stage(session, people, task, stage, user_id, note)

    if stage.stage_type == "end":
        instance.status = "completed"
        instance.completed_at = datetime.now(timezone.utc)
        stage_run.exited_at = instance.completed_at
        stage_run.status = "completed"
        return stage_run

    await _create_stage_tasks(session, instance, stage, stage_run)
    return stage_run


async def _create_stage_tasks(session: AsyncSession, instance: WorkflowInstance, stage: Stage, stage_run: StageRun) -> None:
    stage_tasks = (
        await session.execute(select(StageTaskTemplate).where(StageTaskTemplate.stage_id == stage.id))
    ).scalars().all()
    if not stage_tasks:
        return
    templates = {
        t.code: t
        for t in (
            await session.execute(
                select(TaskTemplate).where(
                    TaskTemplate.organization_id == instance.organization_id,
                    TaskTemplate.code.in_({st.task_template_code for st in stage_tasks}),
                )
            )
        ).scalars()
    }
    work_unit = await session.get(WorkUnit, instance.subject_id) if instance.subject_type == WORK_UNIT_SUBJECT else None
    subject_task = await session.get(Task, instance.subject_id) if instance.subject_type == TASK_SUBJECT else None
    # Every task has a team: the stage's own, else the project's, else that of the task the workflow runs on.
    owning_unit_id = (
        stage_run.owner_unit_id
        or (work_unit.owning_unit_id if work_unit else None)
        or (subject_task.owning_unit_id if subject_task else None)
    )

    for stage_task in stage_tasks:
        # Publishing checks every template exists; one removed since is skipped.
        template = templates.get(stage_task.task_template_code)
        if template is None:
            continue
        due_at = stage_run.entered_at + timedelta(minutes=stage_task.due_offset_minutes) if stage_task.due_offset_minutes else None
        await create_stage_task(
            session,
            instance.organization_id,
            template,
            title=stage_task.title,
            subject_type=instance.subject_type,
            subject_id=instance.subject_id,
            work_unit_id=work_unit.id if work_unit else None,
            owning_unit_id=owning_unit_id,
            assignee_user_id=_uuid_or_none((stage_task.assignee_selector or {}).get("user_id")),
            due_at=due_at,
            workflow_instance_id=instance.id,
            stage_run_id=stage_run.id,
            required=stage_task.required,
        )


# --- Reading ----------------------------------------------------------------------


async def _instance_responses(
    session: AsyncSession, instances: list[WorkflowInstance]
) -> list[WorkflowInstanceResponse]:
    """Responses for a page of instances: definitions and open stages loaded once for the page."""
    if not instances:
        return []
    versions = {
        version_id: (version_no, code, name)
        for version_id, version_no, code, name in (
            await session.execute(
                select(WorkflowVersion.id, WorkflowVersion.version_no, WorkflowDefinition.code, WorkflowDefinition.name)
                .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowVersion.definition_id)
                .where(WorkflowVersion.id.in_({i.version_id for i in instances}))
            )
        ).all()
    }
    current_stages: dict[uuid.UUID, list[StageRunSummary]] = {i.id: [] for i in instances}
    open_runs = await session.execute(
        select(StageRun, Stage.code, Stage.name)
        .join(Stage, Stage.id == StageRun.stage_id)
        .where(StageRun.instance_id.in_(current_stages), StageRun.exited_at.is_(None))
        .order_by(StageRun.entered_at)
    )
    for stage_run, stage_code, stage_name in open_runs.all():
        current_stages[stage_run.instance_id].append(
            StageRunSummary(
                stage_run_id=stage_run.id,
                stage_code=stage_code,
                stage_name=stage_name,
                entered_at=stage_run.entered_at,
                iteration=stage_run.iteration,
                owner_unit=unit_ref(stage_run.owner_unit_id),
            )
        )

    responses = []
    for instance in instances:
        version_no, definition_code, definition_name = versions[instance.version_id]
        responses.append(
            WorkflowInstanceResponse(
                id=instance.id,
                definition={"code": definition_code, "name": definition_name},
                version_no=version_no,
                subject={"type": instance.subject_type, "id": instance.subject_id},
                status=instance.status,
                current_stages=current_stages[instance.id],
                context=instance.context or {},
                started_at=instance.started_at,
                completed_at=instance.completed_at,
                version=instance.version,
            )
        )
    return responses


async def _instance_response(session: AsyncSession, instance: WorkflowInstance) -> WorkflowInstanceResponse:
    return (await _instance_responses(session, [instance]))[0]


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
        definition = await get_definition_by_code(session, org_id, definition_code)
        query = query.where(
            WorkflowInstance.version_id.in_(select(WorkflowVersion.id).where(WorkflowVersion.definition_id == definition.id))
        )

    rows, page = await paginate(
        session, query, WorkflowInstance, limit, cursor, order_by=WorkflowInstance.started_at, descending=True
    )
    return PageResponse(data=await _instance_responses(session, rows), page=page)


async def _get_instance(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, for_update: bool = False
) -> WorkflowInstance:
    """`for_update` locks the row until the transaction ends: of two concurrent changes (say,
    two clicks on Approve) the second waits, then fails its version check instead of moving
    the instance a second time."""
    query = select(WorkflowInstance).where(WorkflowInstance.id == instance_id, WorkflowInstance.organization_id == org_id)
    res = await session.execute(query.with_for_update() if for_update else query)
    instance = res.scalars().first()
    if not instance:
        raise WorkflowInstanceNotFoundError(str(instance_id))
    return instance


async def get_workflow_instance(session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id)
    return await _instance_response(session, instance)


async def running_instance_ids(session: AsyncSession, subject_type: str, subject_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """Each subject's unfinished workflow instance, if it has one (the newest)."""
    if not subject_ids:
        return {}
    rows = await session.execute(
        select(WorkflowInstance.subject_id, WorkflowInstance.id)
        .where(
            WorkflowInstance.subject_type == subject_type,
            WorkflowInstance.subject_id.in_(subject_ids),
            WorkflowInstance.status.notin_(TERMINAL_STATUSES),
        )
        .order_by(WorkflowInstance.started_at)
    )
    return dict(rows.all())


# --- Moving -------------------------------------------------------------------


async def _open_stage_runs(session: AsyncSession, instance: WorkflowInstance) -> list[StageRun]:
    runs = await session.execute(select(StageRun).where(StageRun.instance_id == instance.id, StageRun.exited_at.is_(None)))
    return list(runs.scalars().all())


async def _blocked_reasons(
    session: AsyncSession,
    actor: Actor,
    transition: Transition,
    from_run: StageRun,
    context: dict,
    instance: Optional[WorkflowInstance] = None,
) -> list[str]:
    """Why `actor` can't take `transition` now; empty when they can."""
    reasons = []
    if instance is not None and instance.governs_status and instance.subject_type == TASK_SUBJECT:
        task = await session.get(Task, instance.subject_id)
        to_stage = await session.get(Stage, transition.to_stage_id)
        if task is not None and to_stage is not None:
            reasons.extend(await stage_entry_issues(session, task, to_stage.status_category))
    if transition.allowed_permission and not actor.has(transition.allowed_permission):
        reasons.append(f"Needs the '{transition.allowed_permission}' permission")
    if transition.condition and not truthy(evaluate(transition.condition, context)):
        reasons.append("Its conditions aren't met")
    from_stage = await session.get(Stage, from_run.stage_id)
    if from_stage.exit_criteria and not truthy(evaluate(from_stage.exit_criteria, context)):
        reasons.append(f"'{from_stage.name}' isn't finished: its exit criteria aren't met")
    open_tasks = await open_required_stage_tasks(session, from_run.id)
    if open_tasks:
        reasons.append(f"{len(open_tasks)} required task(s) of '{from_stage.name}' are still open")
    return reasons


async def list_available_transitions(
    session: AsyncSession, org_id: uuid.UUID, actor: Actor, instance_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[AvailableTransitionResponse]:
    instance = await _get_instance(session, org_id, instance_id)
    open_runs = {run.stage_id: run for run in await _open_stage_runs(session, instance)}

    transitions: list[Transition] = []
    if open_runs and instance.status == "running":
        transitions_res = await session.execute(
            select(Transition).where(Transition.from_stage_id.in_(open_runs)).order_by(Transition.priority.desc(), Transition.code)
        )
        transitions = list(transitions_res.scalars().all())

    page_rows = transitions[:limit]
    stage_codes = {}
    if page_rows:
        stage_codes = dict(
            (await session.execute(select(Stage.id, Stage.code).where(Stage.id.in_({t.to_stage_id for t in page_rows})))).all()
        )
    data = []
    for transition in page_rows:
        reasons = await _blocked_reasons(
            session, actor, transition, open_runs[transition.from_stage_id], instance.context or {}, instance
        )
        data.append(
            AvailableTransitionResponse(
                code=transition.code,
                name=transition.name,
                to_stage=stage_codes[transition.to_stage_id],
                requires_approval=bool(transition.approval_policy_code),
                allowed=not reasons,
                blocked_reasons=reasons,
            )
        )
    return PageResponse(data=data, page=PageMeta(next_cursor=None, has_more=len(transitions) > limit, limit=limit))


async def _move(
    session: AsyncSession,
    instance: WorkflowInstance,
    transition: Transition,
    from_run: StageRun,
    performed_by: uuid.UUID,
    reason: Optional[str],
    approval_signal_id: Optional[uuid.UUID] = None,
    people: Optional[PeopleDirectory] = None,
) -> None:
    """Leave the transition's stage and enter the next one (finishing at an end stage)."""
    from_run.exited_at = datetime.now(timezone.utc)
    from_run.exited_via_transition_id = transition.id
    from_run.status = "completed"
    to_stage = await session.get(Stage, transition.to_stage_id)
    to_run = await _enter_stage(
        session, instance, to_stage, via_transition_id=transition.id, people=people, user_id=performed_by, note=reason
    )
    session.add(
        TransitionLog(
            instance_id=instance.id,
            transition_id=transition.id,
            from_stage_run_id=from_run.id,
            to_stage_run_id=to_run.id,
            # When the instance left the stage: before an end stage marks it completed.
            performed_at=from_run.exited_at,
            performed_by=performed_by,
            reason=reason,
            approval_request_id=approval_signal_id,
        )
    )
    instance.version += 1
    await session.flush()


async def perform_transition(
    session: AsyncSession,
    org_id: uuid.UUID,
    actor: Actor,
    instance_id: uuid.UUID,
    data: TransitionRequest,
    if_match: Optional[str],
    people: Optional[PeopleDirectory] = None,
) -> TransitionResult:
    instance = await _get_instance(session, org_id, instance_id, for_update=True)
    _check_if_match(if_match, instance.version)
    if instance.status != "running":
        raise InstanceNotRunningError(instance.status)

    open_runs = {run.stage_id: run for run in await _open_stage_runs(session, instance)}
    transition = (
        await session.execute(
            select(Transition).where(Transition.code == data.transition_code, Transition.from_stage_id.in_(open_runs))
        )
    ).scalars().first()
    if not transition:
        raise TransitionNotAvailableError(data.transition_code)
    if transition.allowed_permission and not actor.has(transition.allowed_permission):
        raise PermissionDeniedError(transition.allowed_permission)

    # The patch counts for the conditions (and stays only if the transition is taken).
    context = {**(instance.context or {}), **(data.context_patch or {})}
    from_run = open_runs[transition.from_stage_id]
    reasons = await _blocked_reasons(session, actor, transition, from_run, context, instance)
    if reasons:
        raise TransitionConditionFailedError(transition.code, "; ".join(reasons) + ".")
    instance.context = context

    if transition.approval_policy_code:
        signal = PendingSignal(
            instance_id=instance.id,
            transition_id=transition.id,
            awaited_event_type=APPROVAL_SIGNAL,
            correlation_key=f"{instance.id}:{transition.code}",
            status="waiting",
        )
        session.add(signal)
        instance.status = "waiting_approval"
        instance.version += 1
        if instance.governs_status and instance.subject_type == TASK_SUBJECT:
            await workflow_step_waits(session, instance.subject_id)
        await session.flush()
        return TransitionResult(outcome="approval_pending", instance=await _instance_response(session, instance), approval_request_id=signal.id)

    await _move(session, instance, transition, from_run, actor.user_id, data.reason, people=people)
    return TransitionResult(outcome="transitioned", instance=await _instance_response(session, instance))


async def _waiting_approval(session: AsyncSession, instance: WorkflowInstance) -> PendingSignal:
    signal = (
        await session.execute(
            select(PendingSignal).where(
                PendingSignal.instance_id == instance.id,
                PendingSignal.awaited_event_type == APPROVAL_SIGNAL,
                PendingSignal.status == "waiting",
            )
        )
    ).scalars().first()
    if instance.status != "waiting_approval" or signal is None:
        raise InvalidStateTransitionError(instance.status, "approval decision")
    return signal


def _resolve(signal: PendingSignal, decision: str, user_id: uuid.UUID, note: Optional[str]) -> None:
    signal.status = decision
    signal.resolved_by = user_id
    signal.resolved_at = datetime.now(timezone.utc)
    signal.resolution_note = note


async def approve_step(
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    instance_id: uuid.UUID,
    note: Optional[str],
    if_match: Optional[str],
    people: Optional[PeopleDirectory] = None,
) -> WorkflowInstanceResponse:
    """Approve the step the instance waits for: the transition is taken now."""
    instance = await _get_instance(session, org_id, instance_id, for_update=True)
    _check_if_match(if_match, instance.version)
    signal = await _waiting_approval(session, instance)
    transition = await session.get(Transition, signal.transition_id)
    from_run = next(run for run in await _open_stage_runs(session, instance) if run.stage_id == transition.from_stage_id)

    _resolve(signal, "approved", user_id, note)
    instance.status = "running"
    await _move(session, instance, transition, from_run, user_id, note, approval_signal_id=signal.id, people=people)
    return await _instance_response(session, instance)


async def reject_step(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID, instance_id: uuid.UUID, reason: str, if_match: Optional[str]
) -> WorkflowInstanceResponse:
    """Reject the step the instance waits for: it stays in its stage and runs on."""
    instance = await _get_instance(session, org_id, instance_id, for_update=True)
    _check_if_match(if_match, instance.version)
    signal = await _waiting_approval(session, instance)
    _resolve(signal, "rejected", user_id, reason)
    instance.status = "running"
    instance.version += 1
    if instance.governs_status and instance.subject_type == TASK_SUBJECT:
        await workflow_step_waits(session, instance.subject_id)
    await session.flush()
    return await _instance_response(session, instance)


async def hold_instance(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, data: HoldRequest, if_match: Optional[str]
) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id, for_update=True)
    _check_if_match(if_match, instance.version)
    if instance.status != "running":
        raise InstanceNotRunningError(instance.status)
    instance.status = "on_hold"
    instance.version += 1
    await session.flush()
    return await _instance_response(session, instance)


async def resume_instance(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, if_match: Optional[str]
) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id, for_update=True)
    _check_if_match(if_match, instance.version)
    if instance.status != "on_hold":
        raise InvalidStateTransitionError(instance.status, "running")
    instance.status = "running"
    instance.version += 1
    await session.flush()
    return await _instance_response(session, instance)


async def cancel_instance(
    session: AsyncSession,
    org_id: uuid.UUID,
    instance_id: uuid.UUID,
    data: HoldRequest,
    if_match: Optional[str],
    user_id: Optional[uuid.UUID] = None,
) -> WorkflowInstanceResponse:
    instance = await _get_instance(session, org_id, instance_id, for_update=True)
    _check_if_match(if_match, instance.version)
    if instance.status in TERMINAL_STATUSES:
        raise InvalidStateTransitionError(instance.status, "cancelled")
    waiting = await session.execute(
        select(PendingSignal).where(PendingSignal.instance_id == instance.id, PendingSignal.status == "waiting")
    )
    for signal in waiting.scalars().all():
        signal.status = "cancelled"
    if instance.governs_status and instance.subject_type == TASK_SUBJECT:
        task = await session.get(Task, instance.subject_id)
        if task is not None:
            await cancel_task_with_workflow(session, task, user_id, data.reason or "Its workflow was cancelled")
    instance.status = "cancelled"
    instance.completed_at = datetime.now(timezone.utc)
    instance.version += 1
    await session.flush()
    return await _instance_response(session, instance)


# --- History ----------------------------------------------------------------------


async def get_instance_history(
    session: AsyncSession, org_id: uuid.UUID, instance_id: uuid.UUID, limit: int, cursor: Optional[str]
) -> PageResponse[InstanceHistoryItemResponse]:
    """The instance's timeline, oldest first: started, each move, each approval asked and
    decided, and its end. An instance's story is short, so it comes as one page."""
    instance = await _get_instance(session, org_id, instance_id)
    events = [InstanceHistoryItemResponse(at=instance.started_at, type="started", details={"by": str(instance.started_by) if instance.started_by else None})]

    logs = await session.execute(
        select(TransitionLog, Transition.code, Stage.code)
        .join(Transition, Transition.id == TransitionLog.transition_id)
        .join(Stage, Stage.id == Transition.to_stage_id)
        .where(TransitionLog.instance_id == instance.id)
    )
    for log, transition_code, stage_code in logs.all():
        events.append(
            InstanceHistoryItemResponse(
                at=log.performed_at,
                type="transition",
                stage_code=stage_code,
                details={"transition_code": transition_code, "reason": log.reason, "by": str(log.performed_by) if log.performed_by else None},
            )
        )

    signals = await session.execute(
        select(PendingSignal, Transition.code)
        .join(Transition, Transition.id == PendingSignal.transition_id)
        .where(PendingSignal.instance_id == instance.id, PendingSignal.awaited_event_type == APPROVAL_SIGNAL)
    )
    for signal, transition_code in signals.all():
        events.append(InstanceHistoryItemResponse(at=signal.created_at, type="approval_requested", details={"transition_code": transition_code}))
        if signal.resolved_at:
            events.append(
                InstanceHistoryItemResponse(
                    at=signal.resolved_at,
                    type="approval_decided",
                    details={
                        "transition_code": transition_code,
                        "decision": signal.status,
                        "note": signal.resolution_note,
                        "by": str(signal.resolved_by) if signal.resolved_by else None,
                    },
                )
            )

    if instance.completed_at:
        events.append(InstanceHistoryItemResponse(at=instance.completed_at, type=instance.status if instance.status in ("completed", "cancelled") else "completed"))

    def moment(event: InstanceHistoryItemResponse) -> datetime:
        return event.at.replace(tzinfo=None) if event.at.tzinfo else event.at

    events.sort(key=moment)
    return PageResponse(data=events, page=PageMeta(next_cursor=None, has_more=False, limit=len(events)))
