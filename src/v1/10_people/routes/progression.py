"""Appraisals, Hikes, Bonuses, and Promotions API routes."""

import uuid
from typing import Annotated, List

from fastapi import Depends, Query
from pydantic import ValidationError as PydanticValidationError

from fastapi import APIRouter, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId, get_identity_client
from exceptions import ValidationFailedError
from permissions import COMPENSATION_MANAGE, COMPENSATION_READ, EMPLOYEE_MANAGE
from schemas.role_change import RoleChangeCreate, RoleChangeResponse
from services.access_scope import refuse_self_decision, worker_in_scope
from services.identity_client import IdentityClient
from services.payroll_service import get_worker_salary_structure
import services.role_changes as role_changes
from schemas.progression import (
    BonusDisbursementCreate,
    BonusDisbursementResponse,
    CompensationRevisionCreate,
    CompensationRevisionResponse,
    PromotionCreate,
    PromotionResponse,
)
from services.progression_service import (
    award_bonus,
    decide_bonus,
    revised_ctc,
    list_bonuses,
    list_compensation_revisions,
    list_promotions,
)

router = APIRouter(tags=["Progression & Appraisals"])


def _role_change_request(**fields) -> RoleChangeCreate:
    """The role change a progression request becomes; what it cannot carry answers 422, not a server error."""
    try:
        return RoleChangeCreate(**fields)
    except PydanticValidationError as error:
        first = error.errors()[0]
        raise ValidationFailedError(str(first["loc"][-1]) if first.get("loc") else "body", first["msg"]) from None


# ---------------------------------------------------------
# Compensation Revisions (Hikes)
# ---------------------------------------------------------
@router.post(
    "/workers/{id}/compensation-revisions",
    response_model=RoleChangeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_compensation_revision_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    data: CompensationRevisionCreate,
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
):
    """
    Ask for a salary revision. It is a role change: others approve it (finance among them) before the new
    salary takes effect, and the revision is recorded then. Answers the waiting request.
    """
    actor.require_permission(COMPENSATION_MANAGE)
    refuse_self_decision(actor, await worker_in_scope(session, actor, id, COMPENSATION_MANAGE), "salary revision")
    current = await get_worker_salary_structure(session, org_id, id)
    if current is None:
        raise ValidationFailedError("previous_annual_ctc", "Set this employee's salary first, then revise it")
    request = _role_change_request(
        change_type="salary_revision",
        revision_type=data.revision_type,
        effective_date=data.effective_date,
        reason=(data.notes or "").strip() or data.revision_type.replace("_", " ").capitalize(),
        new_annual_ctc=revised_ctc(current.annual_ctc, data),
        letter_doc_id=data.increment_letter_doc_id,
    )
    change = await role_changes.request_change(session, actor, identity, id, request)
    await session.commit()
    return (await role_changes.to_responses(session, actor, [change]))[0]


@router.get(
    "/workers/{id}/compensation-revisions",
    response_model=List[CompensationRevisionResponse],
)
async def list_compensation_revisions_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(COMPENSATION_READ)
    await worker_in_scope(session, actor, id, COMPENSATION_READ)
    return await list_compensation_revisions(session, org_id, id)


# ---------------------------------------------------------
# Promotions
# ---------------------------------------------------------
@router.post(
    "/workers/{id}/promotions",
    response_model=RoleChangeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_promotion_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    data: PromotionCreate,
    identity: Annotated[IdentityClient, Depends(get_identity_client)],
):
    """
    Ask for a promotion. It is a role change: approved step by step, it then changes the title and leaves the
    promotion record. Answers the waiting request.
    """
    actor.require_permission(EMPLOYEE_MANAGE)
    refuse_self_decision(actor, await worker_in_scope(session, actor, id, EMPLOYEE_MANAGE), "promotion")
    request = _role_change_request(
        change_type="promotion",
        effective_date=data.effective_date,
        reason=f"Promotion to {data.new_title} ({data.new_level})",
        new_designation=data.new_title,
        new_job_profile_id=data.new_job_profile_id,
        new_level=data.new_level,
        letter_doc_id=data.promotion_letter_doc_id,
    )
    change = await role_changes.request_change(session, actor, identity, id, request)
    await session.commit()
    return (await role_changes.to_responses(session, actor, [change]))[0]


@router.get(
    "/workers/{id}/promotions",
    response_model=List[PromotionResponse],
)
async def list_promotions_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(COMPENSATION_READ)
    await worker_in_scope(session, actor, id, COMPENSATION_READ)
    return await list_promotions(session, org_id, id)


# ---------------------------------------------------------
# Bonuses
# ---------------------------------------------------------
@router.post(
    "/workers/{id}/bonuses",
    response_model=BonusDisbursementResponse,
    status_code=status.HTTP_201_CREATED,
)
async def award_bonus_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    data: BonusDisbursementCreate,
):
    actor.require_permission(COMPENSATION_MANAGE)
    refuse_self_decision(actor, await worker_in_scope(session, actor, id, COMPENSATION_MANAGE), "bonus")
    result = await award_bonus(session, org_id, id, user_id, data)
    await session.commit()
    return result


@router.get(
    "/workers/{id}/bonuses",
    response_model=List[BonusDisbursementResponse],
)
async def list_bonuses_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
):
    actor.require_permission(COMPENSATION_READ)
    await worker_in_scope(session, actor, id, COMPENSATION_READ)
    return await list_bonuses(session, org_id, id)


@router.patch(
    "/workers/{id}/bonuses/{bonus_id}/approve",
    response_model=BonusDisbursementResponse,
)
async def decide_bonus_endpoint(
    id: uuid.UUID,
    bonus_id: uuid.UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    approved: bool = Query(True),
):
    """Approve (or reject with `approved=false`) a bonus someone else awarded. Only approved bonuses are paid."""
    actor.require_permission(COMPENSATION_MANAGE)
    refuse_self_decision(actor, await worker_in_scope(session, actor, id, COMPENSATION_MANAGE), "bonus")
    result = await decide_bonus(session, actor, id, bonus_id, approved)
    await session.commit()
    return result
