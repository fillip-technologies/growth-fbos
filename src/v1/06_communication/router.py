from fastapi import APIRouter

core_router = APIRouter()


@core_router.get("/ping", tags=["system"])
async def ping() -> dict:
    return {"message": "pong"}

# Include route modules here as the service grows (Notifications, inbox and webhooks):
# from routes.notifications import router as notifications_router
# core_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])

# Mount both /v1 and /api/communication/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/communication/v1")
