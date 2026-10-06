from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
import httpx

from config import settings
from database.base import Base
from database.session import dispose_engine, engine, warm_pool
import models  # noqa: F401 — registers every ORM class on Base.metadata
from router import router
from services.identity_client import IdentityClient
from utils.timing import ServerTimingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tables still come from the models until the first Alembic migration lands.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(
        base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds
    ) as http:
        app.state.identity_client = IdentityClient(http, settings.internal_service_token)
        await warm_pool()
        yield
    await dispose_engine()


app = FastAPI(title="Delivery Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.add_middleware(ServerTimingMiddleware)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "delivery"}
