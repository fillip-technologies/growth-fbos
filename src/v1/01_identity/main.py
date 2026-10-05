import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from config import settings
from database.session import dispose_engine, warm_pool
from exceptions import IdentityServiceError
import models  # noqa: F401 - Register all models with Base.metadata
from router import router
from schemas.auth import JwksResponse
from services.auth_cache import auth_cache
from services.auth_service import auth_service
from utils.timing import ServerTimingMiddleware

# Rejected requests are logged with their reason; uvicorn's access log only shows the status.
logger = logging.getLogger("identity.errors")

_PROBLEM_META: dict[str, tuple[str, bool]] = {
    "INVALID_CREDENTIALS": ("Email or password is incorrect", False),
    "ACCOUNT_LOCKED": ("Account is locked", False),
    "ACCOUNT_NOT_ACTIVE": ("Account is not active", False),
    "PLATFORM_ADMIN_REQUIRED": ("Platform administrator access required", False),
    "CLIENT_ADMIN_REQUIRED": ("Client administrator access required", False),
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
    "CLIENT_NOT_FOUND": ("Client not found", False),
    "CLIENT_CODE_EXISTS": ("Client code already exists", False),
    "ORGANIZATION_NOT_FOUND": ("Organization not found", False),
    "ORGANIZATION_CODE_EXISTS": ("Organization code already exists", False),
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
    "CLIENT_ORGANIZATION_LIMIT_REACHED": ("Organization limit reached", False),
    "ORGANIZATION_USER_LIMIT_REACHED": ("User limit reached", False),
    "PERMISSION_DENIED": ("You don't have permission to do this", False),
    "VALIDATION_FAILED": ("Some fields are invalid", False),
    "USER_NOT_INVITED": ("The user is not awaiting an invitation", False),
    "SELF_MODIFICATION_FORBIDDEN": ("You can't change your own access", False),
}



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is owned by Alembic (`alembic upgrade head` runs in start.sh).
    await warm_pool()
    await auth_cache.connect(settings.redis_url)
    yield
    await auth_cache.close()
    await dispose_engine()


app = FastAPI(title="Identity Service", version="1.0.0", lifespan=lifespan)
app.include_router(router)
app.add_middleware(ServerTimingMiddleware)


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
    logger.warning(
        "%s %s -> %s %s: %s%s",
        request.method, request.url.path, exc.status_code, exc.code, exc.message,
        f" {exc.details}" if exc.details else "",
    )
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    issues = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    logger.warning("%s %s -> 422 request validation: %s", request.method, request.url.path, issues)
    return await request_validation_exception_handler(request, exc)


@app.get("/health", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "identity"}


@app.get("/.well-known/jwks.json", response_model=JwksResponse, tags=["auth"])
async def get_root_jwks() -> JwksResponse:
    return auth_service.get_jwks()
