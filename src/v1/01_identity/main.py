import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from database.base import Base
from database.session import dispose_engine, engine
from exceptions import IdentityServiceError
import models  # noqa: F401 - Register all models with Base.metadata
from router import router
from schemas.auth import JwksResponse
from services.auth_service import auth_service

_PROBLEM_META: dict[str, tuple[str, bool]] = {
    "INVALID_CREDENTIALS": ("Email or password is incorrect", False),
    "ACCOUNT_LOCKED": ("Account is locked", False),
    "ACCOUNT_NOT_ACTIVE": ("Account is not active", False),
    "ORGANIZATION_AMBIGUOUS": ("Multiple organizations found for this email", False),
    "MFA_CODE_INVALID": ("The verification code is incorrect", False),
    "MFA_TOKEN_EXPIRED": ("MFA session expired", False),
    "REFRESH_TOKEN_INVALID": ("Session expired", False),
    "REFRESH_TOKEN_REUSED": ("Session revoked due to token reuse", False),
    "CSRF_TOKEN_INVALID": ("CSRF token mismatch", False),
    "RATE_LIMIT_EXCEEDED": ("Too many requests", True),
    "USER_NOT_FOUND": ("User not found", False),
    "EMAIL_ALREADY_EXISTS": ("A user with this email already exists", False),
    "PRECONDITION_FAILED": ("Resource has been modified by another request", False),
    "PRECONDITION_REQUIRED": ("If-Match header is required", False),
    "DUPLICATE_CODE": ("Code already exists in this organization", False),
    "NOT_FOUND": ("Resource not found", False),
    "ORG_UNIT_HIERARCHY_INVALID": ("This unit type can't be placed there", False),
    "ORG_UNIT_CYCLE": ("The new parent is inside the unit's subtree", False),
    "ROLE_IS_SYSTEM": ("System roles can't be changed", False),
    "FIELD_SCHEMA_INVALID": ("Invalid field schema", False),
    "VERTICAL_PACK_INVALID": ("Invalid vertical pack", False),
    "RESET_TOKEN_INVALID": ("Reset link is invalid or expired", False),
    "INVITATION_INVALID": ("Invitation is invalid or expired", False),
    "PASSWORD_TOO_WEAK": ("Password does not meet complexity requirements", False),
    "CLIENT_CREDENTIALS_INVALID": ("Client authentication failed", False),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


app = FastAPI(title="Identity Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.exception_handler(IdentityServiceError)
async def identity_error_handler(request: Request, exc: IdentityServiceError) -> JSONResponse:
    title, retryable = _PROBLEM_META.get(exc.code, (exc.message, False))
    body: dict = {
        "type": f"https://docs.fbos.example.com/errors/{exc.code}",
        "title": title,
        "status": exc.status_code,
        "code": exc.code,
        "detail": exc.message,
        "instance": request.url.path,
        "request_id": str(uuid.uuid4()),
        "retryable": retryable,
    }
    if exc.meta:
        body["meta"] = exc.meta
    if exc.details:
        body["errors"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "identity"}


@app.get("/.well-known/jwks.json", response_model=JwksResponse, tags=["auth"])
async def get_root_jwks() -> JwksResponse:
    return auth_service.get_jwks()
