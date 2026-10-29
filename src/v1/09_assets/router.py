from fastapi import APIRouter

from routes.assets import router as assets_router
from routes.categories import router as categories_router
from routes.lifecycle import router as lifecycle_router
from routes.vendors import router as vendors_router

core_router = APIRouter()
core_router.include_router(categories_router)
core_router.include_router(vendors_router)
core_router.include_router(assets_router)
core_router.include_router(lifecycle_router)

# Mount both /v1 and /api/assets/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/assets/v1")
