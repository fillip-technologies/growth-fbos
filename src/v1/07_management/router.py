from fastapi import APIRouter

core_router = APIRouter()


@core_router.get("/ping", tags=["system"])
async def ping() -> dict:
    return {"message": "pong"}

# Include route modules here as the service grows (Planning, Performance/KPIs, Resources and capacity):
# from routes.planning import router as planning_router
# core_router.include_router(planning_router, prefix="/kpi-targets", tags=["planning"])

# Mount both /v1 and /api/management/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/management/v1")
