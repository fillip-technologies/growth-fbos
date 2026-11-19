import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    # vertical_id references identity service — no DB-level FK across services
    vertical_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    # Set once the lead converts into a client
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # "Sales outreach by": who handles the lead. None while it waits to be claimed. Changes only
    # by claim and transfer, each written to `lead_events`.
    owner_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new", index=True)
    loss_reason: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    scope_path: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, index=True)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # The follow-up date of the latest call that set one.
    next_follow_up_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    # When the customer accepted a quotation, and who handled the lead then.
    converted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    converted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class LeadEvent(Base):
    """
    What happened to a lead, in order: who added it, claimed it, passed it on, called, qualified,
    disqualified or reopened it, and when. Rows are only ever added.
    """

    __tablename__ = "lead_events"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # created | claimed | transferred | released | contacted | qualified | disqualified
    # | reopened | converted
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    # Who did it; None when the system did (a website enquiry imported).
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # The outreach person before and after (claim, transfer, release, created).
    from_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    to_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    # The status before and after, when it changed.
    from_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # The reason given (a transfer, a disqualification).
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
