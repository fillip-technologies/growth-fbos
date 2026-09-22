import uuid
from typing import Optional

from fastapi import APIRouter, Header, Query, status

from dependencies import DatabaseSession, OrgId, UserId
from schemas.activity import ActivityCreate, ActivityResponse
from schemas.common import PageResponse
from services.activity_service import ActivityService

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=PageResponse[ActivityResponse])
async def list_activities(
    session: DatabaseSession,
    org_id: OrgId,
    subject_type: Optional[str] = Query(None, description="Filter by subject type e.g. commercial.lead, commercial.opportunity"),
    subject_id: Optional[uuid.UUID] = Query(None, description="Filter by subject uuid"),
    owner_user_id: Optional[uuid.UUID] = Query(None, description="Filter by activity owner user"),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[ActivityResponse]:
    """List CRM activities with keyset cursor pagination."""
    return await ActivityService.list_activities(
        session=session,
        org_id=org_id,
        subject_type=subject_type,
        subject_id=subject_id,
        owner_user_id=owner_user_id,
        limit=limit,
        cursor=cursor,
    )


@router.post("", response_model=ActivityResponse, status_code=status.HTTP_201_CREATED)
async def log_activity(
    payload: ActivityCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ActivityResponse:
    """Log an interaction or task activity across any CRM subject."""
    activity = await ActivityService.log_activity(
        session=session,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
    )
    await session.commit()
    return activity
