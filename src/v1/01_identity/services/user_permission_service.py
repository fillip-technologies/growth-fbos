"""
Granting and revoking permissions on individual users (user-based access control).

Role presets expand into plain per-user permissions here; nothing downstream ever
reads roles to make an access decision.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import PermissionDeniedError, ValidationFailedError
from models.org_unit import OrgUnit
from models.rbac import Permission, Role, RoleAssignment
from models.user import User
from models.user_permission import UserPermission
from schemas.user import (
    HomeUnitRef,
    ManagerRef,
    PermissionGrantInput,
    RolePresetInput,
    UserPermissionResponse,
    UserPermissionsResponse,
)
from services.access_control import Actor, Grant

logger = logging.getLogger("identity.user_permission_service")


@dataclass
class ResolvedGrant:
    """A validated permission ready to be stored on a user."""

    code: str
    scope_unit_id: Optional[uuid.UUID]
    scope_path: Optional[str]
    self_only: bool
    valid_to: Optional[datetime]
    source_role_id: Optional[uuid.UUID] = None

    @property
    def key(self) -> tuple[str, Optional[uuid.UUID]]:
        return self.code, self.scope_unit_id

    def as_grant(self) -> Grant:
        return Grant(self.code, self.scope_unit_id, self.scope_path, self.self_only)


@dataclass
class ResolvedPreset:
    role: Role
    scope_unit_id: Optional[uuid.UUID]
    scope_path: Optional[str]
    self_only: bool
    valid_to: Optional[datetime]


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _merge(existing: ResolvedGrant, incoming: ResolvedGrant) -> ResolvedGrant:
    """Two grants of the same permission in the same scope collapse into the broader one."""
    valid_to = None
    if existing.valid_to is not None and incoming.valid_to is not None:
        valid_to = max(_as_utc(existing.valid_to), _as_utc(incoming.valid_to))
    return ResolvedGrant(
        code=existing.code,
        scope_unit_id=existing.scope_unit_id,
        scope_path=existing.scope_path,
        self_only=existing.self_only and incoming.self_only,
        valid_to=valid_to,
        source_role_id=existing.source_role_id or incoming.source_role_id,
    )


class UserPermissionService:
    async def _scope_paths(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        unit_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, str]:
        if not unit_ids:
            return {}
        units = (
            await session.execute(
                select(OrgUnit).where(
                    OrgUnit.id.in_(unit_ids),
                    OrgUnit.organization_id == organization_id,
                    OrgUnit.status == "active",
                )
            )
        ).unique().scalars().all()
        return {unit.id: unit.path for unit in units}

    async def resolve(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        permissions: list[PermissionGrantInput],
        presets: list[RolePresetInput],
    ) -> tuple[list[ResolvedGrant], list[ResolvedPreset]]:
        """
        Validate direct permissions and role presets against this organization and expand
        them into one de-duplicated list of grants. Every problem is reported at once.
        """
        errors: list[dict[str, str]] = []
        now = datetime.now(timezone.utc)

        unit_ids = {p.scope_unit_id for p in permissions if p.scope_unit_id}
        unit_ids |= {p.scope_unit_id for p in presets if p.scope_unit_id}
        scope_paths = await self._scope_paths(session, organization_id, unit_ids)
        catalog = set((await session.execute(select(Permission.code))).scalars().all())

        resolved: dict[tuple[str, Optional[uuid.UUID]], ResolvedGrant] = {}

        def add(grant: ResolvedGrant) -> None:
            existing = resolved.get(grant.key)
            resolved[grant.key] = _merge(existing, grant) if existing else grant

        def check_scope_and_expiry(field: str, unit_id: Optional[uuid.UUID], valid_to: Optional[datetime]) -> bool:
            ok = True
            if unit_id is not None and unit_id not in scope_paths:
                errors.append({"field": f"{field}.scope_unit_id", "issue": "Unknown or inactive branch, department or team"})
                ok = False
            if valid_to is not None and _as_utc(valid_to) <= now:
                errors.append({"field": f"{field}.valid_to", "issue": "Must be in the future"})
                ok = False
            return ok

        for index, item in enumerate(permissions):
            field = f"permissions[{index}]"
            scope_ok = check_scope_and_expiry(field, item.scope_unit_id, item.valid_to)
            if item.code not in catalog:
                errors.append({"field": f"{field}.code", "issue": f"Unknown permission '{item.code}'"})
                continue
            if scope_ok:
                add(ResolvedGrant(
                    code=item.code,
                    scope_unit_id=item.scope_unit_id,
                    scope_path=scope_paths.get(item.scope_unit_id) if item.scope_unit_id else None,
                    self_only=item.self_only,
                    valid_to=item.valid_to,
                ))

        resolved_presets: list[ResolvedPreset] = []
        for index, item in enumerate(presets):
            field = f"role_assignments[{index}]"
            scope_ok = check_scope_and_expiry(field, item.scope_unit_id, item.valid_to)
            role = await self._find_role(session, organization_id, item)
            if role is None:
                errors.append({"field": f"{field}.role_id", "issue": "Unknown role"})
                continue
            if not scope_ok:
                continue
            resolved_presets.append(ResolvedPreset(
                role, item.scope_unit_id, scope_paths.get(item.scope_unit_id) if item.scope_unit_id else None,
                item.self_only, item.valid_to,
            ))
            for role_permission in role.role_permissions:
                add(ResolvedGrant(
                    code=role_permission.permission_code,
                    scope_unit_id=item.scope_unit_id,
                    scope_path=scope_paths.get(item.scope_unit_id) if item.scope_unit_id else None,
                    self_only=item.self_only,
                    valid_to=item.valid_to,
                    source_role_id=role.id,
                ))

        if errors:
            raise ValidationFailedError(errors)
        return list(resolved.values()), resolved_presets

    async def _find_role(
        self, session: AsyncSession, organization_id: uuid.UUID, preset: RolePresetInput
    ) -> Optional[Role]:
        # Roles are per organization (including the `admin` preset); another org's role
        # must never be applied here.
        query = select(Role).where(Role.organization_id == organization_id)
        if preset.role_id is not None:
            query = query.where(Role.id == preset.role_id)
        else:
            query = query.where(func.lower(Role.code) == preset.role_code.lower())
        return (await session.execute(query)).unique().scalar_one_or_none()

    def assert_can_grant(self, actor: Actor, grants: list[ResolvedGrant]) -> None:
        """No escalation: an actor can only hand out access they hold at least as broadly."""
        for grant in grants:
            if not actor.can_grant(grant.as_grant()):
                raise PermissionDeniedError(
                    grant.code,
                    f"You can't grant '{grant.code}' beyond the access you hold yourself",
                )

    def add_to_user(
        self,
        session: AsyncSession,
        actor: Actor,
        user: User,
        grants: list[ResolvedGrant],
        presets: list[ResolvedPreset],
        reason: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        for grant in grants:
            session.add(UserPermission(
                id=uuid.uuid4(),
                organization_id=user.organization_id,
                user_id=user.id,
                permission_code=grant.code,
                scope_unit_id=grant.scope_unit_id,
                self_only=grant.self_only,
                source_role_id=grant.source_role_id,
                granted_by_id=actor.user_id,
                granted_at=now,
                valid_to=grant.valid_to,
            ))
        # Presets are also recorded as role assignments, so the UI can show which
        # presets a user was given and `GET /users?role_code=` keeps working.
        for preset in presets:
            session.add(RoleAssignment(
                id=uuid.uuid4(),
                organization_id=user.organization_id,
                user_id=user.id,
                role_id=preset.role.id,
                scope_unit_id=preset.scope_unit_id,
                scope_path=preset.scope_path,
                self_only=preset.self_only,
                valid_from=now,
                valid_to=preset.valid_to,
                granted_by_id=actor.user_id,
                reason=reason,
            ))

    async def replace_for_user(
        self,
        session: AsyncSession,
        actor: Actor,
        user: User,
        grants: list[ResolvedGrant],
        presets: list[ResolvedPreset],
        reason: str,
    ) -> tuple[list[str], list[str]]:
        """
        Make `grants` the user's complete permission set. Every row that is added,
        removed or changed must be within what the actor could grant, so a scoped admin
        can't strip (or hand out) access beyond their own. Returns (added, removed) codes.
        """
        current_rows = (
            await session.execute(select(UserPermission).where(UserPermission.user_id == user.id))
        ).unique().scalars().all()
        current = {(row.permission_code, row.scope_unit_id): row for row in current_rows}
        wanted = {grant.key: grant for grant in grants}

        removed_rows = [row for key, row in current.items() if key not in wanted]
        added = [grant for key, grant in wanted.items() if key not in current]
        changed = [
            grant for key, grant in wanted.items()
            if key in current and (
                current[key].self_only != grant.self_only
                or _as_utc(current[key].valid_to) != _as_utc(grant.valid_to)
            )
        ]

        def row_as_grant(row: UserPermission) -> Grant:
            return Grant(
                row.permission_code, row.scope_unit_id,
                row.scope_unit.path if row.scope_unit else None, row.self_only,
            )

        self.assert_can_grant(actor, added + changed)
        for row in removed_rows + [current[g.key] for g in changed]:
            if not actor.can_grant(row_as_grant(row)):
                raise PermissionDeniedError(
                    row.permission_code,
                    f"You can't remove '{row.permission_code}': it is broader than the access you hold",
                )

        for row in removed_rows:
            await session.delete(row)
        for grant in changed:
            row = current[grant.key]
            row.self_only = grant.self_only
            row.valid_to = grant.valid_to
            row.granted_by_id = actor.user_id
            row.granted_at = datetime.now(timezone.utc)

        # A preset record stays only while the user still holds all of that role's
        # permissions in its scope; otherwise it would misreport where access came from.
        existing_presets = (
            await session.execute(select(RoleAssignment).where(RoleAssignment.user_id == user.id))
        ).unique().scalars().all()
        for assignment in existing_presets:
            role_codes = {rp.permission_code for rp in assignment.role.role_permissions} if assignment.role else set()
            if not role_codes or any((code, assignment.scope_unit_id) not in wanted for code in role_codes):
                await session.delete(assignment)
        self.add_to_user(session, actor, user, added, presets, reason)
        return sorted({g.code for g in added + changed}), sorted({r.permission_code for r in removed_rows})

    async def list_for_user(self, session: AsyncSession, user: User) -> UserPermissionsResponse:
        rows = (
            await session.execute(
                select(UserPermission)
                .where(UserPermission.user_id == user.id)
                .order_by(UserPermission.permission_code, UserPermission.granted_at)
            )
        ).unique().scalars().all()

        role_ids = {row.source_role_id for row in rows if row.source_role_id}
        granter_ids = {row.granted_by_id for row in rows if row.granted_by_id}
        roles = {
            role.id: role.code
            for role in (await session.execute(select(Role).where(Role.id.in_(role_ids)))).unique().scalars()
        } if role_ids else {}
        granters = {
            u.id: u.name
            for u in (await session.execute(select(User).where(User.id.in_(granter_ids)))).scalars()
        } if granter_ids else {}

        return UserPermissionsResponse(
            user_id=user.id,
            is_superuser=user.user_type == "client_admin",
            permissions=[
                UserPermissionResponse(
                    id=row.id,
                    code=row.permission_code,
                    scope_unit=HomeUnitRef(
                        id=row.scope_unit.id, name=row.scope_unit.name, unit_type=row.scope_unit.unit_type
                    ) if row.scope_unit else None,
                    self_only=row.self_only,
                    source_role=roles.get(row.source_role_id) if row.source_role_id else None,
                    valid_to=_as_utc(row.valid_to),
                    granted_by=ManagerRef(id=row.granted_by_id, name=granters[row.granted_by_id])
                    if row.granted_by_id in granters else None,
                    granted_at=_as_utc(row.granted_at),
                )
                for row in rows
            ],
        )


user_permission_service = UserPermissionService()
