from fastapi import APIRouter

from routes.analytics import router as analytics_router
from routes.audit import router as audit_router

core_router = APIRouter()
core_router.include_router(audit_router)
core_router.include_router(analytics_router)

# Mount both /v1 and /api/insight/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/insight/v1")
