import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status

from dependencies import Authorization, DatabaseSession, Delivery, OrgId, UserId, require_permission
from schemas.activity import ActivityCreate, ActivityLogged, ActivityResponse
from schemas.common import PageResponse
from services.activity_service import ActivityService
from services.activity_tasks import DeliveryCaller

router = APIRouter(prefix="/activities", tags=["activities"])

CAN_READ = Depends(require_permission("revenue.activity.read"))
CAN_WRITE = Depends(require_permission("revenue.activity.write"))


@router.get(
    "", response_model=PageResponse[ActivityResponse],
    dependencies=[CAN_READ],
)
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


@router.post(
    "", response_model=ActivityLogged, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def log_activity(
    payload: ActivityCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    authorization: Authorization,
    delivery: Delivery,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ActivityLogged:
    """
    Log a call, meeting, email, WhatsApp, site visit or note on a lead, opportunity or contract.
    `task` says what happens in tasks: recorded as a done task of yours (the default), completing
    one of your open tasks about the record, or none; a `follow_up` adds a follow-up task.
    """
    activity = await ActivityService.log_activity(
        session=session,
        org_id=org_id,
        user_id=user_id,
        payload=payload,
        delivery=DeliveryCaller(delivery, authorization),
    )
    await session.commit()
    return activity
