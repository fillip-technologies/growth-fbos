import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class ServiceCategory(Base):
    """
    Organization-defined grouping for the outside services clients use
    (e.g. Hosting, Insurance, Accounting, Telecom, Logistics).
    """

    __tablename__ = "service_categories"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_service_categories_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )


class ServiceProvider(Base):
    """
    An outside company or person that provides something to clients
    (e.g. Hostinger, LIC, a CA firm, Airtel). Entered once, reused across clients.
    """

    __tablename__ = "service_providers"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_service_providers_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("service_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )


class ClientServiceRecord(Base):
    """
    One outside service a client uses: a domain, an insurance policy, a telecom
    line, an accounting engagement, anything. Kind-specific details go in
    `attributes`. Never holds credentials.
    """

    __tablename__ = "client_services"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("service_providers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("service_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_no: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    managed_by: Mapped[str] = mapped_column(String(20), nullable=False, default="client")
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    renewal_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    billing_cycle: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
