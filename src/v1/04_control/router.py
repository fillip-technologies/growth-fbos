from fastapi import APIRouter

from dependencies import DatabaseSession, OrgId, UserId
from routes.approvals import router as approvals_router
from routes.sla import router as sla_router
import services.approvals as approval_service

core_router = APIRouter()
core_router.include_router(approvals_router)
core_router.include_router(sla_router)


@core_router.get("/approval-requests/summary")
@core_router.get("/approvals/requests/summary")
async def get_approvals_summary(
    session: DatabaseSession,
    org_id: OrgId,
    caller_user_id: UserId,
) -> dict:
    return await approval_service.get_approvals_summary(session, org_id, caller_user_id)


# Mount both /v1 and /api/control/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/control/v1")

