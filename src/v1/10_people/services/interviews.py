"""Interviews: assigning an employee to interview a candidate, and their feedback on it."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import permissions
from exceptions import ConflictError, PermissionDeniedError, ValidationFailedError, WorkerNotFoundError
from models.recruitment import Candidate, Interview, JobApplication, JobRequisition, ScorecardSubmission
from models.worker import Worker
from schemas.recruitment import InterviewCreate, InterviewFeedback, InterviewUpdate
from services.identity_client import Actor
from services.notification_client import notification_client

SCHEDULED, COMPLETED, CANCELLED = "scheduled", "completed", "cancelled"
CLOSED_APPLICATIONS = ("rejected", "hired")
INTERVIEWS_URL = "/people/interviews"


async def _application(session: AsyncSession, org_id: uuid.UUID, application_id: uuid.UUID) -> JobApplication:
    application = (
        await session.execute(
            select(JobApplication).where(JobApplication.id == application_id, JobApplication.organization_id == org_id)
        )
    ).scalar_one_or_none()
    if application is None:
        raise WorkerNotFoundError("Job application not found")
    return application


async def get_interview(session: AsyncSession, org_id: uuid.UUID, interview_id: uuid.UUID) -> Interview:
    interview = (
        await session.execute(select(Interview).where(Interview.id == interview_id, Interview.organization_id == org_id))
    ).scalar_one_or_none()
    if interview is None:
        raise WorkerNotFoundError("Interview not found")
    return interview


async def describe(session: AsyncSession, interviews: list[Interview]) -> list[dict]:
    """Interviews as response dicts, with the candidate's name and the job's title."""
    app_ids = {i.application_id for i in interviews}
    rows = {}
    if app_ids:
        result = await session.execute(
            select(JobApplication.id, Candidate.first_name, Candidate.last_name, JobRequisition.title)
            .join(Candidate, Candidate.id == JobApplication.candidate_id)
            .join(JobRequisition, JobRequisition.id == JobApplication.requisition_id)
            .where(JobApplication.id.in_(app_ids))
        )
        rows = {r.id: (f"{r.first_name} {r.last_name}".strip(), r.title) for r in result}
    described = []
    for interview in interviews:
        candidate_name, job_title = rows.get(interview.application_id, (None, None))
        described.append(
            {
                **{c.name: getattr(interview, c.name) for c in Interview.__table__.columns},
                "candidate_name": candidate_name,
                "job_title": job_title,
            }
        )
    return described


async def schedule_interview(
    session: AsyncSession, actor: Actor, application_id: uuid.UUID, data: InterviewCreate
) -> Interview:
    org = actor.organization_id
    application = await _application(session, org, application_id)
    if application.status in CLOSED_APPLICATIONS:
        raise ConflictError(f"Cannot schedule an interview on a {application.status} application")

    worker = (
        await session.execute(select(Worker).where(Worker.organization_id == org, Worker.id == data.interviewer_worker_id))
    ).scalar_one_or_none()
    if worker is None:
        raise WorkerNotFoundError(str(data.interviewer_worker_id))
    if worker.user_id is None:
        raise ValidationFailedError("interviewer_worker_id", "This employee has no login, so they cannot be an interviewer")
    if worker.status != "active":
        raise ValidationFailedError("interviewer_worker_id", "Only active employees can interview")

    interview = Interview(
        organization_id=org,
        application_id=application_id,
        round_name=data.round_name.strip(),
        interviewer_worker_id=worker.id,
        interviewer_user_id=worker.user_id,
        interviewer_name=f"{worker.first_name} {worker.last_name}".strip(),
        scheduled_at=data.scheduled_at,
        duration_minutes=data.duration_minutes,
        location=data.location,
        status=SCHEDULED,
        created_by=actor.user_id,
    )
    session.add(interview)
    await session.flush()
    await session.refresh(interview)
    return interview


async def update_interview(
    session: AsyncSession, actor: Actor, interview_id: uuid.UUID, data: InterviewUpdate
) -> Interview:
    interview = await get_interview(session, actor.organization_id, interview_id)
    if interview.status != SCHEDULED:
        raise ConflictError(f"A {interview.status} interview cannot be changed")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(interview, field, value)
    await session.flush()
    await session.refresh(interview)
    return interview


async def list_for_application(session: AsyncSession, org_id: uuid.UUID, application_id: uuid.UUID) -> list[dict]:
    await _application(session, org_id, application_id)
    interviews = list(
        (
            await session.execute(
                select(Interview)
                .where(Interview.organization_id == org_id, Interview.application_id == application_id)
                .order_by(Interview.scheduled_at)
            )
        ).scalars()
    )
    return await describe(session, interviews)


async def list_mine(session: AsyncSession, actor: Actor, status: Optional[str] = None) -> list[dict]:
    """Interviews assigned to the caller: nobody reaches another interviewer's list."""
    stmt = select(Interview).where(
        Interview.organization_id == actor.organization_id, Interview.interviewer_user_id == actor.user_id
    )
    if status:
        stmt = stmt.where(Interview.status == status)
    interviews = list((await session.execute(stmt.order_by(Interview.scheduled_at))).scalars())
    return await describe(session, interviews)


