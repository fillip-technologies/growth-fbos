from fastapi import APIRouter

core_router = APIRouter()

# Include route modules here as the service grows (Approvals, SLA):
# from routes.requests import router as requests_router
# core_router.include_router(requests_router, prefix="/approval-requests", tags=["approval-requests"])
# from routes.sla import router as sla_router
# core_router.include_router(sla_router, prefix="/sla", tags=["sla"])

# Mount both /v1 and /api/control/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/control/v1")
