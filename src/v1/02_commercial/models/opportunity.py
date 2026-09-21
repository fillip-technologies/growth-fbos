import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    deal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("leads.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="open", index=True)
    probability: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expected_value: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    expected_close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    loss_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
