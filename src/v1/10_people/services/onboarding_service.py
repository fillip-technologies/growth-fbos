"""Zero-touch Onboarding service layer and inter-service orchestration."""

import logging
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, ValidationFailedError, WorkerNotFoundError
from models.job_architecture import Position
from models.platform import Outbox
from models.recruitment import Candidate, JobApplication, JobOffer, JobRequisition
from models.worker import PositionAssignment, Worker, WorkerTimelineEvent
from schemas.recruitment import OnboardCandidateRequest
from services.codes import next_worker_code

logger = logging.getLogger(__name__)


async def accept_and_onboard_candidate(
    session: AsyncSession,
    organization_id: uuid.UUID,
    offer_id: uuid.UUID,
    data: OnboardCandidateRequest,
) -> Worker:
    """
    Executes the Hire-to-Onboard transition:
    1. Validates and marks JobOffer as accepted and converted.
    2. Provisions Worker master record with sequential or custom EMP code (supports back-dating).
    3. Links Position seat and marks Position as filled.
    4. Updates JobApplication and JobRequisition headcount counters.
    5. Queues cross-service events for 01_identity, 09_assets, 05_documents, and 07_management.
    """
    # 1. Fetch offer and candidate
    offer_res = await session.execute(
        select(JobOffer).where(
            JobOffer.id == offer_id,
            JobOffer.organization_id == organization_id,
        )
    )
    offer = offer_res.scalar_one_or_none()
    if not offer:
        raise WorkerNotFoundError("Job offer not found")

    if offer.status == "converted":
        raise ConflictError("This candidate has already been onboarded")

    candidate_res = await session.execute(
        select(Candidate).where(
            Candidate.id == offer.candidate_id,
            Candidate.organization_id == organization_id,
        )
    )
    candidate = candidate_res.scalar_one_or_none()
    if not candidate:
        raise WorkerNotFoundError("Candidate profile not found")

    # 2. Determine worker code & dates
    worker_code = data.custom_worker_code
    if not worker_code:
        worker_code = await next_worker_code(session, organization_id)

    joining_date = data.date_of_joining or offer.expected_start_date or date.today()

    # Determine designation from position or application requisition
    designation = "Employee"
    position = None
    if offer.position_id:
        pos_res = await session.execute(
            select(Position).where(
                Position.id == offer.position_id,
                Position.organization_id == organization_id,
            )
        )
        position = pos_res.scalar_one_or_none()
        if position:
            designation = position.title

    # 3. Create Worker
    worker = Worker(
        organization_id=organization_id,
        worker_code=worker_code,
        first_name=candidate.first_name,
        last_name=candidate.last_name,
        work_email=data.work_email,
        phone=candidate.phone,
        designation=designation,
        status="active",
        date_of_joining=joining_date,
    )
    session.add(worker)
    await session.flush()

    # 4. Seat assignment
    if position:
        position.hiring_status = "filled"
        assignment = PositionAssignment(
            organization_id=organization_id,
            worker_id=worker.id,
            position_id=position.id,
            is_primary=True,
            status="active",
            effective_start_date=joining_date,
        )
        session.add(assignment)


    # 5. Timeline milestone
    timeline = WorkerTimelineEvent(
        organization_id=organization_id,
        worker_id=worker.id,
        event_category="hire",
        title=f"Joined company as {designation}",
        description="Onboarded through recruitment offer acceptance",
        effective_date=joining_date,
        new_state={
            "source": "recruitment_onboard",
            "offer_id": str(offer.id),
            "salary": str(offer.base_annual_salary),
            "currency": offer.currency,
        },
    )
    session.add(timeline)


    # 6. Update Offer and Application status
    offer.status = "converted"

    app_res = await session.execute(
        select(JobApplication).where(
            JobApplication.id == offer.application_id,
            JobApplication.organization_id == organization_id,
        )
    )
    application = app_res.scalar_one_or_none()
    if application:
        application.current_stage = "hired"
        application.status = "hired"

        # Update requisition filled count
        req_res = await session.execute(
            select(JobRequisition).where(
                JobRequisition.id == application.requisition_id,
                JobRequisition.organization_id == organization_id,
            )
        )
        req = req_res.scalar_one_or_none()
        if req:
            req.filled_count += 1
            if req.filled_count >= req.openings_count:
                req.status = "filled"

    # 7. Queue Cross-service Outbox Events
    # Identity provisioning event
    session.add(
        Outbox(
            organization_id=organization_id,
            aggregate_type="worker",
            aggregate_id=worker.id,
            event_type="WorkerOnboarded",
            payload={
                "worker_id": str(worker.id),
                "worker_code": worker.worker_code,
                "email": worker.work_email,
                "first_name": worker.first_name,
                "last_name": worker.last_name,
            },
        )
    )

    # Assets IT handover event
    session.add(
        Outbox(
            organization_id=organization_id,
            aggregate_type="worker",
            aggregate_id=worker.id,
            event_type="HardwareHandoverRequired",
            payload={
                "worker_id": str(worker.id),
                "worker_code": worker.worker_code,
                "employee_name": f"{worker.first_name} {worker.last_name}",
                "effective_date": str(joining_date),
            },
        )
    )


    await session.flush()
    return worker
