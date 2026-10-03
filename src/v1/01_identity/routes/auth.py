from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session
from dependencies import get_client_ip, get_current_user, get_user_agent
from exceptions import CsrfTokenInvalidError
from schemas.auth import (
    ApiClientTokenRequest,
    ClientTokenResponse,
    InvitationAcceptRequest,
    JwksResponse,
    LoginRequest,
    LoginResponse,
    Me,
    MfaEnrollConfirmRequest,
    MfaEnrollmentResponse,
    MfaVerifyRequest,
    PasswordForgotRequest,
    PasswordResetRequest,
    RecoveryCodesResponse,
    RefreshRequest,
    TokenResponse,
)
from schemas.common import PaginatedResponse
from schemas.platform_auth import PlatformLoginRequest, PlatformLoginResponse, PlatformRefreshRequest
from schemas.session import SessionResponse
from schemas.token import TokenPayload
from services.auth_service import auth_service
from services.platform_auth_service import PLATFORM_REFRESH_TOKEN_TYPE, platform_auth_service
from services.session_service import current_session_id, session_service
from utils.security import (
    COOKIE_PLATFORM_CSRF_TOKEN,
    COOKIE_PLATFORM_REFRESH_TOKEN,
    COOKIE_REFRESH_TOKEN,
    clear_auth_cookies,
    decode_access_token_claims,
    decode_refresh_token,
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
    "/platform/login",
    response_model=PlatformLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Platform Super-Admin Login",
    description=(
        "Authenticates the independent platform super-admin. Returns a 15-minute access token; "
        "browsers also get a rotating refresh token as the HttpOnly `fbos_prt` cookie "
        "(plus the readable `fbos_pcsrf` CSRF cookie)."
    ),
)
async def platform_login(
    request_data: PlatformLoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> PlatformLoginResponse:
    client_is_browser = is_browser_client(request)
    login_response, refresh_token = await platform_auth_service.login(
        session=session,
        email=request_data.email,
        password=request_data.password,
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request),
        client_is_browser=client_is_browser,
    )
    if client_is_browser:
        _set_platform_cookies(response, refresh_token)
    return login_response


@router.post(
    "/platform/token/refresh",
    response_model=PlatformLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the platform super-admin's refresh token",
    description=(
        "Same rules as /token/refresh, with the platform cookies: browsers send the `fbos_prt` cookie "
        "and an X-CSRF-Token header equal to the `fbos_pcsrf` cookie."
    ),
)
async def platform_refresh_token(
    request: Request,
    response: Response,
    request_body: Optional[PlatformRefreshRequest] = None,
    session: AsyncSession = Depends(get_db_session),
) -> PlatformLoginResponse:
    cookie_token = request.cookies.get(COOKIE_PLATFORM_REFRESH_TOKEN)
    if cookie_token is not None:
        validate_csrf(request, csrf_cookie_name=COOKIE_PLATFORM_CSRF_TOKEN)
    target_token = cookie_token or (request_body.refresh_token if request_body else None)

    client_is_browser = is_browser_client(request)
    token_response, new_refresh_token = await platform_auth_service.refresh(
        session=session,
        refresh_token=target_token,
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request),
        client_is_browser=client_is_browser,
    )
    if client_is_browser:
        _set_platform_cookies(response, new_refresh_token)
    return token_response


