import uuid
from typing import Optional

from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    # vertical_id references identity service — no DB-level FK across services
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new", index=True)
    loss_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
