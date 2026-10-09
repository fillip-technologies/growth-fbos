import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class OrgTaxRegistration(Base):
    """
    One of the organization's own tax registrations (a GSTIN per state in India). It decides
    the supplier side of every tax calculation: the regime, the jurisdiction the supply is
    made from, the number series, and whether exports can go out under a letter of undertaking.
    Issued documents keep a snapshot of it, so editing it never changes them.
    """

    __tablename__ = "org_tax_registrations"
    __table_args__ = (
        UniqueConstraint("organization_id", "regime_code", "registration_no", name="uq_org_tax_registrations_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    regime_code: Mapped[str] = mapped_column(String(40), nullable=False)
    registration_no: Mapped[str] = mapped_column(String(50), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(512), nullable=False)
    trade_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    jurisdiction_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    registration_type: Mapped[str] = mapped_column(String(40), nullable=False, default="regular")
    address: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    lut_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lut_valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    lut_valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # The registration documents use when none is chosen.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    def lut_valid_on(self, day: date) -> bool:
        return bool(
            self.lut_number
            and self.lut_valid_from is not None
            and self.lut_valid_to is not None
            and self.lut_valid_from <= day <= self.lut_valid_to
        )

    def active_on(self, day: date) -> bool:
        return (
            self.status == "active"
            and (self.valid_from is None or self.valid_from <= day)
            and (self.valid_to is None or day <= self.valid_to)
        )
