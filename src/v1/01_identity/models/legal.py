import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class LegalEntity(Base):
    __tablename__ = "legal_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # mg_unit_id points to the org unit that represents this legal entity's main geo
    mg_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True
    )
    legal_name: Mapped[str] = mapped_column(String(512), nullable=False)
    pan: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)


class TaxRegistration(Base):
    __tablename__ = "tax_registrations"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("legal_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_unit_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("org_units.id", ondelete="SET NULL"), nullable=True
    )
    pin: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    regime_code: Mapped[str] = mapped_column(String(50), nullable=False)
    registered_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
