from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_client_ip, get_current_user, get_user_agent
from exceptions import CsrfTokenInvalidError
from schemas.auth import (
    LoginRequest,
    LoginResponse,
    Me,
    MfaVerifyRequest,
    RefreshRequest,
    TokenResponse,
)
from schemas.token import TokenPayload
from services.auth_service import auth_service
from utils.security import (
    COOKIE_REFRESH_TOKEN,
    clear_auth_cookies,
    is_browser_client,
    set_auth_cookies,
    validate_csrf,
)

router = APIRouter()


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="User Login",
    description="Verifies user credentials (argon2id) and returns access/refresh tokens or an MFA challenge.",
)
async def login(
    request_data: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    client_is_browser = is_browser_client(request)

    login_response, raw_refresh_token = await auth_service.login(
        session=session,
        request_data=request_data,
        client_ip=client_ip,
        user_agent=user_agent,
        client_is_browser=client_is_browser,
    )

    if client_is_browser and raw_refresh_token:
        set_auth_cookies(response=response, refresh_token=raw_refresh_token)

    return login_response


@router.post(
    "/mfa/verify",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete Sign-in with TOTP code",
    description="Exchanges the short-lived mfa_token and 6-digit TOTP code for an access token and refresh token.",
)
async def verify_mfa(
    request_data: MfaVerifyRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    client_is_browser = is_browser_client(request)

    token_response, raw_refresh_token = await auth_service.verify_mfa(
        session=session,
        request_data=request_data,
        client_ip=client_ip,
        user_agent=user_agent,
        client_is_browser=client_is_browser,
    )

    if client_is_browser and raw_refresh_token:
        set_auth_cookies(response=response, refresh_token=raw_refresh_token)

    return token_response


@router.post(
    "/token/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token and get a new access token",
    description=(
        "Rotates the refresh token and invalidates the old one. Reused tokens revoke the entire session family. "
        "Browser calls must send the X-CSRF-Token header matching the fbos_csrf cookie."
    ),
)
async def refresh_token(
    request: Request,
    response: Response,
    request_body: Optional[RefreshRequest] = None,
    x_csrf_token: Optional[str] = Header(None, alias="X-CSRF-Token"),
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    # Determine token source: HttpOnly cookie fbos_rt (browsers) vs body (mobile/API clients)
    cookie_token = request.cookies.get(COOKIE_REFRESH_TOKEN)
    body_token = request_body.refresh_token if request_body else None

    is_cookie_authenticated = cookie_token is not None
    client_is_browser = is_browser_client(request)

    if is_cookie_authenticated:
        # Browser call: enforce double-submit CSRF protection
        validate_csrf(request)
        target_token = cookie_token
    else:
        # If client passes X-CSRF-Token or fbos_csrf cookie, validate CSRF
        if "fbos_csrf" in request.cookies:
            validate_csrf(request)
        target_token = body_token

    token_response, new_refresh_token = await auth_service.refresh_session(
        session=session,
        refresh_token_str=target_token,
        client_ip=client_ip,
        user_agent=user_agent,
        client_is_browser=client_is_browser,
    )

    if client_is_browser and new_refresh_token:
        set_auth_cookies(response=response, refresh_token=new_refresh_token)

    return token_response


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out and revoke the session",
    description="Revokes the refresh-token family for the current session and clears the browser cookies.",
)
async def logout(
    request: Request,
    response: Response,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)

    await auth_service.logout(
        session=session,
        current_user=current_user,
        client_ip=client_ip,
        user_agent=user_agent,
    )

    clear_auth_cookies(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=Me,
    status_code=status.HTTP_200_OK,
    summary="Get signed-in user with effective permissions",
    description="Returns current authenticated user details and resolved effective roles and permissions.",
)
async def get_me(
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Me:
    client_ip = get_client_ip(request)
    return await auth_service.get_me(
        session=session,
        current_user=current_user,
        client_ip=client_ip,
    )
