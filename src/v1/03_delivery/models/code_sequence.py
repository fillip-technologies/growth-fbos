import uuid

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class CodeSequence(Base):
    """
    The next number of one of an organization's reference series: project codes per year
    (`WU-2026`), task codes per year (`TSK-2026`), change requests per project. A row is
    locked while its number is taken, so two requests never get the same reference.
    """

    __tablename__ = "code_sequences"
    __table_args__ = (UniqueConstraint("organization_id", "scope", name="uq_code_sequences_org_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
