import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaxConfigEntry(Base):
    """
    One dated piece of an organization's tax configuration: a regime, component, rate,
    category, rule, jurisdiction, withholding section, deadline or number format
    (`finance/tax/config_schema.py` says what `data` holds for each kind). Entries are in
    effect from `effective_from` (inclusive) to `effective_to` (exclusive, open when null);
    entries of one kind and code never overlap.
    """

    __tablename__ = "tax_config_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "kind", "code", "effective_from", name="uq_tax_config_entries_key"),
        Index("ix_tax_config_entries_org_kind", "organization_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    # "manual", or the pack version it came from ("pack:in_gst@1").
    origin: Mapped[str] = mapped_column(String(60), nullable=False, default="manual")
    # Edited after a pack put it there: a pack upgrade will not overwrite it without asking.
    locally_modified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TaxConfigRevision(Base):
    """
    Each change to an organization's tax configuration bumps its revision. Documents store
    the revision their taxes were worked out under, so an audit can see exactly which
    configuration produced them.
    """

    __tablename__ = "tax_config_revisions"
    __table_args__ = (UniqueConstraint("organization_id", "revision", name="uq_tax_config_revisions_org_revision"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class TaxPackApplication(Base):
    """A pack version applied to an organization's configuration, and what it changed."""

    __tablename__ = "tax_pack_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    pack_code: Mapped[str] = mapped_column(String(60), nullable=False)
    pack_version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    applied_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
