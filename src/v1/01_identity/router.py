from fastapi import APIRouter
from routes.auth import router as auth_router
from routes.users import router as users_router

router = APIRouter(prefix="/v1")
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(users_router, prefix="/users", tags=["users"])
