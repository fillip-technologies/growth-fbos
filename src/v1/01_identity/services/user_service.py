from datetime import datetime, timedelta, timezone
import logging
import secrets
from typing import Optional
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import (
    DuplicateCodeError,
    IdentityServiceError,
    OrganizationNotFoundError,
    OrganizationUserLimitReachedError,
    OrgUnitNotFoundError,
    PermissionDeniedError,
    PreconditionFailedError,
    SelfModificationError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserNotInvitedError,
    ValidationFailedError,
)
from models.auth import RefreshToken, UserCredential
from models.client import Client
from models.membership import UnitMembership
from models.org_unit import OrgUnit
from models.organization import Organization
from models.rbac import Role, RoleAssignment
from models.user import User
from schemas.common import PageInfo, PaginatedResponse
from schemas.user import (
    HomeUnitRef,
    InvitationResponse,
    ManagerRef,
    TeamRef,
    UserDeactivateRequest,
    UserInviteRequest,
    UserPermissionsReplace,
    UserPermissionsResponse,
    UserResponse,
    UserStatus,
    UserUpdateRequest,
)
from services.access_control import Actor
from services.event_publisher import event_publisher
from services.rate_limiter import rate_limiter
from services.unit_members import HOME_UNIT_ROLE, TEAM_MEMBER_ROLE, belongs_to
from services.user_permission_service import user_permission_service
from utils.dates import iso_utc

logger = logging.getLogger("identity.user_service")

INVITATION_TTL = timedelta(hours=72)

PERM_READ = "identity.user.read"
PERM_CREATE = "identity.user.create"
PERM_UPDATE = "identity.user.update"
PERM_DEACTIVATE = "identity.user.deactivate"
PERM_ACCESS_READ = "identity.user_permission.read"
PERM_ACCESS_MANAGE = "identity.user_permission.manage"


def _new_invitation_token() -> tuple[str, datetime]:
    return f"inv_{secrets.token_urlsafe(24)}", datetime.now(timezone.utc) + INVITATION_TTL


def _assert_version(if_match: str, current_version: int) -> None:
    """Strict If-Match: accepts `3`, `"3"` or `W/"3"`; anything else is a mismatch."""
    tag = if_match.strip()
    if tag.startswith("W/"):
        tag = tag[2:]
    tag = tag.strip('"')
    if not tag.isdigit() or int(tag) != current_version:
        raise PreconditionFailedError(f"ETag mismatch. Current version is '{current_version}'")


