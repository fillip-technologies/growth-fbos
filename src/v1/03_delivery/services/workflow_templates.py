"""
Ready-made workflows for tasks, one per common kind of work. A company installs one: it becomes
the company's own task workflow (published as version 1), which a task type can then follow
(services/task_workflows.py) and which the company may change in later versions. The templates
here never change what a company installed.

Every stage names the task status it stands for, and every template ends in done or cancelled,
so each is ready for task types as installed. No stage moves work to another team: which team
does what differs per company, and a later version can say so.
"""
from dataclasses import dataclass
from typing import Optional
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import WorkflowTemplateNotFoundError
from schemas.workflows import (
    StageDef,
    TransitionDef,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowTemplateInstall,
    WorkflowTemplateResponse,
    WorkflowTemplateStage,
    WorkflowVersionContent,
)
from services.workflows import (
    create_workflow_definition,
    create_workflow_version,
    definition_response,
    get_definition_by_code,
    publish_workflow_version,
)

TASK_SUBJECT = "task.task"


@dataclass(frozen=True)
class Template:
    code: str
    name: str
    discipline: str
    summary: str
    # (code, name, stage type, status category), in order.
    stages: tuple[tuple[str, str, str, str], ...]
    # (code, name, from stage, to stage)
    steps: tuple[tuple[str, str, str, str], ...]

    def content(self) -> WorkflowVersionContent:
        return WorkflowVersionContent(
            stages=[
                StageDef(code=code, name=name, seq=seq, stage_type=stage_type, status_category=category)
                for seq, (code, name, stage_type, category) in enumerate(self.stages, start=1)
            ],
            transitions=[
                TransitionDef(code=code, name=name, from_=source, to=target, trigger_type="manual")
                for code, name, source, target in self.steps
            ],
        )


