from fastapi import APIRouter

core_router = APIRouter()


@core_router.get("/ping", tags=["system"])
async def ping() -> dict:
    return {"message": "pong"}

# Include route modules here as the service grows (Documents):
# from routes.documents import router as documents_router
# core_router.include_router(documents_router, prefix="/documents", tags=["documents"])

# Mount both /v1 and /api/documents/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/documents/v1")
