from fastapi import APIRouter

core_router = APIRouter()


@core_router.get("/ping", tags=["system"])
async def ping() -> dict:
    return {"message": "pong"}

# Include route modules here as the service grows (Assets):
# from routes.assets import router as assets_router
# core_router.include_router(assets_router, prefix="/assets", tags=["assets"])

# Mount both /v1 and /api/assets/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/assets/v1")
