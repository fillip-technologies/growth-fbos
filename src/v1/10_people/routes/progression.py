"""Appraisals, Hikes, Bonuses, and Promotions API routes."""

import uuid
from typing import List

from fastapi import APIRouter, status

from dependencies import CurrentActor, DatabaseSession, OrgId, UserId
from permissions import COMPENSATION_MANAGE, COMPENSATION_READ, EMPLOYEE_MANAGE
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
    list_bonuses,
    list_compensation_revisions,
    list_promotions,
    record_compensation_revision,
    record_promotion,
)

router = APIRouter(tags=["Progression & Appraisals"])


# ---------------------------------------------------------
# Compensation Revisions (Hikes)
# ---------------------------------------------------------
@router.post(
    "/workers/{id}/compensation-revisions",
    response_model=CompensationRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_compensation_revision_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    data: CompensationRevisionCreate,
):
    actor.require_permission(COMPENSATION_MANAGE)
    result = await record_compensation_revision(session, org_id, id, user_id, data)
    await session.commit()
    return result


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
    return await list_compensation_revisions(session, org_id, id)


# ---------------------------------------------------------
# Promotions
# ---------------------------------------------------------
@router.post(
    "/workers/{id}/promotions",
    response_model=PromotionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_promotion_endpoint(
    id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    actor: CurrentActor,
    data: PromotionCreate,
):
    actor.require_permission(EMPLOYEE_MANAGE)
    result = await record_promotion(session, org_id, id, user_id, data)
    await session.commit()
    return result


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
    return await list_bonuses(session, org_id, id)
