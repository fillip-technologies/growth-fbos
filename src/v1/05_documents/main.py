from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database.base import Base
from database.session import async_session_factory, dispose_engine, engine
from exceptions import DocumentsServiceError
import models  # noqa: F401 - Register all models with Base.metadata
from models.document import DocumentCategory
from router import router

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
}

DEFAULT_CATEGORIES = [
    ("deliverable", "Deliverable", "confidential"),
    ("contract", "Signed Contract", "confidential"),
    ("invoice", "Invoice PDF", "internal"),
    ("report", "Report", "internal"),
    ("policy", "Policy Document", "internal"),
    ("attachment", "General Attachment", "internal"),
]
DEFAULT_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")


async def seed_default_categories():
    """Seed standard classification categories on initial boot."""
    async with async_session_factory() as session:
        for code, name, default_class in DEFAULT_CATEGORIES:
            stmt = select(DocumentCategory).where(
                DocumentCategory.organization_id == DEFAULT_ORG_ID,
                DocumentCategory.code == code,
            )
            res = await session.execute(stmt)
            if not res.scalar_one_or_none():
                cat = DocumentCategory(
                    id=uuid.uuid4(),
                    organization_id=DEFAULT_ORG_ID,
                    code=code,
                    name=name,
                    default_classification=default_class,
                )
                session.add(cat)
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        await seed_default_categories()
    except SQLAlchemyError:
        pass
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
