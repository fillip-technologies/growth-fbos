from fastapi import APIRouter

router = APIRouter(prefix="/v1")

# Include route modules here as the service grows:
# from routes.definitions import router as definitions_router
# router.include_router(definitions_router, prefix="/workflow-definitions", tags=["workflow-definitions"])
# from routes.instances import router as instances_router
# router.include_router(instances_router, prefix="/workflow-instances", tags=["workflow-instances"])
