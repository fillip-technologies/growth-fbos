from fastapi import APIRouter

from routes.categories import router as categories_router
from routes.expenses import router as expenses_router
from routes.income import router as income_router
from routes.internal import router as internal_router
from routes.investments import router as investments_router
from routes.settings import router as settings_router
from routes.summaries import router as summaries_router

core_router = APIRouter()
core_router.include_router(categories_router)
core_router.include_router(expenses_router)
core_router.include_router(investments_router)
core_router.include_router(income_router)
core_router.include_router(settings_router)
core_router.include_router(summaries_router)
core_router.include_router(internal_router)

# Mounted at both /v1 and the documented /api/finance/v1, like every other service.
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/finance/v1")
