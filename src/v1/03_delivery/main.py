import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
import logging

from fastapi import FastAPI
import httpx

from config import settings
from database.session import async_session_factory, dispose_engine, warm_pool
from router import router
from services.calendars import working_calendars
from services.identity_client import IdentityClient
from services.outbox_worker import start_worker
from utils.timing import ServerTimingMiddleware


# The service's own messages (the worker starting, notifications given up) reach the container
# log from INFO up. Libraries keep Python's default (warnings), so httpx doesn't log every call.
_log_handler = logging.StreamHandler()
_log_handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
_delivery_log = logging.getLogger("delivery")
_delivery_log.setLevel(logging.INFO)
_delivery_log.addHandler(_log_handler)
_delivery_log.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(
        base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds
    ) as http, httpx.AsyncClient(
        base_url=settings.communication_service_url, timeout=settings.notification_timeout_seconds
    ) as communication_http:
        identity = IdentityClient(http, settings.internal_service_token)
        app.state.identity_client = identity
        working_calendars.start(identity)
        await warm_pool()
        worker = None
        if settings.worker_enabled:
            worker = start_worker(
                async_session_factory, communication_http, settings.internal_service_token, identity, identity,
                settings.worker_interval_seconds,
            )
        yield
        if worker is not None:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        working_calendars.stop()
    await dispose_engine()


app = FastAPI(title="Delivery Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.add_middleware(ServerTimingMiddleware)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "delivery"}
