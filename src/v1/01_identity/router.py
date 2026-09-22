from fastapi import APIRouter

router = APIRouter(prefix="/v1")

# Routes will be registered as implemented:
# from routes.auth import router as auth_router
# from routes.users import router as users_router
# router.include_router(auth_router, prefix="/auth", tags=["auth"])
# router.include_router(users_router, prefix="/users", tags=["users"])
