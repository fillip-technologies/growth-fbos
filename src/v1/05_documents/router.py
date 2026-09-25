from fastapi import APIRouter

from routes.documents import router as documents_router
from routes.shares import router as shares_router
from routes.uploads import router as uploads_router

core_router = APIRouter()

@core_router.get("/ping", tags=["system"])
async def ping() -> dict:
    return {"message": "pong"}

# Include all document route handlers
core_router.include_router(uploads_router)
core_router.include_router(documents_router)
core_router.include_router(shares_router)

# Mount both /v1 and /api/documents/v1 for complete compatibility
router = APIRouter()
router.include_router(core_router, prefix="/v1")
router.include_router(core_router, prefix="/api/documents/v1")
