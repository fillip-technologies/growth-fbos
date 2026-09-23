from routes.documents import router as documents_router
from routes.shares import router as shares_router
from routes.uploads import router as uploads_router

__all__ = [
    "uploads_router",
    "documents_router",
    "shares_router",
]
