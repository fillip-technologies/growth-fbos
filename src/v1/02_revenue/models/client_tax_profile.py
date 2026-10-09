import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class ClientTaxProfile(Base):
    """
    How tax applies to a customer. Every field is optional: without a profile (or a field) the
    customer's GSTIN, PAN and billing address decide (`services/tax_service.py`).
    """

    __tablename__ = "client_tax_profiles"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    # One of the regime's party_registration_types (registered, unregistered, sez_unit, overseas…).
    registration_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    registration_no: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    place_of_supply: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    # The customer withholds TDS under this section (a code or an old section number) when set.
    tds_section_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # [{certificate_no, percent, valid_from, valid_to}]: our lower/nil deduction certificates that
    # name this customer as the deductor.
    lower_deduction_certificates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
