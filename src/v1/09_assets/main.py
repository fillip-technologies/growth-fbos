from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from router import router
from database.base import Base
from database.session import engine, dispose_engine
import models  # Ensure all SQLAlchemy models are registered on Base.metadata


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


app = FastAPI(title="Assets Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "assets"}
