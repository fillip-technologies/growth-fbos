from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
import httpx

import models  # Ensure all SQLAlchemy models are registered on Base.metadata
from config import settings
from database.base import Base
from database.session import dispose_engine, engine
from router import router
from services.identity_client import IdentityClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(
        base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds
    ) as http:
        app.state.identity_client = IdentityClient(http, settings.internal_service_token)
        yield
    await dispose_engine()


app = FastAPI(title="Assets Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "assets"}