class UserService:
    # ------------------------------------------------------------------ helpers

    async def _build_user_response(
        self, session: AsyncSession, user: User, teams: Optional[list[TeamRef]] = None
    ) -> UserResponse:
        """`teams` can be passed in when a whole page was loaded at once (see `_teams_of`)."""
        if teams is None:
            teams = (await self._teams_of(session, [user.id])).get(user.id, [])

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
        invitation_expires_at = (
            iso_utc(cred.invitation_token_expires_at)
            if cred and user.status == "invited" and cred.invitation_token
            else None
        )

        return UserResponse(
            id=user.id,
            employee_code=user.employee_code,
            name=user.name,
            email=user.email,
            phone=user.phone,
            user_type=user.user_type,
            status=user.status,
            home_unit=home_unit_ref,
            teams=teams,
            manager=manager_ref,
            mfa_enabled=bool(cred and cred.otp_enabled),
            last_login_at=iso_utc(user.last_login_at),
            version=user.version,
            created_at=iso_utc(user.created_at),
            invitation_expires_at=invitation_expires_at,
        )

    async def _teams_of(self, session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[TeamRef]]:
        """
        Teams each user is an extra member of, by name, in one query. `unit_memberships` has no
        unique index, so a double submit can leave a duplicate row; DISTINCT folds it away.
        """
        if not user_ids:
            return {}
        rows = await session.execute(
            select(UnitMembership.user_id, OrgUnit.id, OrgUnit.name)
            .join(OrgUnit, OrgUnit.id == UnitMembership.unit_id)
            .where(UnitMembership.user_id.in_(user_ids), UnitMembership.member_role == TEAM_MEMBER_ROLE)
            .distinct()
            .order_by(OrgUnit.name)
        )
        teams_by_user: dict[uuid.UUID, list[TeamRef]] = {}
        for user_id, team_id, team_name in rows:
            teams_by_user.setdefault(user_id, []).append(TeamRef(id=team_id, name=team_name))
        return teams_by_user

    async def _unit_path(self, session: AsyncSession, unit_id: Optional[uuid.UUID]) -> Optional[str]:
        if unit_id is None:
            return None
        unit = await session.get(OrgUnit, unit_id)
        return unit.path if unit else None

    async def _load_user(
        self, session: AsyncSession, actor: Actor, user_id: uuid.UUID, permission: str
    ) -> User:
        """
        Load a user the actor may act on with `permission`. Users outside every scope the
        actor can read are answered 404 (existence is information); visible users the
        actor can't act on get 403 with the missing permission.
        """
        user = await session.get(User, user_id)
        if not user or user.organization_id != actor.organization_id:
            raise UserNotFoundError()

        path = await self._unit_path(session, user.home_unit_id)
        if actor.can(permission, path, owner_id=user.id):
            return user
        if actor.can(PERM_READ, path, owner_id=user.id):
            raise PermissionDeniedError(permission)
        raise UserNotFoundError()

    async def load_user_for(
        self,
        session: AsyncSession,
        actor: Actor,
        user_id: uuid.UUID,
        permission: str,
        manage_action: Optional[str] = None,
    ) -> User:
        """
        A user the actor may act on with `permission` (404 outside every readable scope, 403
        when visible but not allowed). With `manage_action`, also refuses the actor's own
        account and, for anyone but a client admin, a client admin's.
        """
        user = await self._load_user(session, actor, user_id, permission)
        if manage_action:
            self._assert_may_manage(actor, user, manage_action)
        return user

    def _assert_may_manage(self, actor: Actor, user: User, action: str) -> None:
        """The tenant superuser (client admin) can only be managed by a client admin."""
        if user.id == actor.user_id:
            raise SelfModificationError(action)
        if user.user_type == "client_admin" and not actor.is_superuser:
            raise PermissionDeniedError(
                "client_admin", "Only a client administrator can change a client administrator"
            )

    async def _resolve_home_unit(
        self, session: AsyncSession, actor: Actor, unit_id: Optional[uuid.UUID], permission: str
    ) -> Optional[OrgUnit]:
        """A home unit must be an active unit of this organization inside the actor's scope."""
        if unit_id is None:
            if not actor.has_org_wide(permission):
                raise ValidationFailedError.for_field(
                    "home_unit_id", "Required: you can only place people in branches, departments or teams you manage"
                )
            return None

        unit = await session.get(OrgUnit, unit_id)
        if not unit or unit.organization_id != actor.organization_id or unit.status != "active":
            raise ValidationFailedError.for_field("home_unit_id", "Unknown or inactive branch, department or team")
        if not actor.can(permission, unit.path):
            raise PermissionDeniedError(permission, "You can't place users in this organization unit")
        return unit

    def _assert_changeable(self, actor: Actor, user: User) -> None:
        """Rules for changing anything about a user: their profile, their place or their teams."""
        if user.user_type == "client_admin" and not actor.is_superuser:
            raise PermissionDeniedError(
                "client_admin", "Only a client administrator can change a client administrator"
            )
        if user.status == "deactivated":
            raise IdentityServiceError(
                status_code=409, code="USER_DEACTIVATED", message="A deactivated user can't be changed",
            )

    async def _change_home_unit(
        self, session: AsyncSession, actor: Actor, user: User, unit_id: Optional[uuid.UUID]
    ) -> None:
        """
        Move the user to `unit_id`, or clear their place when it is None (company-wide rights
        only). Moving needs update rights in the destination unit too.
        """
        unit = await self._resolve_home_unit(session, actor, unit_id, PERM_UPDATE)
        await session.execute(
            delete(UnitMembership).where(
                UnitMembership.user_id == user.id, UnitMembership.member_role == HOME_UNIT_ROLE
            )
        )
        if unit is None:
            user.home_unit_id = None
            return

        user.home_unit_id = unit.id
        # Working in the team now: an extra membership of it would list them there twice.
        await session.execute(
            delete(UnitMembership).where(
                UnitMembership.user_id == user.id,
                UnitMembership.unit_id == unit.id,
                UnitMembership.member_role == TEAM_MEMBER_ROLE,
            )
        )
        session.add(UnitMembership(
            id=uuid.uuid4(), user_id=user.id, unit_id=unit.id, member_role=HOME_UNIT_ROLE,
        ))

    async def _publish_user_updated(self, actor: Actor, user: User, changed: list[str]) -> None:
        await event_publisher.publish(
            "identity.user.updated.v1",
            {
                "user_id": str(user.id),
                "organization_id": str(user.organization_id),
                "changed": changed,
                "version": user.version,
                "actor_id": str(actor.user_id),
            },
        )

    async def _resolve_manager(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        manager_id: Optional[uuid.UUID],
        subject_id: Optional[uuid.UUID] = None,
    ) -> Optional[User]:
        if manager_id is None:
            return None
        if manager_id == subject_id:
            raise ValidationFailedError.for_field("manager_user_id", "A user can't be their own manager")

        manager = await session.get(User, manager_id)
        if not manager or manager.organization_id != organization_id:
            raise ValidationFailedError.for_field("manager_user_id", "Unknown user")
        if manager.status == "deactivated":
            raise ValidationFailedError.for_field("manager_user_id", "The manager is deactivated")

        # Walk up the chain so A -> B -> A loops can't be created.
        seen: set[uuid.UUID] = {manager.id}
        current = manager
        while subject_id is not None and current.manager_user_id is not None:
            if current.manager_user_id == subject_id:
                raise ValidationFailedError.for_field(
                    "manager_user_id", "This would create a reporting loop"
                )
            if current.manager_user_id in seen:
                break
            seen.add(current.manager_user_id)
            current = await session.get(User, current.manager_user_id)
            if current is None:
                break
        return manager

    async def _assert_user_quota(self, session: AsyncSession, organization_id: uuid.UUID, client: Optional[Client]) -> None:
        if client is None or client.max_users_per_org is None:
            return
        seats_used = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.organization_id == organization_id, User.status.in_(["active", "invited"]))
            )
        ).scalar_one()
        if seats_used >= client.max_users_per_org:
            raise OrganizationUserLimitReachedError(limit=client.max_users_per_org, current=seats_used)

    async def _assert_email_free(self, session: AsyncSession, actor: Actor, email: str) -> None:
        # Emails are unique across the platform (sign-in resolves by email), so check
        # globally; only reveal the existing id when it is in the actor's own organization.
        existing = (
            await session.execute(select(User).where(func.lower(User.email) == email))
        ).scalar_one_or_none()
        if existing is None:
            return
        same_org = existing.organization_id == actor.organization_id
        raise UserAlreadyExistsError(existing.id if same_org else None)

    async def _assert_employee_code_free(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        employee_code: Optional[str],
    ) -> None:
        if not employee_code:
            return
        taken = (
            await session.execute(
                select(User.id).where(
                    User.organization_id == organization_id,
                    func.lower(User.employee_code) == employee_code.lower(),
                )
            )
        ).first()
        if taken:
            raise DuplicateCodeError(employee_code)

    async def _invitation_event(
        self,
        session: AsyncSession,
        actor: Actor,
        user: User,
        token: str,
        expires_at: datetime,
        resent: bool = False,
    ) -> dict:
        org = await session.get(Organization, user.organization_id)
        client = await session.get(Client, org.client_id) if org else None
        return {
            "user_id": str(user.id),
            "organization_id": str(user.organization_id),
            "organization_name": org.name if org else None,
            "client_name": client.name if client else None,
            "email": user.email,
            "name": user.name,
            "user_type": user.user_type,
            "invitation_token": token,
            "expires_at": expires_at.isoformat(),
            "invited_by_name": actor.name,
            "actor_id": str(actor.user_id),
            "resent": resent,
        }

    # ------------------------------------------------------------------ queries

    async def list_users(
        self,
        session: AsyncSession,
        actor: Actor,
        status: Optional[UserStatus] = None,
        unit_id: Optional[uuid.UUID] = None,
        team_id: Optional[uuid.UUID] = None,
        role_code: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> PaginatedResponse[UserResponse]:
        # Scope filtering happens in SQL so pages and counts never leak hidden users.
        query = select(User).where(
            User.organization_id == actor.organization_id,
            actor.user_visibility_filter(PERM_READ),
        )

        if status:
            query = query.where(User.status == status)

        if unit_id:
            # Where people work: their home unit is this unit or one below it.
            unit = await session.get(OrgUnit, unit_id)
            if not unit or unit.organization_id != actor.organization_id:
                return PaginatedResponse(data=[], page=PageInfo(next_cursor=None, has_more=False, limit=limit))
            units_below = select(OrgUnit.id).where(
                OrgUnit.organization_id == actor.organization_id,
                OrgUnit.path.startswith(unit.path),
            )
            query = query.where(User.home_unit_id.in_(units_below))

        if team_id:
            # Everyone in the team: those who work in it and its current extra members.
            team = await session.get(OrgUnit, team_id)
            if not team or team.organization_id != actor.organization_id or team.unit_type != "team":
                return PaginatedResponse(data=[], page=PageInfo(next_cursor=None, has_more=False, limit=limit))
            query = query.where(belongs_to(team))

        if role_code:
            holders = (
                select(RoleAssignment.user_id)
                .join(Role, Role.id == RoleAssignment.role_id)
                .where(
                    RoleAssignment.organization_id == actor.organization_id,
                    func.lower(Role.code) == role_code.lower(),
                )
            )
            query = query.where(User.id.in_(holders))

        if q:
            term = f"%{q.strip()}%"
            query = query.where(
                User.name.ilike(term) | User.email.ilike(term) | User.employee_code.ilike(term)
            )

        offset = int(cursor) if cursor and cursor.isdigit() else 0
        query = query.order_by(User.created_at.desc(), User.id.desc()).offset(offset).limit(limit + 1)
        users = list((await session.execute(query)).scalars().all())

        has_more = len(users) > limit
        users = users[:limit]
        teams_by_user = await self._teams_of(session, [u.id for u in users])
        return PaginatedResponse(
            data=[await self._build_user_response(session, u, teams_by_user.get(u.id, [])) for u in users],
            page=PageInfo(next_cursor=str(offset + limit) if has_more else None, has_more=has_more, limit=limit),
        )

    async def get_user(self, session: AsyncSession, actor: Actor, user_id: uuid.UUID) -> UserResponse:
        user = await self._load_user(session, actor, user_id, PERM_READ)
        return await self._build_user_response(session, user)

    # ------------------------------------------------------------------ invitation flow

    async def invite_user(
        self,
        session: AsyncSession,
        actor: Actor,
        data: UserInviteRequest,
    ) -> UserResponse:
        """
        Create the user in `invited` status with their initial permissions and send a
        single-use activation link valid for 72 hours. All checks run before anything is
        written; the whole invite is one transaction.
        """
        org = await session.get(Organization, actor.organization_id)
        if not org:
            raise OrganizationNotFoundError()
        if org.status != "active":
            raise IdentityServiceError(
                status_code=409, code="ORGANIZATION_NOT_ACTIVE",
                message="Users can't be invited into an inactive organization",
            )
        client = await session.get(Client, org.client_id)

        await self._assert_user_quota(session, org.id, client)
        await self._assert_email_free(session, actor, data.email)
        await self._assert_employee_code_free(session, org.id, data.employee_code)
        home_unit = await self._resolve_home_unit(session, actor, data.home_unit_id, PERM_CREATE)
        await self._resolve_manager(session, org.id, data.manager_user_id)

        grants, presets = [], []
        if data.permissions or data.role_assignments:
            actor.require(PERM_ACCESS_MANAGE)
            grants, presets = await user_permission_service.resolve(
                session, org.id, data.permissions, data.role_assignments
            )
            user_permission_service.assert_can_grant(actor, grants)

        now = datetime.now(timezone.utc)
        user = User(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=data.name,
            email=data.email,
            phone=data.phone,
            employee_code=data.employee_code,
            user_type=data.user_type,
            home_unit_id=home_unit.id if home_unit else None,
            manager_user_id=data.manager_user_id,
            status="invited",
            version=1,
            created_at=now,
        )
        session.add(user)
        await session.flush()

        if home_unit:
            session.add(UnitMembership(
                id=uuid.uuid4(), user_id=user.id, unit_id=home_unit.id, member_role=HOME_UNIT_ROLE,
            ))

        token, expires_at = _new_invitation_token()
        session.add(UserCredential(
            user_id=user.id,
            password_hash="",  # set when the invitation is accepted
            invitation_token=token,
            invitation_token_expires_at=expires_at,
        ))
        user_permission_service.add_to_user(session, actor, user, grants, presets, reason="Initial access on invitation")

        try:
            await session.commit()
        except IntegrityError:
            # Lost a race with a concurrent invite for the same email / code.
            await session.rollback()
            raise UserAlreadyExistsError()
        await session.refresh(user)

        await event_publisher.publish(
            "identity.user.invited.v1",
            await self._invitation_event(session, actor, user, token, expires_at),
        )
        return await self._build_user_response(session, user)

    async def resend_invitation(
        self,
        session: AsyncSession,
        actor: Actor,
        user_id: uuid.UUID,
    ) -> InvitationResponse:
        """Issue a fresh 72-hour link; the previous link stops working immediately."""
        user = await self._load_user(session, actor, user_id, PERM_CREATE)
        if user.status != "invited":
            raise UserNotInvitedError(user.status)
        if user.user_type == "client_admin" and not actor.is_superuser:
            raise PermissionDeniedError(
                "client_admin", "Only a client administrator can re-invite a client administrator"
            )
        rate_limiter.check(f"{user.id}:invitation", rate_class="invitation")

        token, expires_at = _new_invitation_token()
        cred = await session.get(UserCredential, user.id)
        if cred is None:
            cred = UserCredential(user_id=user.id, password_hash="")
            session.add(cred)
        cred.invitation_token = token
        cred.invitation_token_expires_at = expires_at
        await session.commit()

        await event_publisher.publish(
            "identity.user.invited.v1",
            await self._invitation_event(session, actor, user, token, expires_at, resent=True),
        )
        return InvitationResponse(user_id=user.id, email=user.email, expires_at=expires_at)

    # ------------------------------------------------------------------ changes

    async def update_user(
        self,
        session: AsyncSession,
        actor: Actor,
        user_id: uuid.UUID,
        data: UserUpdateRequest,
        if_match: str,
    ) -> UserResponse:
        user = await self._load_user(session, actor, user_id, PERM_UPDATE)
        _assert_version(if_match, user.version)
        self._assert_changeable(actor, user)

        provided = data.model_fields_set
        changed: list[str] = []

        if "name" in provided and data.name is not None and data.name != user.name:
            user.name = data.name
            changed.append("name")
        if "phone" in provided and data.phone != user.phone:
            user.phone = data.phone
            changed.append("phone")
        if "manager_user_id" in provided and data.manager_user_id != user.manager_user_id:
            await self._resolve_manager(session, user.organization_id, data.manager_user_id, subject_id=user.id)
            user.manager_user_id = data.manager_user_id
            changed.append("manager_user_id")
        if "home_unit_id" in provided and data.home_unit_id != user.home_unit_id:
            await self._change_home_unit(session, actor, user, data.home_unit_id)
            changed.append("home_unit_id")

        if not changed:
            return await self._build_user_response(session, user)

        user.version += 1
        await session.commit()
        await session.refresh(user)

        await self._publish_user_updated(actor, user, changed)
        return await self._build_user_response(session, user)

    async def deactivate_user(
        self,
        session: AsyncSession,
        actor: Actor,
        user_id: uuid.UUID,
        data: UserDeactivateRequest,
        if_match: str,
    ) -> UserResponse:
        """Revokes all sessions and any pending invitation. History is kept."""
        user = await self._load_user(session, actor, user_id, PERM_DEACTIVATE)
        _assert_version(if_match, user.version)
        self._assert_may_manage(actor, user, "deactivate")
        if user.status == "deactivated":
            return await self._build_user_response(session, user)

        if data.reassign_to_user_id is not None:
            replacement = await session.get(User, data.reassign_to_user_id)
            if (
                not replacement
                or replacement.organization_id != user.organization_id
                or replacement.id == user.id
                or replacement.status != "active"
            ):
                raise ValidationFailedError.for_field(
                    "reassign_to_user_id", "Must be another active user of this company"
                )

        now = datetime.now(timezone.utc)
        user.status = "deactivated"
        user.version += 1

        cred = await session.get(UserCredential, user.id)
        if cred:
            cred.invitation_token = None
            cred.invitation_token_expires_at = None
            cred.reset_token = None
            cred.reset_token_expires_at = None
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now.replace(tzinfo=None))
        )
        await session.commit()
        await session.refresh(user)

        await event_publisher.publish(
            "identity.user.deactivated.v1",
            {
                "user_id": str(user.id),
                "organization_id": str(user.organization_id),
                "reason": data.reason,
                "reassign_to_user_id": str(data.reassign_to_user_id) if data.reassign_to_user_id else None,
                "effective_at": now.isoformat(),
                "actor_id": str(actor.user_id),
            },
        )
        return await self._build_user_response(session, user)

    # ------------------------------------------------------------------ team memberships

    async def join_team(
        self, session: AsyncSession, actor: Actor, user_id: uuid.UUID, team_id: uuid.UUID
    ) -> tuple[TeamRef, bool]:
        """
        Make the user an extra member of a team; where they work doesn't change. Returns the
        team and whether they were added (False when they already were a member).
        """
        user, team = await self._load_team_change(session, actor, user_id, team_id)
        if team.status != "active":
            raise ValidationFailedError.for_field("team_id", "This team is inactive")
        if team.id == user.home_unit_id:
            raise ValidationFailedError.for_field("team_id", "They already work in this team")

        team_ref = TeamRef(id=team.id, name=team.name)
        already_member = (
            await session.execute(
                select(UnitMembership.id)
                .where(
                    UnitMembership.user_id == user.id,
                    UnitMembership.unit_id == team.id,
                    UnitMembership.member_role == TEAM_MEMBER_ROLE,
                )
                .limit(1)
            )
        ).first()
        if already_member:
            return team_ref, False

        session.add(UnitMembership(
            id=uuid.uuid4(), user_id=user.id, unit_id=team.id, member_role=TEAM_MEMBER_ROLE,
        ))
        await self._save_team_change(session, actor, user)
        return team_ref, True

    async def leave_team(
        self, session: AsyncSession, actor: Actor, user_id: uuid.UUID, team_id: uuid.UUID
    ) -> None:
        """End the user's extra membership of a team. Removing someone who isn't a member changes nothing."""
        user, team = await self._load_team_change(session, actor, user_id, team_id)
        if team.id == user.home_unit_id:
            raise ValidationFailedError.for_field(
                "team_id", "This is where they work. Move them, or clear their place, instead"
            )

        removed = await session.execute(
            delete(UnitMembership).where(
                UnitMembership.user_id == user.id,
                UnitMembership.unit_id == team.id,
                UnitMembership.member_role == TEAM_MEMBER_ROLE,
            )
        )
        if removed.rowcount == 0:
            return
        await self._save_team_change(session, actor, user)

    async def _load_team_change(
        self, session: AsyncSession, actor: Actor, user_id: uuid.UUID, team_id: uuid.UUID
    ) -> tuple[User, OrgUnit]:
        """
        The user and team for a membership change, under the rules for moving someone: update
        rights over the user and inside the team.
        """
        user = await self._load_user(session, actor, user_id, PERM_UPDATE)
        self._assert_changeable(actor, user)

        team = await session.get(OrgUnit, team_id)
        if not team or team.organization_id != actor.organization_id:
            raise OrgUnitNotFoundError()
        if team.unit_type != "team":
            raise ValidationFailedError.for_field(
                "team_id", "Only teams take extra members; to put someone in a branch or department, move them there"
            )
        if not actor.can(PERM_UPDATE, team.path):
            raise PermissionDeniedError(PERM_UPDATE, "You can't change who is in this team")
        return user, team

    async def _save_team_change(self, session: AsyncSession, actor: Actor, user: User) -> None:
        # Teams are part of the user's representation, so their version (the ETag) moves on.
        user.version += 1
        await session.commit()
        await session.refresh(user)
        await self._publish_user_updated(actor, user, ["teams"])

    # ------------------------------------------------------------------ per-user access

    async def get_permissions(
        self, session: AsyncSession, actor: Actor, user_id: uuid.UUID
    ) -> UserPermissionsResponse:
        user = await self._load_user(session, actor, user_id, PERM_ACCESS_READ)
        return await user_permission_service.list_for_user(session, user)

    async def replace_permissions(
        self,
        session: AsyncSession,
        actor: Actor,
        user_id: uuid.UUID,
        data: UserPermissionsReplace,
    ) -> UserPermissionsResponse:
        user = await self._load_user(session, actor, user_id, PERM_ACCESS_MANAGE)
        self._assert_may_manage(actor, user, "change the permissions of")
        if user.status == "deactivated":
            raise IdentityServiceError(
                status_code=409, code="USER_DEACTIVATED", message="A deactivated user can't be given access",
            )

        grants, presets = await user_permission_service.resolve(
            session, user.organization_id, data.permissions, data.role_assignments or []
        )
        added, removed = await user_permission_service.replace_for_user(
            session, actor, user, grants, presets, data.reason,
            replace_presets=data.role_assignments is not None,
        )
        await session.commit()

        if added or removed:
            await event_publisher.publish(
                "identity.user.permissions_changed.v1",
                {
                    "user_id": str(user.id),
                    "organization_id": str(user.organization_id),
                    "granted": added,
                    "revoked": removed,
                    "reason": data.reason,
                    "actor_id": str(actor.user_id),
                },
            )
        return await user_permission_service.list_for_user(session, user)


user_service = UserService()
