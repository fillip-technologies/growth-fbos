from datetime import datetime
import logging
from typing import Any, Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    DuplicateCodeError,
    PreconditionFailedError,
    PreconditionRequiredError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from models.auth import RefreshToken, UserCredential
from models.membership import UnitMembership
from models.org_unit import OrgUnit
from models.rbac import Role, RoleAssignment
from models.user import User
from schemas.common import PageInfo, PaginatedResponse
from schemas.user import (
    HomeUnitRef,
    ManagerRef,
    UserDeactivateRequest,
    UserInviteRequest,
    UserResponse,
    UserUpdateRequest,
)
from services.event_publisher import event_publisher

logger = logging.getLogger("identity.user_service")


class UserService:
    async def _build_user_response(self, session: AsyncSession, user: User) -> UserResponse:
        """Helper to build UserResponse with populated home_unit, manager, and mfa status."""
        home_unit_ref: Optional[HomeUnitRef] = None
        if user.home_unit_id:
            unit = await session.get(OrgUnit, user.home_unit_id)
            if unit:
                home_unit_ref = HomeUnitRef(id=unit.id, name=unit.name, unit_type=unit.unit_type)

        manager_ref: Optional[ManagerRef] = None
        if user.manager_user_id:
            manager = await session.get(User, user.manager_user_id)
            if manager:
                manager_ref = ManagerRef(id=manager.id, name=manager.name)

        cred = await session.get(UserCredential, user.id)
        mfa_enabled = bool(cred.otp_enabled) if cred else False

        created_at_str = user.created_at.isoformat() if hasattr(user, "created_at") and user.created_at else None
        last_login_str = user.last_login_at.isoformat() if user.last_login_at else None

        return UserResponse(
            id=user.id,
            employee_code=user.employee_code,
            name=user.name,
            email=user.email,
            phone=user.phone,
            user_type=user.user_type,
            status=getattr(user, "status", "active"),
            home_unit=home_unit_ref,
            manager=manager_ref,
            mfa_enabled=mfa_enabled,
            last_login_at=last_login_str,
            version=user.version,
            created_at=created_at_str,
        )

    async def list_users(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        status: Optional[str] = None,
        unit_id: Optional[uuid.UUID] = None,
        role_code: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[UserResponse]:
        query = select(User).where(User.organization_id == organization_id)

        if status:
            query = query.where(User.status == status)

        if unit_id:
            query = query.where(User.home_unit_id == unit_id)

        if role_code:
            role_res = await session.execute(
                select(Role).where(Role.code == role_code, Role.organization_id == organization_id)
            )
            role = role_res.scalar_one_or_none()
            if not role:
                return PaginatedResponse(
                    data=[],
                    page=PageInfo(next_cursor=None, has_more=False, limit=limit),
                )
            assigned_user_ids = select(RoleAssignment.user_id).where(
                RoleAssignment.role_id == role.id,
                RoleAssignment.organization_id == organization_id,
            ).scalar_subquery()
            query = query.where(User.id.in_(assigned_user_ids))

        if q:
            term = f"%{q}%"
            query = query.where(
                (User.name.ilike(term))
                | (User.email.ilike(term))
                | (User.employee_code.ilike(term))
            )

        # Pagination ordering
        query = query.order_by(User.created_at.desc(), User.id.desc())

        # Offset cursor if provided
        offset = 0
        if cursor and cursor.isdigit():
            offset = int(cursor)
        query = query.offset(offset).limit(limit + 1)

        result = await session.execute(query)
        users = list(result.scalars().all())

        has_more = len(users) > limit
        if has_more:
            users = users[:limit]
            next_cursor = str(offset + limit)
        else:
            next_cursor = None

        data = [await self._build_user_response(session, u) for u in users]
        return PaginatedResponse(
            data=data,
            page=PageInfo(next_cursor=next_cursor, has_more=has_more, limit=limit),
        )

    async def get_user(
        self, session: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> UserResponse:
        user = await session.get(User, user_id)
        if not user or user.organization_id != organization_id:
            raise UserNotFoundError()

        return await self._build_user_response(session, user)

    async def invite_user(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        data: UserInviteRequest,
        actor_id: Optional[uuid.UUID] = None,
    ) -> UserResponse:
        # 1. Unique email check within organization
        existing_email = await session.execute(
            select(User).where(
                User.organization_id == organization_id,
                func.lower(User.email) == data.email.lower(),
            )
        )
        if existing_email.scalar_one_or_none():
            raise UserAlreadyExistsError()

        # 2. Unique employee_code check if provided
        if data.employee_code:
            existing_code = await session.execute(
                select(User).where(
                    User.organization_id == organization_id,
                    User.employee_code == data.employee_code,
                )
            )
            if existing_code.scalar_one_or_none():
                raise DuplicateCodeError(data.employee_code)

        # 3. Create User record
        user = User(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name=data.name,
            email=data.email.lower(),
            phone=data.phone,
            employee_code=data.employee_code,
            user_type=data.user_type,
            home_unit_id=data.home_unit_id,
            manager_user_id=data.manager_user_id,
            status="invited",
            version=1,
            created_at=datetime.utcnow(),
        )
        session.add(user)

        # 4. If home_unit_id provided, create UnitMembership
        if data.home_unit_id:
            membership = UnitMembership(
                id=uuid.uuid4(),
                user_id=user.id,
                unit_id=data.home_unit_id,
                member_role="home_unit",
            )
            session.add(membership)

        import secrets
        from datetime import timedelta, timezone
        inv_token = f"inv_{secrets.token_urlsafe(16)}"
        now = datetime.now(timezone.utc)
        cred = UserCredential(
            user_id=user.id,
            password_hash="",  # Not set until invitation is accepted
            invitation_token=inv_token,
            invitation_token_expires_at=now + timedelta(hours=72),
        )
        session.add(cred)

        await session.commit()
        await session.refresh(user)

        # 5. Publish domain event
        await event_publisher.publish(
            "identity.user.invited.v1",
            {
                "user_id": str(user.id),
                "organization_id": str(organization_id),
                "email": user.email,
                "invitation_token": inv_token,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )


        return await self._build_user_response(session, user)

    async def update_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        data: UserUpdateRequest,
        if_match: Optional[str] = None,
    ) -> UserResponse:
        user = await session.get(User, user_id)
        if not user or user.organization_id != organization_id:
            raise UserNotFoundError()

        # Concurrency check (If-Match)
        if if_match is not None:
            clean_match = if_match.strip(' "')
            if clean_match.isdigit() and int(clean_match) != user.version:
                raise PreconditionFailedError(
                    f"ETag mismatch. Current version is '{user.version}'"
                )

        if data.name is not None:
            user.name = data.name
        if data.phone is not None:
            user.phone = data.phone
        if data.manager_user_id is not None:
            user.manager_user_id = data.manager_user_id
        if data.home_unit_id is not None:
            user.home_unit_id = data.home_unit_id
            # Ensure UnitMembership exists
            membership_res = await session.execute(
                select(UnitMembership).where(
                    UnitMembership.user_id == user.id,
                    UnitMembership.member_role == "home_unit",
                )
            )
            membership = membership_res.scalar_one_or_none()
            if membership:
                membership.unit_id = data.home_unit_id
            else:
                session.add(
                    UnitMembership(
                        id=uuid.uuid4(),
                        user_id=user.id,
                        unit_id=data.home_unit_id,
                        member_role="home_unit",
                    )
                )

        user.version += 1
        await session.commit()
        await session.refresh(user)

        await event_publisher.publish(
            "identity.user.updated.v1",
            {"user_id": str(user.id), "version": user.version},
        )

        return await self._build_user_response(session, user)

    async def deactivate_user(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        data: UserDeactivateRequest,
        if_match: Optional[str] = None,
        actor_id: Optional[uuid.UUID] = None,
    ) -> UserResponse:
        user = await session.get(User, user_id)
        if not user or user.organization_id != organization_id:
            raise UserNotFoundError()

        # Concurrency check
        if if_match is not None:
            clean_match = if_match.strip(' "')
            if clean_match.isdigit() and int(clean_match) != user.version:
                raise PreconditionFailedError(
                    f"ETag mismatch. Current version is '{user.version}'"
                )

        user.status = "deactivated"
        user.version += 1

        # Revoke all active refresh tokens immediately
        tokens_res = await session.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        for token in tokens_res.scalars().all():
            token.revoked_at = datetime.utcnow()

        await session.commit()
        await session.refresh(user)

        await event_publisher.publish(
            "identity.user.deactivated.v1",
            {
                "user_id": str(user.id),
                "reason": data.reason,
                "reassign_to_user_id": str(data.reassign_to_user_id)
                if data.reassign_to_user_id
                else None,
                "actor_id": str(actor_id) if actor_id else None,
            },
        )

        return await self._build_user_response(session, user)


user_service = UserService()
