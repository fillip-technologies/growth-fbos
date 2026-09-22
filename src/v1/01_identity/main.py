from contextlib import asynccontextmanager
from fastapi import FastAPI

from database.base import Base
from database.session import dispose_engine, engine
import models  # noqa: F401 - Register all models with Base.metadata
from router import router
from schemas.auth import JwksResponse
from services.auth_service import auth_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


app = FastAPI(title="Identity Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "identity"}


@app.get("/.well-known/jwks.json", response_model=JwksResponse, tags=["auth"])
async def get_root_jwks() -> JwksResponse:
    return auth_service.get_jwks()
