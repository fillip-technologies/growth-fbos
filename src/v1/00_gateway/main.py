import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from router import router
from services.ceo_snapshots import run_forever as run_ceo_snapshots


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    client = httpx.AsyncClient(timeout=30.0)
    app.state.http_client = client
    snapshots = asyncio.create_task(run_ceo_snapshots(client)) if settings.ceo_snapshot_enabled else None
    yield
    if snapshots is not None:
        snapshots.cancel()
    await client.aclose()


def configure_cors(app: FastAPI, enabled: bool, origins: str) -> None:
    """Answer cross-origin requests when CORS_ENABLED is on; `origins` is a comma list or *."""
    if not enabled:
        return
    allowed = [origin.strip() for origin in (origins or "").split(",") if origin.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


app = FastAPI(title="Gateway Service", version="1.0.0", lifespan=lifespan)
configure_cors(app, settings.cors_enabled, settings.cors_origins)
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "gateway"}
