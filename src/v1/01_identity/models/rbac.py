import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(200), primary_key=True)
    service: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        String(200), ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class RoleAssignment(Base):
    """
    Grants a role to a user within the scope of an org-unit/vertical pair.
    scope_path further narrows the scope to a subtree of the org hierarchy.
    """

    __tablename__ = "role_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_vertical_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("org_unit_verticals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Materialized path representing the scope subtree (ltree equivalent)
    scope_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    include_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
