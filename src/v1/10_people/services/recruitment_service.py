"""Recruitment and ATS service layer."""

import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.job_architecture import JobProfile, PayBand, Position
from models.recruitment import (
    Candidate,
    JobApplication,
    JobOffer,
    JobRequisition,
    ScorecardSubmission,
)
from schemas.recruitment import (
    CandidateCreate,
    CandidateUpdate,
    JobOfferCreate,
    JobRequisitionCreate,
    JobRequisitionUpdate,
    ScorecardCreate,
)
from services.codes import next_requisition_code


async def create_requisition(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: JobRequisitionCreate,
) -> JobRequisition:
    req_code = await next_requisition_code(session, organization_id)
    req = JobRequisition(
        organization_id=organization_id,
        requisition_code=req_code,
        title=data.title,
        position_id=data.position_id,
        department=data.department,
        location=data.location,
        employment_type=data.employment_type,
        hiring_manager_id=data.hiring_manager_id,
        recruiter_id=data.recruiter_id,
        openings_count=data.openings_count,
        job_description=data.job_description,
        target_start_date=data.target_start_date,
        status="open",
    )
    session.add(req)
    await session.flush()
    await session.refresh(req)
    return req


async def list_requisitions(
    session: AsyncSession,
    organization_id: uuid.UUID,
    status: Optional[str] = None,
    department: Optional[str] = None,
) -> List[JobRequisition]:
    query = select(JobRequisition).where(JobRequisition.organization_id == organization_id)
    if status:
        query = query.where(JobRequisition.status == status)
    if department:
        query = query.where(JobRequisition.department == department)
    query = query.order_by(desc(JobRequisition.created_at))
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_requisition(
    session: AsyncSession,
    organization_id: uuid.UUID,
    requisition_id: uuid.UUID,
) -> JobRequisition:
    query = select(JobRequisition).where(
        JobRequisition.id == requisition_id,
        JobRequisition.organization_id == organization_id,
    )
    result = await session.execute(query)
    req = result.scalar_one_or_none()
    if not req:
        raise WorkerNotFoundError("Job requisition not found")
    return req


