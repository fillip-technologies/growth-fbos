import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class ProcessedEvent(Base):
    """
    Idempotent event processing receipt ensuring at-most-once consumption per consumer group.
    """

    __tablename__ = "processed_events"

    consumer: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IdempotencyKey(Base):
    """
    HTTP API idempotency ledger storing client requests and pre-calculated responses.
    """

    __tablename__ = "idempotency_keys"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class CodeSequence(Base):
    """
    High-performance business code / numbering sequence counter generator.
    """

    __tablename__ = "code_sequences"

    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    sequence_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    period_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    prefix: Mapped[str] = mapped_column(String(50), nullable=False)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class Outbox(Base):
    """
    Transactional outbox event log for reliable asynchronous domain event publishing.
    """

    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    headers: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
