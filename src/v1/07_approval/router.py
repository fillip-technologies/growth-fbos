from fastapi import APIRouter

router = APIRouter(prefix="/v1")

# Include route modules here as the service grows:
# from routes.requests import router as requests_router
# router.include_router(requests_router, prefix="/approval-requests", tags=["approval-requests"])
