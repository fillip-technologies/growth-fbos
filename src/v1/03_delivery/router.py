from fastapi import APIRouter

from routes.tasks import router as tasks_router
from routes.work_units import router as work_units_router
from routes.workflows import router as workflows_router

core_router = APIRouter()
core_router.include_router(work_units_router)
core_router.include_router(workflows_router)
core_router.include_router(tasks_router)

# Mount both /v1 and /api/delivery/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/delivery/v1")
