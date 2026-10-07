from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx

from config import settings
from database.base import Base
from database.session import dispose_engine, engine
from exceptions import DocumentsServiceError
import models  # noqa: F401 - Register all models with Base.metadata
from router import router
from services.identity_client import IdentityClient
from services.subject_client import SubjectClient

_PROBLEM_META: dict[str, tuple[str, bool]] = {
    "NOT_FOUND": ("Resource not found", False),
    "FILE_TOO_LARGE": ("File is too large", False),
    "MIME_TYPE_NOT_ALLOWED": ("File type not allowed", False),
    "DOCUMENT_LOCKED": ("Document is locked", False),
    "CHECKSUM_MISMATCH": ("Uploaded file doesn't match its checksum", False),
    "DOCUMENT_SCAN_PENDING": ("File is still being scanned", True),
    "DOCUMENT_INFECTED": ("File failed the virus scan", False),
    "SHARE_EXPIRED": ("This link has expired", False),
    "UPLOAD_EXPIRED": ("Upload session expired", False),
    "SHARE_PASSWORD_REQUIRED": ("Password required", False),
    "SUBJECT_NOT_FOUND": ("The linked business object was not found", False),
    "DOCUMENT_RESTRICTED": ("Restricted documents cannot be shared", False),
    "PERMISSION_DENIED": ("You don't have permission for this action", False),
    "UNAUTHORIZED": ("Authentication required", False),
    "VALIDATION_FAILED": ("Some fields are invalid", False),
    "CATEGORY_UNKNOWN": ("Unknown document category", False),
    "CATEGORY_CODE_EXISTS": ("Category code already in use", False),
    "SUBJECT_LOCKED": ("This record no longer accepts documents", False),
    "AUTH_SERVICE_UNAVAILABLE": ("Sign-in could not be checked", True),
    "SUBJECT_SERVICE_UNAVAILABLE": ("Linked record could not be checked", True),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with (
        httpx.AsyncClient(base_url=settings.identity_service_url, timeout=settings.identity_timeout_seconds) as identity_http,
        httpx.AsyncClient(timeout=settings.subject_check_timeout_seconds) as subject_http,
    ):
        app.state.identity_client = IdentityClient(identity_http, settings.internal_service_token)
        app.state.subject_client = SubjectClient(
            subject_http,
            settings.subject_services,
            settings.internal_service_token,
            settings.subject_read_cache_seconds,
        )
        yield
    await dispose_engine()


app = FastAPI(title="Documents Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(DocumentsServiceError)
async def documents_error_handler(request: Request, exc: DocumentsServiceError) -> JSONResponse:
    title, retryable = _PROBLEM_META.get(exc.code, (exc.message, False))
    body: dict = {
        "type": f"https://docs.fbos.example.com/errors/{exc.code}",
        "title": title,
        "status": exc.status_code,
        "code": exc.code,
        "detail": exc.message,
        "instance": request.url.path,
        "request_id": request.headers.get("x-request-id") or str(uuid.uuid4()),
        "retryable": retryable,
    }
    if exc.meta:
        body["meta"] = exc.meta
    if exc.details:
        body["errors"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "documents"}
