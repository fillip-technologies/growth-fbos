import uuid
from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Renewal(Base):
    __tablename__ = "renewals"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    new_opportunity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True
    )
    date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    outcome_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
