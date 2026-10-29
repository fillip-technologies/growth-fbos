"""Appraisals, compensation revisions, bonuses, and promotions service layer."""

import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ValidationFailedError, WorkerNotFoundError
from models.payroll import SalaryStructure
from models.progression import (
    BonusDisbursement,
    CompensationRevision,
    PromotionRecord,
)
from models.worker import Worker, WorkerTimelineEvent
from schemas.progression import (
    BonusDisbursementCreate,
    CompensationRevisionCreate,
    PromotionCreate,
)
from services.payroll_service import get_worker_salary_structure


async def record_compensation_revision(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
    approver_id: uuid.UUID,
    data: CompensationRevisionCreate,
) -> CompensationRevision:
    worker = await session.get(Worker, worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    new_ctc = data.new_annual_ctc
    if new_ctc is None:
        if data.increment_pct is not None:
            new_ctc = data.previous_annual_ctc * (Decimal("1.0") + (data.increment_pct / Decimal("100.0")))
        elif data.increment_flat_amount is not None:
            new_ctc = data.previous_annual_ctc + data.increment_flat_amount
        else:
            raise ValidationFailedError("increment", "Must provide increment_pct, increment_flat_amount, or new_annual_ctc")

    new_ctc = new_ctc.quantize(Decimal("0.01"))

    revision = CompensationRevision(
        organization_id=organization_id,
        worker_id=worker_id,
        revision_type=data.revision_type,
        previous_annual_ctc=data.previous_annual_ctc,
        increment_pct=data.increment_pct,
        increment_flat_amount=data.increment_flat_amount,
        new_annual_ctc=new_ctc,
        effective_date=data.effective_date,
        notes=data.notes,
        increment_letter_doc_id=data.increment_letter_doc_id,
        approved_by=approver_id,
    )
    session.add(revision)

    # Update active SalaryStructure
    current_struct = await get_worker_salary_structure(session, organization_id, worker_id)
    if current_struct:
        ratio = new_ctc / current_struct.annual_ctc if current_struct.annual_ctc > Decimal("0.0") else Decimal("1.0")
        current_struct.is_current = False

        new_struct = SalaryStructure(
            organization_id=organization_id,
            worker_id=worker_id,
            currency=current_struct.currency,
            basic_salary=(current_struct.basic_salary * ratio).quantize(Decimal("0.01")),
            hra=(current_struct.hra * ratio).quantize(Decimal("0.01")),
            special_allowance=(current_struct.special_allowance * ratio).quantize(Decimal("0.01")),
            pf_deduction=current_struct.pf_deduction,
            pt_deduction=current_struct.pt_deduction,
            tds_tax=(current_struct.tds_tax * ratio).quantize(Decimal("0.01")),
            gross_monthly=(current_struct.gross_monthly * ratio).quantize(Decimal("0.01")),
            annual_ctc=new_ctc,
            effective_from=data.effective_date,
            is_current=True,
        )
        session.add(new_struct)

    # Add milestone to Worker timeline
    pct_text = f" ({data.increment_pct}% hike)" if data.increment_pct else ""
    timeline = WorkerTimelineEvent(
        organization_id=organization_id,
        worker_id=worker_id,
        event_category="salary_revision",
        title=f"Compensation Revision: {data.revision_type}{pct_text}",
        description=f"CTC updated from {data.previous_annual_ctc} to {new_ctc}. {data.notes or ''}",
        effective_date=data.effective_date,
        previous_state={"annual_ctc": str(data.previous_annual_ctc)},
        new_state={"annual_ctc": str(new_ctc)},
    )
    session.add(timeline)

    await session.flush()
    await session.refresh(revision)
    return revision


async def list_compensation_revisions(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> List[CompensationRevision]:
    result = await session.execute(
        select(CompensationRevision).where(
            CompensationRevision.organization_id == organization_id,
            CompensationRevision.worker_id == worker_id,
        ).order_by(desc(CompensationRevision.effective_date))
    )
    return list(result.scalars().all())


async def record_promotion(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
    approver_id: uuid.UUID,
    data: PromotionCreate,
) -> PromotionRecord:
    worker = await session.get(Worker, worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    old_title = worker.designation

    promo = PromotionRecord(
        organization_id=organization_id,
        worker_id=worker_id,
        previous_job_profile_id=data.previous_job_profile_id,
        new_job_profile_id=data.new_job_profile_id,
        previous_level=data.previous_level,
        new_level=data.new_level,
        previous_title=data.previous_title or old_title,
        new_title=data.new_title,
        effective_date=data.effective_date,
        promotion_letter_doc_id=data.promotion_letter_doc_id,
        approved_by=approver_id,
    )
    session.add(promo)

    # Update worker title
    worker.designation = data.new_title
    worker.job_title = data.new_title

    # Add milestone to Worker timeline
    timeline = WorkerTimelineEvent(
        organization_id=organization_id,
        worker_id=worker_id,
        event_category="promotion",
        title=f"Promoted to {data.new_title} ({data.new_level})",
        description=f"Promoted from {data.previous_title or old_title} to {data.new_title}",
        effective_date=data.effective_date,
        previous_state={"designation": data.previous_title or old_title, "level": data.previous_level},
        new_state={"designation": data.new_title, "level": data.new_level},
    )
    session.add(timeline)

    await session.flush()
    await session.refresh(promo)
    return promo


async def list_promotions(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> List[PromotionRecord]:
    result = await session.execute(
        select(PromotionRecord).where(
            PromotionRecord.organization_id == organization_id,
            PromotionRecord.worker_id == worker_id,
        ).order_by(desc(PromotionRecord.effective_date))
    )
    return list(result.scalars().all())


async def award_bonus(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
    approver_id: uuid.UUID,
    data: BonusDisbursementCreate,
) -> BonusDisbursement:
    worker = await session.get(Worker, worker_id)
    if not worker or worker.organization_id != organization_id:
        raise WorkerNotFoundError("Worker not found")

    bonus = BonusDisbursement(
        organization_id=organization_id,
        worker_id=worker_id,
        bonus_type=data.bonus_type,
        amount=data.amount,
        currency=data.currency,
        payout_month=data.payout_month,
        reason=data.reason,
        status="approved",
        approved_by=approver_id,
    )
    session.add(bonus)
    await session.flush()
    await session.refresh(bonus)
    return bonus


async def list_bonuses(
    session: AsyncSession,
    organization_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> List[BonusDisbursement]:
    result = await session.execute(
        select(BonusDisbursement).where(
            BonusDisbursement.organization_id == organization_id,
            BonusDisbursement.worker_id == worker_id,
        ).order_by(desc(BonusDisbursement.created_at))
    )
    return list(result.scalars().all())
