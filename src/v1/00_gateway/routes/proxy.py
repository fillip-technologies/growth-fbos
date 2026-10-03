from typing import Final, Optional
import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from config import settings

router = APIRouter()

SERVICE_URL_MAP: Final[dict[str, str]] = {
    "identity": settings.identity_service_url,
    "revenue": settings.revenue_service_url,
    "delivery": settings.delivery_service_url,
    "control": settings.control_service_url,
    "documents": settings.documents_service_url,
    "communication": settings.communication_service_url,
    "management": settings.management_service_url,
    "insight": settings.insight_service_url,
    "assets": settings.assets_service_url,
}

HOP_BY_HOP_HEADERS: Final[set[str]] = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "content-encoding",
}


def _build_forward_headers(request: Request) -> dict[str, str]:
    """Prepare downstream request headers, preserving tracing and auth while filtering hop-by-hop."""
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        if key.lower() not in ("host", "content-length"):
            headers[key] = value.strip()

    client_host = request.client.host if request.client else "unknown"
    existing_forwarded = headers.get("x-forwarded-for")
    headers["x-forwarded-for"] = f"{existing_forwarded}, {client_host}" if existing_forwarded else client_host
    headers.setdefault("x-forwarded-proto", request.url.scheme)
    return headers


def _filter_response_headers(upstream_headers: httpx.Headers) -> list[tuple[str, str]]:
    """
    Upstream response headers minus hop-by-hop ones, as a list so repeated headers
    survive: a login sets two cookies (refresh + CSRF) and both must reach the browser.
    Content-Type is left to the Response's media_type.
    """
    return [
        (key, value)
        for key, value in upstream_headers.multi_items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-type"
    ]


async def _forward_request(
    request: Request,
    target_base_url: str,
    path_suffix: str,
) -> Response:
    """Execute proxy request to target downstream service and return response."""
    client: Optional[httpx.AsyncClient] = getattr(request.app.state, "http_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gateway HTTP client is not initialized",
        )

    target_url = f"{target_base_url.rstrip('/')}/{path_suffix.lstrip('/')}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = _build_forward_headers(request)
    body = await request.body()

    try:
        upstream_resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "type": "https://docs.fbos.example.com/errors/SERVICE_UNAVAILABLE",
                "title": "Service Unavailable",
                "status": 503,
                "code": "SERVICE_UNAVAILABLE",
                "detail": f"Downstream service at '{target_base_url}' is unreachable.",
                "instance": str(request.url.path),
                "retryable": True,
            },
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={
                "type": "https://docs.fbos.example.com/errors/GATEWAY_TIMEOUT",
                "title": "Gateway Timeout",
                "status": 504,
                "code": "GATEWAY_TIMEOUT",
                "detail": f"Downstream service at '{target_base_url}' timed out.",
                "instance": str(request.url.path),
                "retryable": True,
            },
        )
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "type": "https://docs.fbos.example.com/errors/BAD_REQUEST",
                "title": "Bad Request",
                "status": 400,
                "code": "BAD_REQUEST",
                "detail": f"Gateway could not forward request: {str(exc)}",
                "instance": str(request.url.path),
                "retryable": False,
            },
        )

    response = Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        media_type=upstream_resp.headers.get("content-type"),
    )
    for key, value in _filter_response_headers(upstream_resp.headers):
        response.headers.append(key, value)
    return response


@router.get("/.well-known/jwks.json", tags=["auth"])
async def proxy_jwks(request: Request) -> Response:
    """Forward public JWKS keys request to Identity service."""
    return await _forward_request(
        request=request,
        target_base_url=settings.identity_service_url,
        path_suffix="/.well-known/jwks.json",
    )


@router.api_route(
    "/api/{service}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
@router.api_route(
    "/api/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy_service_api(service: str, request: Request, path: str = "") -> Response:
    """Reverse-proxy /api/<service>/... requests to the matching microservice."""
    target_base = SERVICE_URL_MAP.get(service)
    if not target_base:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{service}' is not routed by the gateway.",
        )

    downstream_path = f"/api/{service}/{path}" if path else f"/api/{service}"
    return await _forward_request(
        request=request,
        target_base_url=target_base,
        path_suffix=downstream_path,
    )
