from datetime import datetime, timedelta, timezone
import logging
from typing import Optional, Tuple
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    AccountLockedError,
    AccountNotActiveError,
    CsrfTokenInvalidError,
    InvalidCredentialsError,
    MfaCodeInvalidError,
    OrganizationAmbiguousError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
    UserNotFoundError,
)
from models.auth import RefreshToken, UserCredential
from models.organization import Organization
from models.rbac import Role, RoleAssignment, RolePermission
from models.user import User
from schemas.auth import LoginRequest, LoginResponse, Me, MfaVerifyRequest, TokenResponse
from schemas.token import TokenPayload
from services.alert_service import alert_service
from services.audit_service import audit_service
from services.event_publisher import event_publisher
from services.rate_limiter import rate_limiter
from utils.security import (
    create_access_token,
    create_mfa_token,
    create_refresh_token,
    decode_jwt_token,
    decode_mfa_token,
    verify_dummy_password,
    verify_password,
    verify_totp_code,
)

logger = logging.getLogger("identity.auth")


class AuthService:
    """
    Core identity authentication and session management service.
    """

    async def login(
        self,
        session: AsyncSession,
        request_data: LoginRequest,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_is_browser: bool = False,
    ) -> Tuple[LoginResponse, Optional[str]]:
        # 1. Rate limiting check (rate limit class: auth)
        rate_limiter.check(f"{client_ip or 'unknown'}:login", rate_class="auth")

        # 2. Look up all users with the specified email
        stmt = select(User).where(User.email == request_data.email)
        res = await session.execute(stmt)
        users = list(res.scalars().all())

        # Branch 1: User does not exist (Timing Attack Protection)
        if not users:
            verify_dummy_password(request_data.password)
            await audit_service.record_attempt(
                session=session,
                event_type="identity.session.login_failed.v1",
                action="login_failed",
                status="failed",
                ip_address=client_ip,
                user_agent=user_agent,
                details={"email": request_data.email, "reason": "INVALID_CREDENTIALS"},
            )
            await event_publisher.publish(
                "identity.session.login_failed.v1",
                {
                    "email": request_data.email,
                    "organization_code": request_data.organization_code,
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "reason": "INVALID_CREDENTIALS",
                },
            )
            await session.commit()
            raise InvalidCredentialsError()

        # Branch 2: Email exists in more than one organization
        if len(users) > 1:
            if not request_data.organization_code:
                # Ambiguous organization: cannot decide without organization_code
                await audit_service.record_attempt(
                    session=session,
                    event_type="identity.session.login_failed.v1",
                    action="login_failed",
                    status="failed",
                    ip_address=client_ip,
                    user_agent=user_agent,
                    details={"email": request_data.email, "reason": "ORGANIZATION_AMBIGUOUS"},
                )
                await event_publisher.publish(
                    "identity.session.login_failed.v1",
                    {
                        "email": request_data.email,
                        "ip_address": client_ip,
                        "user_agent": user_agent,
                        "reason": "ORGANIZATION_AMBIGUOUS",
                    },
                )
                await session.commit()
                raise OrganizationAmbiguousError()

            # Disambiguate user using organization_code
            target_user: Optional[User] = None
            for u in users:
                org = await session.get(Organization, u.organization_id)
                if org and org.code == request_data.organization_code:
                    target_user = u
                    break

            if target_user is None:
                verify_dummy_password(request_data.password)
                await audit_service.record_attempt(
                    session=session,
                    event_type="identity.session.login_failed.v1",
                    action="login_failed",
                    status="failed",
                    ip_address=client_ip,
                    user_agent=user_agent,
                    details={"email": request_data.email, "reason": "INVALID_CREDENTIALS"},
                )
                await event_publisher.publish(
                    "identity.session.login_failed.v1",
                    {
                        "email": request_data.email,
                        "organization_code": request_data.organization_code,
                        "ip_address": client_ip,
                        "user_agent": user_agent,
                        "reason": "INVALID_CREDENTIALS",
                    },
                )
                await session.commit()
                raise InvalidCredentialsError()
            user = target_user
        else:
            # Exactly one user found
            user = users[0]
            if request_data.organization_code:
                org = await session.get(Organization, user.organization_id)
                if not org or org.code != request_data.organization_code:
                    verify_dummy_password(request_data.password)
                    await audit_service.record_attempt(
                        session=session,
                        event_type="identity.session.login_failed.v1",
                        action="login_failed",
                        status="failed",
                        ip_address=client_ip,
                        user_agent=user_agent,
                        organization_id=user.organization_id,
                        user_id=user.id,
                        details={"email": request_data.email, "reason": "INVALID_CREDENTIALS"},
                    )
                    await event_publisher.publish(
                        "identity.session.login_failed.v1",
                        {
                            "email": request_data.email,
                            "organization_code": request_data.organization_code,
                            "ip_address": client_ip,
                            "user_agent": user_agent,
                            "reason": "INVALID_CREDENTIALS",
                        },
                    )
                    await session.commit()
                    raise InvalidCredentialsError()

        # 3. Check account active status (invited, suspended, deactivated -> 403)
        user_status = getattr(user, "status", "active")
        if user_status != "active" or user.user_type in ("invited", "suspended", "deactivated"):
            await audit_service.record_attempt(
                session=session,
                event_type="identity.session.login_failed.v1",
                action="login_failed",
                status="failed",
                ip_address=client_ip,
                user_agent=user_agent,
                organization_id=user.organization_id,
                user_id=user.id,
                details={"email": user.email, "reason": "ACCOUNT_NOT_ACTIVE"},
            )
            await event_publisher.publish(
                "identity.session.login_failed.v1",
                {
                    "user_id": str(user.id),
                    "email": user.email,
                    "organization_id": str(user.organization_id),
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "reason": "ACCOUNT_NOT_ACTIVE",
                },
            )
            await session.commit()
            raise AccountNotActiveError()

        # 4. Fetch user credentials
        credential = await session.get(UserCredential, user.id)
        if not credential:
            verify_dummy_password(request_data.password)
            await audit_service.record_attempt(
                session=session,
                event_type="identity.session.login_failed.v1",
                action="login_failed",
                status="failed",
                ip_address=client_ip,
                user_agent=user_agent,
                organization_id=user.organization_id,
                user_id=user.id,
                details={"email": user.email, "reason": "INVALID_CREDENTIALS"},
            )
            await event_publisher.publish(
                "identity.session.login_failed.v1",
                {
                    "email": user.email,
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "reason": "INVALID_CREDENTIALS",
                },
            )
            await session.commit()
            raise InvalidCredentialsError()

        now = datetime.now(timezone.utc)

        # 5. Check account lockout status (423 ACCOUNT_LOCKED)
        if credential.locked_until is not None:
            # Handle timezone awareness safely
            lock_time = credential.locked_until
            if lock_time.tzinfo is None:
                lock_time = lock_time.replace(tzinfo=timezone.utc)

            if lock_time > now:
                await audit_service.record_attempt(
                    session=session,
                    event_type="identity.session.login_failed.v1",
                    action="login_attempt_account_locked",
                    status="locked",
                    ip_address=client_ip,
                    user_agent=user_agent,
                    organization_id=user.organization_id,
                    user_id=user.id,
                    details={"email": user.email, "reason": "ACCOUNT_LOCKED"},
                )
                await event_publisher.publish(
                    "identity.session.login_failed.v1",
                    {
                        "user_id": str(user.id),
                        "email": user.email,
                        "organization_id": str(user.organization_id),
                        "ip_address": client_ip,
                        "user_agent": user_agent,
                        "reason": "ACCOUNT_LOCKED",
                    },
                )
                await session.commit()
                raise AccountLockedError()
            else:
                # Lockout period has elapsed: clear lock
                credential.locked_until = None
                credential.failed_attempts = 0

        # 6. Verify password (Argon2id)
        is_password_valid = verify_password(request_data.password, credential.password_hash)

        if not is_password_valid:
            # Calculate failure window (5 failures within 15 minutes)
            last_failed = getattr(credential, "last_failed_at", None)
            if last_failed is not None and last_failed.tzinfo is None:
                last_failed = last_failed.replace(tzinfo=timezone.utc)

            if last_failed is None or (now - last_failed) > timedelta(minutes=15):
                credential.failed_attempts = 1
            else:
                credential.failed_attempts += 1

            if hasattr(credential, "last_failed_at"):
                setattr(credential, "last_failed_at", now)

            if credential.failed_attempts >= 5:
                # Account is now locked for 15 minutes!
                credential.locked_until = now + timedelta(minutes=15)

                # Send security alert email
                await alert_service.send_security_alert_email(
                    email=user.email,
                    reason="Five failed sign-in attempts within 15 minutes.",
                    ip_address=client_ip,
                    user_agent=user_agent,
                )

                await audit_service.record_attempt(
                    session=session,
                    event_type="identity.session.login_failed.v1",
                    action="account_locked",
                    status="locked",
                    ip_address=client_ip,
                    user_agent=user_agent,
                    organization_id=user.organization_id,
                    user_id=user.id,
                    details={"email": user.email, "reason": "ACCOUNT_LOCKED"},
                )
                await event_publisher.publish(
                    "identity.session.login_failed.v1",
                    {
                        "user_id": str(user.id),
                        "email": user.email,
                        "organization_id": str(user.organization_id),
                        "ip_address": client_ip,
                        "user_agent": user_agent,
                        "reason": "ACCOUNT_LOCKED",
                    },
                )
                await session.commit()
                raise AccountLockedError()
            else:
                await audit_service.record_attempt(
                    session=session,
                    event_type="identity.session.login_failed.v1",
                    action="login_failed",
                    status="failed",
                    ip_address=client_ip,
                    user_agent=user_agent,
                    organization_id=user.organization_id,
                    user_id=user.id,
                    details={"email": user.email, "reason": "INVALID_CREDENTIALS"},
                )
                await event_publisher.publish(
                    "identity.session.login_failed.v1",
                    {
                        "user_id": str(user.id),
                        "email": user.email,
                        "organization_id": str(user.organization_id),
                        "ip_address": client_ip,
                        "user_agent": user_agent,
                        "reason": "INVALID_CREDENTIALS",
                    },
                )
                await session.commit()
                raise InvalidCredentialsError()

        # 7. Password verified successfully: reset failure counters
        credential.failed_attempts = 0
        credential.locked_until = None
        if hasattr(credential, "last_failed_at"):
            setattr(credential, "last_failed_at", None)
        user.last_login_at = now

        # 8. Check if MFA is enabled
        if credential.otp_enabled:
            # Issue short-lived 5-minute MFA token for step 2
            mfa_token = create_mfa_token(
                user_id=user.id,
                organization_id=user.organization_id,
                email=user.email,
            )
            await audit_service.record_attempt(
                session=session,
                event_type="identity.session.login_attempt",
                action="mfa_challenge_issued",
                status="success",
                ip_address=client_ip,
                user_agent=user_agent,
                organization_id=user.organization_id,
                user_id=user.id,
                details={"email": user.email, "mfa_required": True},
            )
            await session.commit()
            return LoginResponse(mfa_required=True, mfa_token=mfa_token, token_type="mfa"), None

        # 9. MFA not enabled: complete sign-in immediately
        family_id = uuid.uuid4()
        token_id = uuid.uuid4()
        refresh_token_str = create_refresh_token(
            token_id=token_id,
            user_id=user.id,
            family_id=family_id,
        )
        access_token_str = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            email=user.email,
            family_id=family_id,
        )

        db_refresh_token = RefreshToken(
            id=token_id,
            user_id=user.id,
            family_id=family_id,
            issued_at=now,
            user_agent=user_agent,
        )
        session.add(db_refresh_token)

        await audit_service.record_attempt(
            session=session,
            event_type="identity.session.login_succeeded.v1",
            action="login_succeeded",
            status="success",
            ip_address=client_ip,
            user_agent=user_agent,
            organization_id=user.organization_id,
            user_id=user.id,
            details={"email": user.email, "auth_method": "password"},
        )
        await event_publisher.publish(
            "identity.session.login_succeeded.v1",
            {
                "user_id": str(user.id),
                "email": user.email,
                "organization_id": str(user.organization_id),
                "ip_address": client_ip,
                "user_agent": user_agent,
                "auth_method": "password",
            },
        )

        await session.commit()

        # Mobile apps receive refresh token in body; browsers receive it in HttpOnly cookie
        response_body = LoginResponse(
            mfa_required=False,
            access_token=access_token_str,
            refresh_token=None if client_is_browser else refresh_token_str,
            token_type="bearer",
            expires_in=900,
        )
        return response_body, refresh_token_str

    async def verify_mfa(
        self,
        session: AsyncSession,
        request_data: MfaVerifyRequest,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_is_browser: bool = False,
    ) -> Tuple[TokenResponse, str]:
        # 1. Rate limiting check (rate limit class: auth)
        rate_limiter.check(f"{client_ip or 'unknown'}:mfa", rate_class="auth")

        # 2. Decode and validate mfa_token (5-minute expiry)
        payload = decode_mfa_token(request_data.mfa_token)
        user_id = uuid.UUID(payload["sub"])

        # 3. Look up user and credentials
        user = await session.get(User, user_id)
        if not user:
            raise InvalidCredentialsError()

        user_status = getattr(user, "status", "active")
        if user_status != "active" or user.user_type in ("invited", "suspended", "deactivated"):
            raise AccountNotActiveError()

        credential = await session.get(UserCredential, user_id)
        if not credential or not credential.otp_secret_enc:
            raise MfaCodeInvalidError()

        # 4. Verify 6-digit TOTP code
        is_code_valid = verify_totp_code(credential.otp_secret_enc, request_data.code)
        if not is_code_valid:
            await audit_service.record_attempt(
                session=session,
                event_type="identity.session.login_failed.v1",
                action="mfa_verify_failed",
                status="failed",
                ip_address=client_ip,
                user_agent=user_agent,
                organization_id=user.organization_id,
                user_id=user.id,
                details={"reason": "MFA_CODE_INVALID"},
            )
            await event_publisher.publish(
                "identity.session.login_failed.v1",
                {
                    "user_id": str(user.id),
                    "email": user.email,
                    "organization_id": str(user.organization_id),
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "reason": "MFA_CODE_INVALID",
                },
            )
            await session.commit()
            raise MfaCodeInvalidError()

        # 5. Anti-replay check: prevent reusing the same TOTP code
        last_code = getattr(credential, "last_totp_code", None)
        if last_code == request_data.code:
            await audit_service.record_attempt(
                session=session,
                event_type="identity.session.login_failed.v1",
                action="mfa_replay_detected",
                status="failed",
                ip_address=client_ip,
                user_agent=user_agent,
                organization_id=user.organization_id,
                user_id=user.id,
                details={"reason": "MFA_CODE_REUSED"},
            )
            await event_publisher.publish(
                "identity.session.login_failed.v1",
                {
                    "user_id": str(user.id),
                    "email": user.email,
                    "organization_id": str(user.organization_id),
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "reason": "MFA_CODE_INVALID",
                },
            )
            await session.commit()
            raise MfaCodeInvalidError()

        if hasattr(credential, "last_totp_code"):
            setattr(credential, "last_totp_code", request_data.code)

        # 6. Success: create tokens and session
        now = datetime.now(timezone.utc)
        credential.failed_attempts = 0
        credential.locked_until = None
        user.last_login_at = now

        family_id = uuid.uuid4()
        token_id = uuid.uuid4()
        refresh_token_str = create_refresh_token(
            token_id=token_id,
            user_id=user.id,
            family_id=family_id,
        )
        access_token_str = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            email=user.email,
            family_id=family_id,
        )

        db_refresh_token = RefreshToken(
            id=token_id,
            user_id=user.id,
            family_id=family_id,
            issued_at=now,
            user_agent=user_agent,
        )
        session.add(db_refresh_token)

        await audit_service.record_attempt(
            session=session,
            event_type="identity.session.login_succeeded.v1",
            action="mfa_login_succeeded",
            status="success",
            ip_address=client_ip,
            user_agent=user_agent,
            organization_id=user.organization_id,
            user_id=user.id,
            details={"email": user.email, "auth_method": "mfa"},
        )
        await event_publisher.publish(
            "identity.session.login_succeeded.v1",
            {
                "user_id": str(user.id),
                "email": user.email,
                "organization_id": str(user.organization_id),
                "ip_address": client_ip,
                "user_agent": user_agent,
                "auth_method": "mfa",
            },
        )

        await session.commit()

        response_body = TokenResponse(
            access_token=access_token_str,
            token_type="bearer",
            expires_in=900,
            refresh_token=None if client_is_browser else refresh_token_str,
        )
        return response_body, refresh_token_str

    async def refresh_session(
        self,
        session: AsyncSession,
        refresh_token_str: Optional[str],
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_is_browser: bool = False,
    ) -> Tuple[TokenResponse, str]:
        # 1. Rate limiting check (rate limit class: auth)
        rate_limiter.check(f"{client_ip or 'unknown'}:refresh", rate_class="auth")

        if not refresh_token_str:
            raise RefreshTokenInvalidError()

        # 2. Decode and validate refresh token JWT
        try:
            payload = decode_jwt_token(refresh_token_str)
        except Exception:
            raise RefreshTokenInvalidError()

        if payload.get("type") != "refresh":
            raise RefreshTokenInvalidError()

        token_id_str = payload.get("jti")
        if not token_id_str:
            raise RefreshTokenInvalidError()

        try:
            token_id = uuid.UUID(token_id_str)
        except (ValueError, TypeError):
            raise RefreshTokenInvalidError()

        # 3. Look up token in database
        token_record = await session.get(RefreshToken, token_id)
        if not token_record:
            raise RefreshTokenInvalidError()

        now = datetime.now(timezone.utc)

        # 4. Theft Detection: token was already rotated!
        if token_record.revoked_at is not None:
            # Revoke entire token family to protect user session against theft
            stmt = (
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == token_record.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.execute(stmt)

            await audit_service.record_attempt(
                session=session,
                event_type="identity.session.revoked.v1",
                action="token_theft_detected_family_revoked",
                status="revoked",
                ip_address=client_ip,
                user_agent=user_agent,
                user_id=token_record.user_id,
                details={"family_id": str(token_record.family_id), "reason": "REFRESH_TOKEN_REUSED"},
            )
            await event_publisher.publish(
                "identity.session.revoked.v1",
                {
                    "user_id": str(token_record.user_id),
                    "family_id": str(token_record.family_id),
                    "reason": "REFRESH_TOKEN_REUSED",
                },
            )
            await session.commit()
            raise RefreshTokenReusedError()

        # 5. Token is valid: rotate token (invalidate old token)
        token_record.revoked_at = now

        user = await session.get(User, token_record.user_id)
        if not user:
            raise RefreshTokenInvalidError()

        user_status = getattr(user, "status", "active")
        if user_status != "active" or user.user_type in ("invited", "suspended", "deactivated"):
            raise AccountNotActiveError()

        # 6. Issue new tokens under the same family
        new_token_id = uuid.uuid4()
        new_refresh_token_str = create_refresh_token(
            token_id=new_token_id,
            user_id=user.id,
            family_id=token_record.family_id,
        )
        new_access_token_str = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            email=user.email,
            family_id=token_record.family_id,
        )

        new_token_record = RefreshToken(
            id=new_token_id,
            user_id=user.id,
            family_id=token_record.family_id,
            issued_at=now,
            user_agent=user_agent,
        )
        session.add(new_token_record)

        await audit_service.record_attempt(
            session=session,
            event_type="identity.session.refreshed.v1",
            action="session_refreshed",
            status="success",
            ip_address=client_ip,
            user_agent=user_agent,
            organization_id=user.organization_id,
            user_id=user.id,
            details={"family_id": str(token_record.family_id)},
        )
        await event_publisher.publish(
            "identity.session.refreshed.v1",
            {
                "user_id": str(user.id),
                "family_id": str(token_record.family_id),
                "ip_address": client_ip,
                "user_agent": user_agent,
            },
        )

        await session.commit()

        response_body = TokenResponse(
            access_token=new_access_token_str,
            token_type="bearer",
            expires_in=900,
            refresh_token=None if client_is_browser else new_refresh_token_str,
        )
        return response_body, new_refresh_token_str

    async def logout(
        self,
        session: AsyncSession,
        current_user: TokenPayload,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        # Rate limit class: standard
        rate_limiter.check(f"{current_user.sub}:logout", rate_class="standard")

        user_id = uuid.UUID(current_user.sub)
        now = datetime.now(timezone.utc)

        # Revoke the refresh-token family for the current session
        if current_user.family_id:
            family_id = uuid.UUID(current_user.family_id)
            stmt = (
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.execute(stmt)
        else:
            # Revoke all active refresh tokens for this user
            stmt = (
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.execute(stmt)

        await audit_service.record_attempt(
            session=session,
            event_type="identity.session.revoked.v1",
            action="logout_revocation",
            status="revoked",
            ip_address=client_ip,
            user_agent=user_agent,
            user_id=user_id,
            details={"family_id": current_user.family_id},
        )
        await event_publisher.publish(
            "identity.session.revoked.v1",
            {
                "user_id": str(user_id),
                "family_id": current_user.family_id,
                "ip_address": client_ip,
                "user_agent": user_agent,
            },
        )

        await session.commit()

    async def get_me(
        self,
        session: AsyncSession,
        current_user: TokenPayload,
        client_ip: Optional[str] = None,
    ) -> Me:
        # Rate limit class: standard
        rate_limiter.check(f"{current_user.sub}:me", rate_class="standard")

        user_id = uuid.UUID(current_user.sub)
        user = await session.get(User, user_id)
        if not user:
            raise UserNotFoundError()

        # Compute effective roles and permissions
        now = datetime.now(timezone.utc)
        assignments_stmt = select(RoleAssignment).where(RoleAssignment.user_id == user_id)
        assignments_res = await session.execute(assignments_stmt)
        assignments = list(assignments_res.scalars().all())

        role_codes: set[str] = set()
        permission_codes: set[str] = set()

        for assignment in assignments:
            if assignment.valid_to is not None:
                valid_to = assignment.valid_to
                if valid_to.tzinfo is None:
                    valid_to = valid_to.replace(tzinfo=timezone.utc)
                if valid_to <= now:
                    continue

            role = await session.get(Role, assignment.role_id)
            if role:
                role_codes.add(role.code)
                # Fetch role permissions
                rp_stmt = select(RolePermission).where(RolePermission.role_id == role.id)
                rp_res = await session.execute(rp_stmt)
                for rp in rp_res.scalars().all():
                    permission_codes.add(rp.permission_code)

        last_login_iso = user.last_login_at.isoformat() if user.last_login_at else None

        return Me(
            id=user.id,
            email=user.email,
            name=user.name,
            phone=user.phone,
            user_type=user.user_type,
            organization_id=user.organization_id,
            roles=sorted(list(role_codes)),
            permissions=sorted(list(permission_codes)),
            last_login_at=last_login_iso,
        )


auth_service = AuthService()
