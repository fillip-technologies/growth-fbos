import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import httpx

import models  # Ensure all SQLAlchemy models are registered on Base.metadata
from config import settings
from database.base import Base
from database.session import dispose_engine, engine
from router import router
from services.identity_client import IdentityClient

logger = logging.getLogger("people.service")


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


app = FastAPI(title="People Service (HCM & ATS)", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {
            "field": str(err.get("loc", [""])[-1]) if err.get("loc") else None,
            "issue": err.get("msg", "Invalid value"),
        }
        for err in exc.errors()
    ]
    detail_msg = "; ".join(f"{e['field']}: {e['issue']}" if e['field'] else e['issue'] for e in errors)
    return JSONResponse(
        status_code=422,
        content={
            "type": "https://docs.fbos.example.com/errors/VALIDATION_ERROR",
            "title": "Validation Error",
            "status": 422,
            "code": "VALIDATION_ERROR",
            "detail": detail_msg or "One or more fields failed validation.",
            "instance": str(request.url.path),
            "errors": errors,
            "retryable": False,
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code = "HTTP_ERROR"
    detail = str(exc.detail)
    errors = None

    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", "HTTP_ERROR")
        detail = exc.detail.get("message", exc.detail.get("detail", str(exc.detail)))
        errors = exc.detail.get("details")

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": f"https://docs.fbos.example.com/errors/{code}",
            "title": code.replace("_", " ").title(),
            "status": exc.status_code,
            "code": code,
            "detail": detail,
            "instance": str(request.url.path),
            "errors": errors,
            "retryable": exc.status_code in (429, 503, 504),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server exception at %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "type": "https://docs.fbos.example.com/errors/INTERNAL_SERVER_ERROR",
            "title": "Internal Server Error",
            "status": 500,
            "code": "INTERNAL_SERVER_ERROR",
            "detail": "An internal server error occurred while processing the request.",
            "instance": str(request.url.path),
            "retryable": True,
        },
    )


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "people"}
