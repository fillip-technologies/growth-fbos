from fastapi import APIRouter

router = APIRouter(prefix="/v1")

# Include route modules here as the service grows:
# from routes.orders import router as orders_router
# router.include_router(orders_router, prefix="/orders", tags=["orders"])