TEMPLATES = (
    Template(
        code="bug-fix",
        name="Bug fix",
        discipline="software",
        summary="Reported, fixed, then verified by someone else before it counts as fixed.",
        stages=(
            ("reported", "Reported", "start", "open"),
            ("fixing", "Fixing", "normal", "in_progress"),
            ("verifying", "Verifying", "normal", "in_review"),
            ("fixed", "Fixed", "end", "done"),
            ("wont_fix", "Won't fix", "end", "cancelled"),
        ),
        steps=(
            ("start_fix", "Start fixing", "reported", "fixing"),
            ("decline", "Won't fix", "reported", "wont_fix"),
            ("ready", "Ready to verify", "fixing", "verifying"),
            ("still_broken", "Still broken", "verifying", "fixing"),
            ("verified", "Verified", "verifying", "fixed"),
        ),
    ),
    Template(
        code="feature",
        name="Feature",
        discipline="software",
        summary="Planned, built, code-reviewed and tested before it ships.",
        stages=(
            ("planned", "Planned", "start", "open"),
            ("building", "Building", "normal", "in_progress"),
            ("code_review", "Code review", "normal", "in_review"),
            ("testing", "Testing", "normal", "in_review"),
            ("shipped", "Shipped", "end", "done"),
            ("dropped", "Dropped", "end", "cancelled"),
        ),
        steps=(
            ("start", "Start building", "planned", "building"),
            ("drop", "Drop", "planned", "dropped"),
            ("request_review", "Request review", "building", "code_review"),
            ("request_changes", "Request changes", "code_review", "building"),
            ("approve", "Approve", "code_review", "testing"),
            ("failed", "Failed testing", "testing", "building"),
            ("ship", "Ship", "testing", "shipped"),
        ),
    ),
    Template(
        code="creative-deliverable",
        name="Creative deliverable",
        discipline="creative",
        summary="From the brief to a draft, reviewed inside the team and then by the client.",
        stages=(
            ("brief", "Brief", "start", "open"),
            ("drafting", "Drafting", "normal", "in_progress"),
            ("internal_review", "Internal review", "normal", "in_review"),
            ("client_review", "Client review", "normal", "in_review"),
            ("approved", "Approved", "end", "done"),
            ("dropped", "Dropped", "end", "cancelled"),
        ),
        steps=(
            ("start", "Start drafting", "brief", "drafting"),
            ("drop", "Drop", "brief", "dropped"),
            ("share", "Share for review", "drafting", "internal_review"),
            ("needs_changes", "Needs changes", "internal_review", "drafting"),
            ("send_to_client", "Send to the client", "internal_review", "client_review"),
            ("client_changes", "Client wants changes", "client_review", "drafting"),
            ("client_approved", "Client approved", "client_review", "approved"),
        ),
    ),
    Template(
        code="service-ticket",
        name="Service ticket",
        discipline="operations",
        summary="Picked up, worked and resolved; or closed when there is nothing to do.",
        stages=(
            ("new", "New", "start", "open"),
            ("working", "Working on it", "normal", "in_progress"),
            ("resolved", "Resolved", "end", "done"),
            ("closed", "Closed without action", "end", "cancelled"),
        ),
        steps=(
            ("pick_up", "Pick up", "new", "working"),
            ("close", "Close without action", "new", "closed"),
            ("resolve", "Resolve", "working", "resolved"),
        ),
    ),
    Template(
        code="field-work-order",
        name="Field work order",
        discipline="operations",
        summary="Scheduled, worked on site, then signed off by the customer.",
        stages=(
            ("scheduled", "Scheduled", "start", "open"),
            ("on_site", "On site", "normal", "in_progress"),
            ("sign_off", "Customer sign-off", "normal", "in_review"),
            ("completed", "Completed", "end", "done"),
            ("cancelled", "Cancelled", "end", "cancelled"),
        ),
        steps=(
            ("arrive", "Arrive on site", "scheduled", "on_site"),
            ("cancel", "Cancel the visit", "scheduled", "cancelled"),
            ("finish", "Work finished", "on_site", "sign_off"),
            ("another_visit", "Needs another visit", "sign_off", "on_site"),
            ("signed", "Signed off", "sign_off", "completed"),
        ),
    ),
    Template(
        code="do-and-review",
        name="Do and review",
        discipline="general",
        summary="Any work someone else checks before it is done.",
        stages=(
            ("to_do", "To do", "start", "open"),
            ("doing", "Doing", "normal", "in_progress"),
            ("review", "Review", "normal", "in_review"),
            ("done", "Done", "end", "done"),
            ("dropped", "Dropped", "end", "cancelled"),
        ),
        steps=(
            ("start", "Start", "to_do", "doing"),
            ("drop", "Drop", "to_do", "dropped"),
            ("hand_in", "Hand in", "doing", "review"),
            ("send_back", "Send back", "review", "doing"),
            ("approve", "Approve", "review", "done"),
        ),
    ),
)
_BY_CODE = {template.code: template for template in TEMPLATES}


def _response(template: Template) -> WorkflowTemplateResponse:
    return WorkflowTemplateResponse(
        code=template.code,
        name=template.name,
        discipline=template.discipline,
        summary=template.summary,
        stages=[WorkflowTemplateStage(code=c, name=n, status_category=category) for c, n, _, category in template.stages],
        steps=[name for _, name, _, _ in template.steps],
    )


def list_templates(discipline: Optional[str]) -> list[WorkflowTemplateResponse]:
    return [_response(t) for t in TEMPLATES if discipline is None or t.discipline == discipline]


async def install_template(
    session: AsyncSession, org_id: uuid.UUID, template_code: str, data: WorkflowTemplateInstall
) -> WorkflowDefinitionResponse:
    """The template as the company's own task workflow, published as version 1 (409 when its code is taken)."""
    template = _BY_CODE.get(template_code)
    if template is None:
        raise WorkflowTemplateNotFoundError(template_code)
    code = data.code or template.code
    await create_workflow_definition(
        session, org_id, WorkflowDefinitionCreate(code=code, name=data.name or template.name, subject_type=TASK_SUBJECT)
    )
    await create_workflow_version(session, org_id, code, template.content())
    await publish_workflow_version(session, org_id, code, 1, '"1"')
    return await definition_response(session, await get_definition_by_code(session, org_id, code))
