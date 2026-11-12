import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class Proposal(Base):
    """
    What we propose to do for the customer, before the priced quotation: requirements, scope,
    timeline, terms and the services with rough prices. Each revision is a new version
    (`version_no`) chained to the one it replaces; a sent version is never changed.
    """

    __tablename__ = "proposals"
    __table_args__ = (
        UniqueConstraint("organization_id", "proposal_no", "version_no", name="uq_proposals_number_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    proposal_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUIDType, ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timeline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    terms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    # Sum of the items (quantity x price), before tax: tax is the quotation's job.
    total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    # draft | sent | under_discussion | accepted | rejected | superseded
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    # Why this version was made (what the customer asked to change).
    revision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The customer's last word on it: feedback under discussion, or why they rejected it.
    customer_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # The PDF the customer got, stored in documents when it was first sent.
    pdf_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    pdf_version_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProposalItem(Base):
    """A service from the catalog on a proposal; a quotation made from it copies these lines."""

    __tablename__ = "proposal_items"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    offering_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("offerings.id", ondelete="RESTRICT"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False, default=1)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    unit_price: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False, default=0)


class ProposalEvent(Base):
    """What happened to a proposal, in order; never changed or deleted."""

    __tablename__ = "proposal_events"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # created | edited | sent | emailed | changes_requested | revised | accepted | rejected | quoted
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUIDType, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # For an email: who sent it, to / cc / bcc, subject, message, files, the PDF and the mail server's id.
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
