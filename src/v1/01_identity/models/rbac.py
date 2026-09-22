import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.base import Base
from database.types import UUIDType

if TYPE_CHECKING:
    from models.org_unit import OrgUnit
    from models.user import User
    from models.vertical import Vertical


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(200), primary_key=True)
    service: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_role_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        String(200), ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )

    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")


class RoleAssignment(Base):
    """
    Grants a role to a user within an optional org-unit scope or vertical.
    scope_path further narrows the scope to a subtree of the org hierarchy.
    """

    __tablename__ = "role_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope_vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("verticals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    self_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    granted_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="joined")
    role: Mapped["Role"] = relationship("Role", foreign_keys=[role_id], lazy="joined")
    scope_unit: Mapped[Optional["OrgUnit"]] = relationship("OrgUnit", foreign_keys=[scope_unit_id], lazy="joined")
    scope_vertical: Mapped[Optional["Vertical"]] = relationship("Vertical", foreign_keys=[scope_vertical_id], lazy="joined")
    granted_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[granted_by_id], lazy="joined")

