import uuid

from fastapi import APIRouter, Depends, status

import permissions
import services.identity_sync as identity_sync
from dependencies import CurrentActor, DatabaseSession, require_permission, worker_in_reach
from schemas.identity_sync import IdentitySyncStatus
from services.worker_documents import ensure_worker

router = APIRouter(tags=["identity-sync"])

CAN_READ = Depends(require_permission(permissions.EMPLOYEE_READ))
CAN_MANAGE = Depends(require_permission(permissions.EMPLOYEE_MANAGE))
IN_READ = Depends(worker_in_reach(permissions.EMPLOYEE_READ))
IN_MANAGE = Depends(worker_in_reach(permissions.EMPLOYEE_MANAGE))


@router.get("/workers/{worker_id}/identity-sync", response_model=IdentitySyncStatus, dependencies=[CAN_READ, IN_READ])
async def get_identity_sync(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID):
    """Whether this person's login matches their job: in sync, waiting, failed, or what differs."""
    worker = await ensure_worker(session, actor.organization_id, worker_id)
    return await identity_sync.sync_status(session, worker)


@router.post(
    "/workers/{worker_id}/identity-sync-requests",
    response_model=IdentitySyncStatus,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[CAN_MANAGE, IN_MANAGE],
)
async def request_identity_sync(session: DatabaseSession, actor: CurrentActor, worker_id: uuid.UUID):
    """Send this person's login what People holds for it again (after fixing a role in Identity, say)."""
    worker = await ensure_worker(session, actor.organization_id, worker_id)
    await identity_sync.queue_sync(session, worker)
    await session.commit()
    return await identity_sync.sync_status(session, worker)
