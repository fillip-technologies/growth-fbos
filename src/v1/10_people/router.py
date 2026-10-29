from fastapi import APIRouter

from routes.positions import router as positions_router
from routes.workers import router as workers_router

core_router = APIRouter()
core_router.include_router(positions_router)
core_router.include_router(workers_router)

# Mount both /v1 and /api/people/v1 for complete gateway & direct compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/people/v1")
