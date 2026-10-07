from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
import httpx

from config import settings
from database.session import warm_pool
from router import router
from services.documents_client import DocumentsClient
from services.identity_client import IdentityClient
from services.notification_client import notification_client
from utils.timing import ServerTimingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with (
        httpx.AsyncClient(base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds) as http,
        httpx.AsyncClient(
            base_url=settings.documents_service_url, timeout=settings.documents_timeout_seconds
        ) as documents_http,
        httpx.AsyncClient(
            base_url=settings.communication_service_url, timeout=settings.notification_timeout_seconds
        ) as communication_http,
    ):
        app.state.identity_client = IdentityClient(http, settings.internal_service_token)
        app.state.documents_client = DocumentsClient(documents_http, settings.internal_service_token)
        if settings.communication_service_url:
            notification_client.start(communication_http, settings.internal_service_token)
        await warm_pool()
        yield
        notification_client.stop()
        await notification_client.drain()


app = FastAPI(title="Revenue Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.add_middleware(ServerTimingMiddleware)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "revenue"}
