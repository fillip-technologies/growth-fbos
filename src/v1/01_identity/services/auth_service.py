from datetime import datetime, timedelta, timezone
import logging
from typing import Optional, Tuple
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import secrets
import jwt
import pyotp

from config import settings
from exceptions import (
    AccountLockedError,
    AccountNotActiveError,
    ClientCredentialsInvalidError,
    CsrfTokenInvalidError,
    InvalidCredentialsError,
    InvitationInvalidError,
    MfaCodeInvalidError,
    OrganizationAmbiguousError,
    PasswordTooWeakError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
    ResetTokenInvalidError,
    UserNotFoundError,
)
from models.auth import ApiClient, RefreshToken, UserCredential
from models.org_unit import OrgUnit
from models.organization import Organization
from models.rbac import Role, RoleAssignment, RolePermission
from models.user import User
from models.vertical import Vertical
from schemas.auth import (
    ApiClientTokenRequest,
    ClientTokenResponse,
    InvitationAcceptRequest,
    JwkKey,
    JwksResponse,
    LoginRequest,
    LoginResponse,
    Me,
    MeRoleItem,
    MfaEnrollConfirmRequest,
    MfaEnrollmentResponse,
    MfaVerifyRequest,
    OrganizationRef,
    PasswordForgotRequest,
    PasswordResetRequest,
    RecoveryCodesResponse,
    ScopeUnitRef,
    ScopeVerticalRef,
    TokenResponse,
)
from schemas.token import TokenPayload
from schemas.user import HomeUnitRef
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
    hash_password,
    verify_dummy_password,
    verify_password,
    verify_totp_code,
)

logger = logging.getLogger("identity.auth")


