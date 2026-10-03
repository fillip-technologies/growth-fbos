import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType

if TYPE_CHECKING:
    from models.org_unit import OrgUnit


class UserPermission(Base):
    """
    One permission granted directly to one user — the unit of access control.

    Access is user-based: every authorization check reads these rows. Roles are only
    presets; applying a role copies its permissions here (recorded in `source_role_id`)
    and they can then be added or removed individually.

    Scope: `scope_unit_id` NULL means organization-wide; otherwise the grant covers that
    unit and everything below it. `self_only` narrows it to the user's own records.
    """

    __tablename__ = "user_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "permission_code", "scope_unit_id", name="uq_user_permission_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_code: Mapped[str] = mapped_column(
        String(200), ForeignKey("permissions.code", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    self_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_role_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True
    )
    granted_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Joined so a grant's live scope path is available without extra queries; the path
    # is read from the unit (never copied) so moving a unit can't leave stale scopes.
    scope_unit: Mapped[Optional["OrgUnit"]] = relationship(
        "OrgUnit", foreign_keys=[scope_unit_id], lazy="joined"
    )
