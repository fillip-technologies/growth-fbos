from fastapi import APIRouter

from routes.management import router as management_router

core_router = APIRouter()
core_router.include_router(management_router)

# Mount both /v1 and /api/management/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/management/v1")
