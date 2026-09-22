import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class AccountingExport(Base):
    """
    Tracks when a billing entity (invoice, payment) was pushed to an external
    accounting system (Tally, Zoho Books, QuickBooks, etc.).
    entity_id is a polymorphic reference — no DB FK.
    """

    __tablename__ = "accounting_exports"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)    # invoice / payment / refund
    entity_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    target_system: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)
    exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