@router.post(
    "/platform/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign the platform super-admin out",
    description="Revokes the current sign-in and clears the platform cookies. Works even after the access token expired.",
)
async def platform_logout(
    request: Request,
    request_body: Optional[PlatformRefreshRequest] = None,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    admin_id, family_id = _session_of(
        request,
        refresh_token=request.cookies.get(COOKIE_PLATFORM_REFRESH_TOKEN)
        or (request_body.refresh_token if request_body else None),
        refresh_token_type=PLATFORM_REFRESH_TOKEN_TYPE,
    )
    await platform_auth_service.logout(
        session, family_id=family_id, admin_id=admin_id,
        client_ip=get_client_ip(request), user_agent=get_user_agent(request),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(
        response,
        refresh_cookie_name=COOKIE_PLATFORM_REFRESH_TOKEN,
        csrf_cookie_name=COOKIE_PLATFORM_CSRF_TOKEN,
    )
    return response


def _set_platform_cookies(response: Response, refresh_token: str) -> None:
    set_auth_cookies(
        response=response,
        refresh_token=refresh_token,
        refresh_cookie_name=COOKIE_PLATFORM_REFRESH_TOKEN,
        csrf_cookie_name=COOKIE_PLATFORM_CSRF_TOKEN,
    )


def _session_of(
    request: Request, refresh_token: Optional[str], refresh_token_type: str
) -> tuple[Optional[uuid.UUID], Optional[uuid.UUID]]:
    """
    (subject id, session family) of the caller, from the refresh token if present, else
    from the bearer access token, expired or not. (None, None) when neither is usable.
    """
    claims = decode_refresh_token(refresh_token, refresh_token_type)
    if claims is None:
        auth_header = request.headers.get("authorization", "")
        bearer = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else None
        claims = decode_access_token_claims(bearer)
    if not claims or not claims.get("family_id"):
        return None, None
    try:
        return uuid.UUID(claims["sub"]), uuid.UUID(claims["family_id"])
    except (ValueError, TypeError):
        return None, None


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
    description=(
        "Revokes the refresh-token family of the current sign-in and clears the browser cookies. "
        "Works even after the access token expired (the session is found from the refresh cookie)."
    ),
)
async def logout(
    request: Request,
    request_body: Optional[RefreshRequest] = None,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    user_id, family_id = _session_of(
        request,
        refresh_token=request.cookies.get(COOKIE_REFRESH_TOKEN)
        or (request_body.refresh_token if request_body else None),
        refresh_token_type="refresh",
    )
    await auth_service.logout(
        session=session,
        user_id=user_id,
        family_id=family_id,
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookies(response)
    return response


@router.get(
    "/sessions",
    response_model=PaginatedResponse[SessionResponse],
    status_code=status.HTTP_200_OK,
    summary="List where you are signed in",
    description="Your live sessions (browsers and devices), most recently used first. `current` marks this one.",
)
async def list_my_sessions(
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Opaque pagination cursor"),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> PaginatedResponse[SessionResponse]:
    user = await session_service.signed_in_user(session, current_user)
    return await session_service.list_sessions(
        session, user.id, current_session_id(current_user), limit=limit, cursor=cursor
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out one of your sessions",
    description="Ends that browser or device's sign-in at once. Ending the current session also clears its cookies.",
)
async def revoke_my_session(
    session_id: uuid.UUID,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    user = await session_service.signed_in_user(session, current_user)
    await session_service.revoke_session(
        session, user, session_id, revoked_by=user.id,
        client_ip=get_client_ip(request), user_agent=get_user_agent(request),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if session_id == current_session_id(current_user):
        clear_auth_cookies(response)
    return response


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out your other sessions",
    description="Ends every other sign-in. With `include_current=true` this one ends too and its cookies are cleared.",
)
async def revoke_my_sessions(
    request: Request,
    include_current: bool = Query(False, description="Also sign out the session making this request"),
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    user = await session_service.signed_in_user(session, current_user)
    await session_service.revoke_sessions(
        session, user, revoked_by=user.id,
        keep_session_id=None if include_current else current_session_id(current_user),
        client_ip=get_client_ip(request), user_agent=get_user_agent(request),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if include_current:
        clear_auth_cookies(response)
    return response


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


@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset email",
)
async def forgot_password(
    request_data: PasswordForgotRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await auth_service.forgot_password(session, request_data)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password with a reset token",
)
async def reset_password(
    request_data: PasswordResetRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await auth_service.reset_password(session, request_data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invitations/accept",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Accept an invitation and set a password",
)
async def accept_invitation(
    request_data: InvitationAcceptRequest,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await auth_service.accept_invitation(session, request_data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/mfa/enroll",
    response_model=MfaEnrollmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Start TOTP enrollment",
)
async def start_mfa_enrollment(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> MfaEnrollmentResponse:
    return await auth_service.start_mfa_enrollment(session, current_user.user_id)


@router.post(
    "/mfa/enroll/confirm",
    response_model=RecoveryCodesResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm TOTP enrollment",
)
async def confirm_mfa_enrollment(
    request_data: MfaEnrollConfirmRequest,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RecoveryCodesResponse:
    return await auth_service.confirm_mfa_enrollment(session, current_user.user_id, request_data.code)


@router.post(
    "/oauth/token",
    response_model=ClientTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an access token for an integration (client credentials)",
)
async def oauth_token(
    request_data: ApiClientTokenRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ClientTokenResponse:
    return await auth_service.oauth_token(session, request_data)


@router.get(
    "/.well-known/jwks.json",
    response_model=JwksResponse,
    status_code=status.HTTP_200_OK,
    summary="Public keys for verifying access tokens",
)
async def get_jwks() -> JwksResponse:
    return auth_service.get_jwks()