async def submit_feedback(
    session: AsyncSession, actor: Actor, interview_id: uuid.UUID, data: InterviewFeedback
) -> ScorecardSubmission:
    """Only the assigned interviewer gives feedback, once. It is blinded from other interviewers."""
    interview = await get_interview(session, actor.organization_id, interview_id)
    if interview.interviewer_user_id != actor.user_id:
        raise PermissionDeniedError(permissions.RECRUITMENT_INTERVIEW)
    if interview.status != SCHEDULED:
        raise ConflictError(f"This interview is already {interview.status}")

    scorecard = ScorecardSubmission(
        organization_id=actor.organization_id,
        application_id=interview.application_id,
        stage_name=interview.round_name,
        interviewer_id=actor.user_id,
        interviewer_name=interview.interviewer_name,
        overall_recommendation=data.overall_recommendation,
        attribute_ratings=data.attribute_ratings,
        feedback_notes=data.feedback_notes,
        is_blinded=True,
    )
    session.add(scorecard)
    await session.flush()
    interview.status = COMPLETED
    interview.scorecard_id = scorecard.id
    await session.flush()
    await session.refresh(scorecard)
    return scorecard


def notify_assigned(interview: Interview, actor: Actor, candidate_name: str) -> None:
    """Tell the interviewer. Call after the change is committed."""
    when = interview.scheduled_at.strftime("%d %b %Y, %H:%M")
    notification_client.notify(
        interview.organization_id,
        [interview.interviewer_user_id],
        event_type="people.interview.assigned.v1",
        title=f"You are interviewing {candidate_name}",
        body=f"{interview.round_name} round on {when}" + (f" at {interview.location}" if interview.location else ""),
        action_url=INTERVIEWS_URL,
        subject_type="people.interview",
        subject_id=interview.id,
        skip_user_id=actor.user_id,
    )


def notify_feedback_given(interview: Interview, candidate_name: str) -> None:
    """Tell whoever scheduled the interview that the feedback is in."""
    notification_client.notify(
        interview.organization_id,
        [interview.created_by],
        event_type="people.interview.feedback.v1",
        title=f"Feedback in for {candidate_name}",
        body=f"{interview.interviewer_name} gave feedback on the {interview.round_name} round.",
        action_url=f"/people/jobs",
        subject_type="people.interview",
        subject_id=interview.id,
        skip_user_id=interview.interviewer_user_id,
    )


async def candidate_name_for(session: AsyncSession, application_id: uuid.UUID) -> str:
    row = (
        await session.execute(
            select(Candidate.first_name, Candidate.last_name)
            .join(JobApplication, JobApplication.candidate_id == Candidate.id)
            .where(JobApplication.id == application_id)
        )
    ).first()
    return f"{row.first_name} {row.last_name}".strip() if row else "a candidate"


