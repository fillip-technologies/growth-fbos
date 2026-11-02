"""Appraisals, compensation revisions, bonuses, and promotions service layer."""

import uuid
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, SelfApprovalError, ValidationFailedError, WorkerNotFoundError
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
)
from services.identity_client import Actor
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

    # The salary on record is the base; the client's figure counts only while none is stored.
    current_struct = await get_worker_salary_structure(session, organization_id, worker_id)
    previous_ctc = current_struct.annual_ctc if current_struct else data.previous_annual_ctc

    new_ctc = revised_ctc(previous_ctc, data)

    revision = CompensationRevision(
        organization_id=organization_id,
        worker_id=worker_id,
        revision_type=data.revision_type,
        previous_annual_ctc=previous_ctc,
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
        description=f"CTC updated from {previous_ctc} to {new_ctc}. {data.notes or ''}",
        effective_date=data.effective_date,
        previous_state={"annual_ctc": str(previous_ctc)},
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


def revised_ctc(current_ctc: Decimal, data: CompensationRevisionCreate) -> Decimal:
    """The salary a revision asks for, worked out from the salary on record (never the client's figure)."""
    if data.new_annual_ctc is not None:
        return data.new_annual_ctc.quantize(Decimal("0.01"))
    if data.increment_pct is not None:
        return (current_ctc * (Decimal("1.0") + data.increment_pct / Decimal("100.0"))).quantize(Decimal("0.01"))
    if data.increment_flat_amount is not None:
        return (current_ctc + data.increment_flat_amount).quantize(Decimal("0.01"))
    raise ValidationFailedError("increment", "Must provide increment_pct, increment_flat_amount, or new_annual_ctc")


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
        status="pending",  # paid only once someone else approves it
        requested_by=approver_id,
    )
    session.add(bonus)
    await session.flush()
    await session.refresh(bonus)
    return bonus


async def get_bonus(
    session: AsyncSession, organization_id: uuid.UUID, worker_id: uuid.UUID, bonus_id: uuid.UUID, lock: bool = False
) -> BonusDisbursement:
    stmt = select(BonusDisbursement).where(
        BonusDisbursement.id == bonus_id,
        BonusDisbursement.organization_id == organization_id,
        BonusDisbursement.worker_id == worker_id,
    )
    bonus = (await session.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
    if bonus is None:
        raise WorkerNotFoundError("Bonus not found")
    return bonus


async def decide_bonus(
    session: AsyncSession, actor: Actor, worker_id: uuid.UUID, bonus_id: uuid.UUID, approved: bool
) -> BonusDisbursement:
    """Someone other than whoever awarded it approves or rejects a bonus."""
    bonus = await get_bonus(session, actor.organization_id, worker_id, bonus_id, lock=True)
    if bonus.status != "pending":
        raise ConflictError(f"This bonus is already {bonus.status}", code="BONUS_STATE")
    # A client admin may decide their own award (they could grant themselves anything); nobody else may.
    if not actor.is_superuser and bonus.requested_by == actor.user_id:
        raise SelfApprovalError("A bonus must be approved by someone other than the person who awarded it")
    bonus.status = "approved" if approved else "rejected"
    bonus.approved_by = actor.user_id
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
