from fastapi import APIRouter

router = APIRouter(prefix="/v1")

# Include route modules here as the service grows:
# from routes.work_units import router as work_units_router
# router.include_router(work_units_router, prefix="/work-units", tags=["work-units"])
