from fastapi import APIRouter

from routes.screens import router as screens_router

core_router = APIRouter()
core_router.include_router(screens_router, tags=["aggregated-screens"])

# Mount both /v1 and /api/bff/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/bff/v1")
