"""
User-based access control.

Every check reads the permissions granted directly to the acting user
(`user_permissions`). A grant covers either the whole organization or one org unit and
everything below it (matched on the unit's materialized `path`), optionally narrowed to
the user's own records.

Client administrators are the tenant superuser: they hold every permission in every
organization of their client.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import PermissionDeniedError
from models.org_unit import OrgUnit
from models.user import User
from models.user_permission import UserPermission


@dataclass(frozen=True)
class Grant:
    permission: str
    scope_unit_id: Optional[uuid.UUID]
    # Live path of the scope unit; None means organization-wide.
    scope_path: Optional[str]
    self_only: bool

    def covers(self, path: Optional[str], owner_id: Optional[uuid.UUID], actor_id: uuid.UUID) -> bool:
        if self.self_only and owner_id != actor_id:
            return False
        if self.scope_path is None:
            return True
        return path is not None and path.startswith(self.scope_path)

    def contains_grant(self, other: "Grant") -> bool:
        """True when this grant is at least as broad as `other` (used to stop escalation)."""
        if self.permission != other.permission:
            return False
        if self.self_only and not other.self_only:
            return False
        if self.scope_path is None:
            return True
        return other.scope_path is not None and other.scope_path.startswith(self.scope_path)


@dataclass
class Actor:
    """The signed-in user acting inside one organization, with their effective grants."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    user_type: str
    name: str
    is_superuser: bool = False
    grants: list[Grant] = field(default_factory=list)

    def grants_for(self, permission: str) -> list[Grant]:
        return [g for g in self.grants if g.permission == permission]

    def has(self, permission: str) -> bool:
        return self.is_superuser or bool(self.grants_for(permission))

    def has_org_wide(self, permission: str) -> bool:
        return self.is_superuser or any(
            g.scope_path is None and not g.self_only for g in self.grants_for(permission)
        )

    def require(self, permission: str) -> None:
        if not self.has(permission):
            raise PermissionDeniedError(permission)

    def can(self, permission: str, path: Optional[str], owner_id: Optional[uuid.UUID] = None) -> bool:
        """Can the actor perform `permission` on a record at `path` owned by `owner_id`?"""
        if self.is_superuser:
            return True
        return any(g.covers(path, owner_id, self.user_id) for g in self.grants_for(permission))

    def can_grant(self, wanted: Grant) -> bool:
        """An actor may only hand out (or take away) access they hold at least as broadly."""
        if self.is_superuser:
            return True
        return any(g.contains_grant(wanted) for g in self.grants_for(wanted.permission))

    def user_visibility_filter(self, permission: str) -> ColumnElement[bool]:
        """
        SQL condition restricting `User` rows to those the actor may see for `permission`,
        so list endpoints never leak rows (or counts) outside the actor's scopes.
        A user record lives at its home unit's path and is "owned" by the user themselves.
        """
        if self.has_org_wide(permission):
            return true()

        conditions: list[ColumnElement[bool]] = []
        for grant in self.grants_for(permission):
            if grant.self_only:
                conditions.append(User.id == self.user_id)
                continue
            if grant.scope_path is None:
                return true()
            units_in_scope = select(OrgUnit.id).where(
                OrgUnit.organization_id == self.organization_id,
                OrgUnit.path.startswith(grant.scope_path),
            )
            conditions.append(User.home_unit_id.in_(units_in_scope))
        return or_(*conditions) if conditions else false()


def _is_current(valid_to: Optional[datetime], now: datetime) -> bool:
    if valid_to is None:
        return True
    if valid_to.tzinfo is None:
        valid_to = valid_to.replace(tzinfo=timezone.utc)
    return valid_to > now


async def load_grants(session: AsyncSession, user_id: uuid.UUID) -> list[Grant]:
    """The user's current (non-expired) grants with live scope paths."""
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(select(UserPermission).where(UserPermission.user_id == user_id))
    ).unique().scalars().all()

    grants: list[Grant] = []
    for row in rows:
        if not _is_current(row.valid_to, now):
            continue
        if row.scope_unit_id is not None and row.scope_unit is None:
            continue  # scope unit vanished: the grant covers nothing
        grants.append(Grant(
            permission=row.permission_code,
            scope_unit_id=row.scope_unit_id,
            scope_path=row.scope_unit.path if row.scope_unit else None,
            self_only=row.self_only,
        ))
    return grants