class AuthService:
    async def _build_me(self, session: AsyncSession, user: User) -> Me:
        org = await session.get(Organization, user.organization_id)
        org_ref = OrganizationRef(
            id=user.organization_id,
            code=org.code or "" if org else "",
            name=org.name if org else "",
        )

        home_unit_ref: Optional[HomeUnitRef] = None
        if user.home_unit_id:
            unit = await session.get(OrgUnit, user.home_unit_id)
            if unit:
                home_unit_ref = HomeUnitRef(id=unit.id, name=unit.name, unit_type=unit.unit_type)

        now = datetime.now(timezone.utc)
        assignments_res = await session.execute(
            select(RoleAssignment).where(RoleAssignment.user_id == user.id)
        )
        assignments = list(assignments_res.scalars().all())

        role_items: list[MeRoleItem] = []
        permission_codes: set[str] = set()

        for assignment in assignments:
            if assignment.valid_to is not None:
                valid_to = assignment.valid_to
                if valid_to.tzinfo is None:
                    valid_to = valid_to.replace(tzinfo=timezone.utc)
                if valid_to <= now:
                    continue

            role = await session.get(Role, assignment.role_id)
            if not role:
                continue

            scope_unit: Optional[ScopeUnitRef] = None
            if assignment.scope_unit_id:
                su = await session.get(OrgUnit, assignment.scope_unit_id)
                if su:
                    scope_unit = ScopeUnitRef(id=su.id, name=su.name)

            scope_vertical: Optional[ScopeVerticalRef] = None
            if assignment.scope_vertical_id:
                sv = await session.get(Vertical, assignment.scope_vertical_id)
                if sv:
                    scope_vertical = ScopeVerticalRef(id=sv.id, name=sv.name)

            role_items.append(MeRoleItem(
                role_code=role.code,
                scope_unit=scope_unit,
                scope_vertical=scope_vertical,
                self_only=assignment.self_only,
            ))

            rp_res = await session.execute(
                select(RolePermission).where(RolePermission.role_id == role.id)
            )
            for rp in rp_res.scalars().all():
                permission_codes.add(rp.permission_code)

        cred = await session.get(UserCredential, user.id)
        mfa_enabled = bool(cred and cred.otp_enabled)

        tz = org.timezone if org else None

        return Me(
            id=user.id,
            name=user.name,
            email=user.email,
            organization=org_ref,
            home_unit=home_unit_ref,
            roles=role_items,
            permissions=sorted(permission_codes),
            mfa_enabled=mfa_enabled,
            timezone=tz,
            locale=None,
        )

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
                credential.locked_until = None
                credential.failed_attempts = 0

        # 6. Verify password (Argon2id)
        is_password_valid = verify_password(request_data.password, credential.password_hash)

        if not is_password_valid:
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
                credential.locked_until = now + timedelta(minutes=15)

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

        # 7. Password verified: reset failure counters
        credential.failed_attempts = 0
        credential.locked_until = None
        if hasattr(credential, "last_failed_at"):
            setattr(credential, "last_failed_at", None)
        user.last_login_at = now

        # 8. Check if MFA is enabled
        if credential.otp_enabled:
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
            return LoginResponse(
                status="mfa_required",
                mfa_token=mfa_token,
                mfa_methods=["totp"],
            ), None

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

        me = await self._build_me(session, user)
        await session.commit()

        response_body = LoginResponse(
            status="ok",
            access_token=access_token_str,
            refresh_token=None if client_is_browser else refresh_token_str,
            token_type="bearer",
            expires_in=900,
            user=me,
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
        rate_limiter.check(f"{client_ip or 'unknown'}:mfa", rate_class="auth")

        payload = decode_mfa_token(request_data.mfa_token)
        user_id = uuid.UUID(payload["sub"])

        user = await session.get(User, user_id)
        if not user:
            raise InvalidCredentialsError()

        user_status = getattr(user, "status", "active")
        if user_status != "active" or user.user_type in ("invited", "suspended", "deactivated"):
            raise AccountNotActiveError()

        credential = await session.get(UserCredential, user_id)
        if not credential or not credential.otp_secret_enc:
            raise MfaCodeInvalidError()

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

        # Anti-replay: prevent reusing the same TOTP code
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

        me = await self._build_me(session, user)
        await session.commit()

        response_body = TokenResponse(
            access_token=access_token_str,
            token_type="bearer",
            expires_in=900,
            refresh_token=None if client_is_browser else refresh_token_str,
            user=me,
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
        rate_limiter.check(f"{client_ip or 'unknown'}:refresh", rate_class="auth")

        if not refresh_token_str:
            raise RefreshTokenInvalidError()

        try:
            payload = decode_jwt_token(refresh_token_str)
        except jwt.PyJWTError:
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

        token_record = await session.get(RefreshToken, token_id)
        if not token_record:
            raise RefreshTokenInvalidError()

        now = datetime.now(timezone.utc)

        # Theft detection: already-rotated token presented
        if token_record.revoked_at is not None:
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

        token_record.revoked_at = now

        user = await session.get(User, token_record.user_id)
        if not user:
            raise RefreshTokenInvalidError()

        user_status = getattr(user, "status", "active")
        if user_status != "active" or user.user_type in ("invited", "suspended", "deactivated"):
            raise AccountNotActiveError()

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

        me = await self._build_me(session, user)
        await session.commit()

        response_body = TokenResponse(
            access_token=new_access_token_str,
            token_type="bearer",
            expires_in=900,
            refresh_token=None if client_is_browser else new_refresh_token_str,
            user=me,
        )
        return response_body, new_refresh_token_str

    async def logout(
        self,
        session: AsyncSession,
        current_user: TokenPayload,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        rate_limiter.check(f"{current_user.sub}:logout", rate_class="standard")

        user_id = uuid.UUID(current_user.sub)
        now = datetime.now(timezone.utc)

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
        rate_limiter.check(f"{current_user.sub}:me", rate_class="standard")

        user_id = uuid.UUID(current_user.sub)
        user = await session.get(User, user_id)
        if not user:
            raise UserNotFoundError()

        return await self._build_me(session, user)

    async def forgot_password(
        self,
        session: AsyncSession,
        request_data: PasswordForgotRequest,
    ) -> None:
        from sqlalchemy import func
        stmt = select(User).where(func.lower(User.email) == request_data.email.lower())
        result = await session.execute(stmt)
        users = list(result.scalars().all())

        if request_data.organization_code and len(users) > 1:
            org_stmt = select(Organization).where(Organization.code == request_data.organization_code)
            org_res = await session.execute(org_stmt)
            org = org_res.scalar_one_or_none()
            if org:
                users = [u for u in users if u.organization_id == org.id]

        if users:
            target_user = users[0]
            token = f"prt_{secrets.token_urlsafe(18)}"
            now = datetime.now(timezone.utc)
            cred = await session.get(UserCredential, target_user.id)
            if cred:
                cred.reset_token = token
                cred.reset_token_expires_at = now + timedelta(minutes=30)
                await session.commit()

            await event_publisher.publish(
                "identity.password.reset_requested.v1",
                {
                    "user_id": str(target_user.id),
                    "email": target_user.email,
                    "token": token,
                },
            )

    async def reset_password(
        self,
        session: AsyncSession,
        request_data: PasswordResetRequest,
    ) -> None:
        if len(request_data.new_password) < 12:
            raise PasswordTooWeakError("Password must be at least 12 characters long")

        stmt = select(UserCredential).where(UserCredential.reset_token == request_data.token)
        result = await session.execute(stmt)
        cred = result.scalar_one_or_none()

        if not cred or not cred.reset_token_expires_at:
            raise ResetTokenInvalidError()

        now = datetime.now(timezone.utc)
        expires = (
            cred.reset_token_expires_at
            if cred.reset_token_expires_at.tzinfo
            else cred.reset_token_expires_at.replace(tzinfo=timezone.utc)
        )
        if expires < now:
            raise ResetTokenInvalidError("Token expired")

        cred.password_hash = hash_password(request_data.new_password)
        cred.reset_token = None
        cred.reset_token_expires_at = None
        cred.password_changed_at = now
        cred.failed_attempts = 0
        cred.locked_until = None

        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == cred.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()

        await event_publisher.publish(
            "identity.password.changed.v1",
            {"user_id": str(cred.user_id)},
        )

    async def accept_invitation(
        self,
        session: AsyncSession,
        request_data: InvitationAcceptRequest,
    ) -> None:
        if len(request_data.password) < 12:
            raise PasswordTooWeakError("Password must be at least 12 characters long")

        stmt = select(UserCredential).where(UserCredential.invitation_token == request_data.token)
        result = await session.execute(stmt)
        cred = result.scalar_one_or_none()

        if not cred or not cred.invitation_token_expires_at:
            raise InvitationInvalidError()

        now = datetime.now(timezone.utc)
        expires = (
            cred.invitation_token_expires_at
            if cred.invitation_token_expires_at.tzinfo
            else cred.invitation_token_expires_at.replace(tzinfo=timezone.utc)
        )
        if expires < now:
            raise InvitationInvalidError("Token expired")

        cred.password_hash = hash_password(request_data.password)
        cred.invitation_token = None
        cred.invitation_token_expires_at = None

        user = await session.get(User, cred.user_id)
        if user:
            user.status = "active"
            user.version += 1

        await session.commit()

        await event_publisher.publish(
            "identity.user.activated.v1",
            {"user_id": str(cred.user_id)},
        )

    async def start_mfa_enrollment(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> MfaEnrollmentResponse:
        user = await session.get(User, user_id)
        if not user:
            raise UserNotFoundError()

        secret = pyotp.random_base32()
        cred = await session.get(UserCredential, user_id)
        if not cred:
            cred = UserCredential(
                user_id=user_id,
                password_hash="",
                otp_secret_enc=secret,
                otp_enabled=False,
            )
            session.add(cred)
        else:
            cred.otp_secret_enc = secret

        await session.commit()

        otpauth_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email, issuer_name="FBOS"
        )
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        qr_url = f"data:image/png;base64,mock_qr_enrollment_data_for_{user.email}"

        return MfaEnrollmentResponse(
            otpauth_uri=otpauth_uri,
            qr_png_data_url=qr_url,
            expires_at=expires_at,
        )

    async def confirm_mfa_enrollment(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        code: str,
    ) -> RecoveryCodesResponse:
        cred = await session.get(UserCredential, user_id)
        if not cred or not cred.otp_secret_enc:
            raise MfaCodeInvalidError()

        totp = pyotp.TOTP(cred.otp_secret_enc)
        if not totp.verify(code, valid_window=1):
            raise MfaCodeInvalidError()

        cred.otp_enabled = True
        codes = [f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}" for _ in range(8)]
        cred.recovery_codes = ",".join(codes)
        await session.commit()

        await event_publisher.publish(
            "identity.mfa.enrolled.v1",
            {"user_id": str(user_id)},
        )

        return RecoveryCodesResponse(codes=codes)

    async def oauth_token(
        self,
        session: AsyncSession,
        data: ApiClientTokenRequest,
    ) -> ClientTokenResponse:
        stmt = select(ApiClient).where(ApiClient.client_id == data.client_id)
        result = await session.execute(stmt)
        client = result.scalar_one_or_none()

        if not client or client.status != "active":
            raise ClientCredentialsInvalidError()

        if client.client_secret_hash and not verify_password(data.client_secret, client.client_secret_hash):
            raise ClientCredentialsInvalidError()

        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=900)
        payload = {
            "sub": client.client_id,
            "org_id": str(client.organization_id),
            "type": "client_credentials",
            "scope": data.scope or client.allowed_scopes or "",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

        return ClientTokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=900,
            scope=data.scope or client.allowed_scopes,
        )

    def get_jwks(self) -> JwksResponse:
        return JwksResponse(
            keys=[
                JwkKey(
                    kty="RSA",
                    kid="k2026-09",
                    use="sig",
                    alg="RS256",
                    n="0vx7agoebGcQSuuPiJD57eTW5KgwEg87VUm74GQbwEwEZFGAURNQ_g3ISS45",
                    e="AQAB",
                )
            ]
        )


auth_service = AuthService()
