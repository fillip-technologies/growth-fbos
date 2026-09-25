import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.types import UUIDType


class ApprovalPolicy(Base):
    """
    Approval rule policy definition matching subject/request criteria to required approval flows.
    """

    __tablename__ = "approval_policies"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_approval_policies_org_code"),)

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    condition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)


class ApprovalPolicyStep(Base):
    """
    Step in an approval policy defining sequence, resolution rules, quorum, and delegation permissions.
    """

    __tablename__ = "approval_policy_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("approval_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), nullable=False, default="sequential")
    approver_selector: Mapped[dict] = mapped_column(JSON, nullable=False)
    quorum: Mapped[str] = mapped_column(String(50), nullable=False, default="all")
    min_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    skip_condition: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    allow_delegation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sla_policy_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
