from fastapi import APIRouter

from routes.approvals import router as approvals_router
from routes.sla import router as sla_router

core_router = APIRouter()
core_router.include_router(approvals_router)
core_router.include_router(sla_router)

# Mount both /v1 and /api/control/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/control/v1")
