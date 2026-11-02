import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI

import models  # noqa: F401 — registers all SQLAlchemy models on Base.metadata
from config import settings
from database.base import Base
from database.session import dispose_engine, engine
from router import router
from services.capacity_worker import run_forever
from services.control_client import ControlClient
from services.identity_client import IdentityClient
from services.revenue_pull import run_forever as run_revenue_pull
from services.source_clients import AbsenceClient, EffortClient, RevenueClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(
        base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds
    ) as identity_http, httpx.AsyncClient(
        base_url=settings.control_service_url, timeout=settings.control_timeout_seconds
    ) as control_http, httpx.AsyncClient(
        base_url=settings.people_service_url, timeout=settings.source_timeout_seconds
    ) as people_http, httpx.AsyncClient(
        base_url=settings.delivery_service_url, timeout=settings.source_timeout_seconds
    ) as delivery_http, httpx.AsyncClient(
        base_url=settings.revenue_service_url, timeout=settings.source_timeout_seconds
    ) as revenue_http:
        app.state.identity_client = IdentityClient(identity_http, settings.internal_service_token)
        app.state.control_client = ControlClient(control_http)
        app.state.absence_client = AbsenceClient(people_http, settings.internal_service_token)
        app.state.effort_client = EffortClient(delivery_http, settings.internal_service_token)
        app.state.revenue_client = RevenueClient(revenue_http, settings.internal_service_token)
        pull = asyncio.create_task(run_revenue_pull(app.state.revenue_client)) if settings.revenue_pull_enabled else None
        worker = (
            asyncio.create_task(
                run_forever(app.state.identity_client, app.state.absence_client, app.state.effort_client)
            )
            if settings.capacity_worker_enabled
            else None
        )
        yield
        for task in (worker, pull):
            if task is not None:
                task.cancel()
    await dispose_engine()


app = FastAPI(title="Management Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "management"}
