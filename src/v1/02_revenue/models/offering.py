import uuid
from typing import Optional

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Offering(Base):
    __tablename__ = "offerings"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    # vertical_id references identity service — no DB-level FK across services
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sac_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    gst_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    billing_model: Mapped[str] = mapped_column(String(50), nullable=False)
    list_price: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)
    default_work_template_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
