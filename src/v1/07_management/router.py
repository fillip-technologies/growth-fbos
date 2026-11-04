from fastapi import APIRouter

from routes.allocations import router as allocations_router
from routes.budgets import router as budgets_router
from routes.internal import router as internal_router
from routes.kpis import router as kpis_router
from routes.planning import router as planning_router
from routes.resources import router as resources_router
from routes.scenarios import router as scenarios_router
from routes.summaries import router as summaries_router

core_router = APIRouter()
for module_router in (
    planning_router,
    kpis_router,
    budgets_router,
    scenarios_router,
    resources_router,
    allocations_router,
    summaries_router,
    internal_router,
):
    core_router.include_router(module_router)

# Mount both /v1 and /api/management/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/management/v1")
