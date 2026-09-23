from fastapi import APIRouter

core_router = APIRouter()


@core_router.get("/ping", tags=["system"])
async def ping() -> dict:
    return {"message": "pong"}

# Include route modules here as the service grows (Audit, Analytics):
# from routes.audit import router as audit_router
# core_router.include_router(audit_router, prefix="/audit-events", tags=["audit"])

# Mount both /v1 and /api/insight/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/insight/v1")
