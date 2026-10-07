import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
import httpx

from config import settings
from database.session import warm_pool
from router import router
from services.documents_client import DocumentsClient
from services.identity_client import IdentityClient
from services.notification_client import notification_client
from services.website_lead_import import start_import_loop
from services.website_leads_client import website_leads_client
from utils.timing import ServerTimingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(
        base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds
    ) as http, httpx.AsyncClient(
        base_url=settings.communication_service_url, timeout=settings.notification_timeout_seconds
    ) as communication_http, httpx.AsyncClient(
        headers={"Authorization": f"Bearer {settings.website_leads_api_key}"},
        timeout=settings.website_leads_timeout_seconds,
    ) as website_http:
        app.state.identity_client = IdentityClient(http, settings.internal_service_token)
        app.state.documents_client = DocumentsClient(documents_http, settings.internal_service_token)
        if settings.communication_service_url:
            notification_client.start(communication_http, settings.internal_service_token)
        if settings.website_leads_api_key:
            website_leads_client.start(
                website_http, settings.website_leads_url, settings.website_leads_organization_id
            )
        await warm_pool()
        import_task = None
        if settings.website_leads_import_enabled:
            import_task = start_import_loop(
                website_leads_client,
                settings.website_leads_organization_id,
                settings.website_leads_owner_user_id,
                settings.website_leads_import_interval_seconds,
            )
        yield
        if import_task is not None:
            import_task.cancel()
            with suppress(asyncio.CancelledError):
                await import_task
        website_leads_client.stop()
        await website_leads_client.drain()
        notification_client.stop()
        await notification_client.drain()


app = FastAPI(title="Revenue Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.add_middleware(ServerTimingMiddleware)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "revenue"}
