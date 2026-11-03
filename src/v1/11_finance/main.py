from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
import httpx

import models  # noqa: F401 — registers every ORM class on Base.metadata
from config import settings
from database.session import dispose_engine
from router import router
from services.identity_client import IdentityClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tables come from Alembic (start.sh runs `alembic upgrade head` before the app starts).
    async with httpx.AsyncClient(
        base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds
    ) as http:
        app.state.identity_client = IdentityClient(http, settings.internal_service_token)
        yield
    await dispose_engine()


app = FastAPI(title="Finance Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "finance"}
