from fastapi import APIRouter

from routes.inbox import router as inbox_router
from routes.preferences import router as preferences_router
from routes.rules import router as rules_router
from routes.webhooks import router as webhooks_router

core_router = APIRouter()
core_router.include_router(inbox_router)
core_router.include_router(preferences_router)
core_router.include_router(rules_router)
core_router.include_router(webhooks_router)

# Mount both /v1 and /api/communication/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/communication/v1")
