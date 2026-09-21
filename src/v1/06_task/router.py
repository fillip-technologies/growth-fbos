from fastapi import APIRouter

router = APIRouter(prefix="/v1")

# Include route modules here as the service grows:
# from routes.tasks import router as tasks_router
# router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