async def update_requisition(
    session: AsyncSession,
    organization_id: uuid.UUID,
    requisition_id: uuid.UUID,
    data: JobRequisitionUpdate,
) -> JobRequisition:
    req = await get_requisition(session, organization_id, requisition_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(req, field, value)
    await session.flush()
    await session.refresh(req)
    return req


async def create_candidate(
    session: AsyncSession,
    organization_id: uuid.UUID,
    data: CandidateCreate,
) -> Candidate:
    candidate = Candidate(
        organization_id=organization_id,
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        resume_doc_id=data.resume_doc_id,
        linkedin_url=data.linkedin_url,
        source=data.source,
        tags=data.tags,
    )
    session.add(candidate)
    await session.flush()
    await session.refresh(candidate)
    return candidate


async def list_candidates(
    session: AsyncSession,
    organization_id: uuid.UUID,
    search: Optional[str] = None,
) -> List[Candidate]:
    query = select(Candidate).where(Candidate.organization_id == organization_id)
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            (Candidate.first_name.ilike(search_filter))
            | (Candidate.last_name.ilike(search_filter))
            | (Candidate.email.ilike(search_filter))
        )
    query = query.order_by(desc(Candidate.created_at))
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_candidate(
    session: AsyncSession,
    organization_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> Candidate:
    query = select(Candidate).where(
        Candidate.id == candidate_id,
        Candidate.organization_id == organization_id,
    )
    result = await session.execute(query)
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise WorkerNotFoundError("Candidate not found")
    return candidate


async def apply_for_job(
    session: AsyncSession,
    organization_id: uuid.UUID,
    candidate_id: uuid.UUID,
    requisition_id: uuid.UUID,
) -> JobApplication:
    # Verify candidate and requisition
    await get_candidate(session, organization_id, candidate_id)
    await get_requisition(session, organization_id, requisition_id)

    # Check for existing application
    existing = await session.execute(
        select(JobApplication).where(
            JobApplication.organization_id == organization_id,
            JobApplication.candidate_id == candidate_id,
            JobApplication.requisition_id == requisition_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Candidate has already applied to this requisition")

    application = JobApplication(
        organization_id=organization_id,
        candidate_id=candidate_id,
        requisition_id=requisition_id,
        current_stage="applied",
        status="active",
    )
    session.add(application)
    await session.flush()
    await session.refresh(application)
    return application


async def list_applications(
    session: AsyncSession,
    organization_id: uuid.UUID,
    requisition_id: Optional[uuid.UUID] = None,
    stage: Optional[str] = None,
) -> List[JobApplication]:
    query = select(JobApplication).where(JobApplication.organization_id == organization_id)
    if requisition_id:
        query = query.where(JobApplication.requisition_id == requisition_id)
    if stage:
        query = query.where(JobApplication.current_stage == stage)
    query = query.order_by(desc(JobApplication.applied_at))
    result = await session.execute(query)
    return list(result.scalars().all())


async def transition_application_stage(
    session: AsyncSession,
    organization_id: uuid.UUID,
    application_id: uuid.UUID,
    stage: str,
    rejection_reason: Optional[str] = None,
) -> JobApplication:
    result = await session.execute(
        select(JobApplication).where(
            JobApplication.id == application_id,
            JobApplication.organization_id == organization_id,
        )
    )
    application = result.scalar_one_or_none()
    if not application:
        raise WorkerNotFoundError("Job application not found")

    application.current_stage = stage
    if stage == "rejected":
        application.status = "rejected"
        application.rejection_reason = rejection_reason
    elif stage == "offer":
        application.status = "offered"
    elif stage == "hired":
        application.status = "hired"

    await session.flush()
    await session.refresh(application)
    return application


async def submit_scorecard(
    session: AsyncSession,
    organization_id: uuid.UUID,
    application_id: uuid.UUID,
    data: ScorecardCreate,
) -> ScorecardSubmission:
    # Ensure application exists
    app_result = await session.execute(
        select(JobApplication).where(
            JobApplication.id == application_id,
            JobApplication.organization_id == organization_id,
        )
    )
    if not app_result.scalar_one_or_none():
        raise WorkerNotFoundError("Job application not found")

    scorecard = ScorecardSubmission(
        organization_id=organization_id,
        application_id=application_id,
        stage_name=data.stage_name,
        interviewer_name=data.interviewer_name,
        interviewer_id=data.interviewer_id,
        overall_recommendation=data.overall_recommendation,
        attribute_ratings=data.attribute_ratings,
        feedback_notes=data.feedback_notes,
        is_blinded=data.is_blinded,
    )
    session.add(scorecard)
    await session.flush()
    await session.refresh(scorecard)
    return scorecard


async def list_scorecards(
    session: AsyncSession,
    organization_id: uuid.UUID,
    application_id: uuid.UUID,
) -> List[ScorecardSubmission]:
    result = await session.execute(
        select(ScorecardSubmission).where(
            ScorecardSubmission.application_id == application_id,
            ScorecardSubmission.organization_id == organization_id,
        ).order_by(desc(ScorecardSubmission.created_at))
    )
    return list(result.scalars().all())


async def create_offer(
    session: AsyncSession,
    organization_id: uuid.UUID,
    application_id: uuid.UUID,
    data: JobOfferCreate,
) -> JobOffer:
    app_res = await session.execute(
        select(JobApplication).where(
            JobApplication.id == application_id,
            JobApplication.organization_id == organization_id,
        )
    )
    application = app_res.scalar_one_or_none()
    if not application:
        raise WorkerNotFoundError("Job application not found")

    is_out_of_band = False
    out_of_band_reason = data.out_of_band_reason

    # Validate against position pay band if position provided
    if data.position_id:
        pos_res = await session.execute(
            select(Position).options(
                selectinload(Position.job_profile).selectinload(JobProfile.pay_band)
            ).where(
                Position.id == data.position_id,
                Position.organization_id == organization_id,
            )
        )
        pos = pos_res.scalar_one_or_none()
        if pos and pos.job_profile and pos.job_profile.pay_band:
            band = pos.job_profile.pay_band
            if data.base_annual_salary > band.maximum_annual:
                is_out_of_band = True
                out_of_band_reason = (
                    out_of_band_reason or f"Offered salary {data.base_annual_salary} exceeds band maximum {band.maximum_annual}"
                )
            elif data.base_annual_salary < band.minimum_annual:
                is_out_of_band = True
                out_of_band_reason = (
                    out_of_band_reason or f"Offered salary {data.base_annual_salary} is below band minimum {band.minimum_annual}"
                )

    offer = JobOffer(
        organization_id=organization_id,
        application_id=application_id,
        candidate_id=data.candidate_id,
        position_id=data.position_id,
        base_annual_salary=data.base_annual_salary,
        sign_on_bonus=data.sign_on_bonus,
        currency=data.currency,
        expected_start_date=data.expected_start_date,
        is_out_of_band=is_out_of_band,
        out_of_band_reason=out_of_band_reason,
        offer_letter_doc_id=data.offer_letter_doc_id,
        status="sent",
    )
    session.add(offer)
    application.current_stage = "offer"
    application.status = "offered"
    await session.flush()
    await session.refresh(offer)
    return offer
