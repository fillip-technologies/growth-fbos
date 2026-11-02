import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChangeType = Literal["promotion", "demotion", "transfer", "correction", "add_post", "end_post", "make_primary"]
PostKind = Literal["concurrent", "additional_charge", "acting"]


class RoleChangeCreate(BaseModel):
    change_type: ChangeType
    effective_date: date  # past dates apply as soon as the change is approved
    reason: str = Field(..., min_length=1, max_length=2000)
    new_designation: Optional[str] = Field(None, min_length=1, max_length=255)
    new_unit_id: Optional[uuid.UUID] = None
    new_manager_id: Optional[uuid.UUID] = None
    new_position_id: Optional[uuid.UUID] = None
    new_annual_ctc: Optional[Decimal] = Field(None, gt=0)
    letter_doc_id: Optional[uuid.UUID] = None

    # Which post: empty means the primary post. Required to end a post or make one primary.
    post_ref: Optional[uuid.UUID] = None
    # Adding a post: its kind, share of time (percent), allowance and planned end.
    post_type: Optional[PostKind] = None
    new_time_share: Optional[Decimal] = Field(None, gt=0, le=100)
    new_monthly_allowance: Optional[Decimal] = Field(None, gt=0)
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def _says_what_it_does(self) -> "RoleChangeCreate":
        if self.change_type == "add_post":
            if not self.post_type or not self.new_designation:
                raise ValueError("A new post needs its kind (post_type) and a title (new_designation)")
            if self.post_ref is not None:
                raise ValueError("A new post has no post_ref")
            if self.end_date is not None and self.end_date <= self.effective_date:
                raise ValueError("The planned end must be after the start")
            return self
        if self.change_type in ("end_post", "make_primary"):
            if self.post_ref is None:
                raise ValueError(f"Say which post to {self.change_type.replace('_', ' ')} (post_ref)")
            return self
        if not any(
            value is not None
            for value in (
                self.new_designation, self.new_unit_id, self.new_manager_id, self.new_position_id,
                self.new_annual_ctc, self.new_time_share, self.new_monthly_allowance,
            )
        ):
            raise ValueError("Change at least one of designation, department, manager, position, salary, share of time or allowance")
        return self


class DecisionNote(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)


class RejectionNote(BaseModel):
    note: str = Field(..., min_length=1, max_length=1000)


class RoleChangeStepResponse(BaseModel):
    seq: int
    name: str
    kind: str
    unit_id: Optional[uuid.UUID] = None
    status: str  # waiting, active, approved, rejected, skipped
    approver_user_ids: List[uuid.UUID] = []
    open_to_pool: bool = False  # anyone who may approve role changes can decide it
    escalated_at: Optional[datetime] = None
    decided_by: Optional[uuid.UUID] = None
    acted_for: Optional[uuid.UUID] = None  # the approver who had delegated to the decider
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None


class AccessRoleRef(BaseModel):
    role_code: str
    scope_unit_id: Optional[uuid.UUID] = None  # empty: company-wide


class AccessImpact(BaseModel):
    """The access roles the person's posts bring, before and after a change."""

    has_login: bool  # without a login there is no access to change
    added: List[AccessRoleRef] = []
    removed: List[AccessRoleRef] = []
    notes: List[str] = []  # what could not be mapped (a department-scoped role for a post with no department)


class RoleChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    worker_id: uuid.UUID
    worker_name: str
    change_type: str
    status: str
    effective_date: date
    reason: str
    letter_doc_id: Optional[uuid.UUID] = None

    new_designation: Optional[str] = None
    new_unit_id: Optional[uuid.UUID] = None
    new_manager_id: Optional[uuid.UUID] = None
    new_position_id: Optional[uuid.UUID] = None
    previous_designation: Optional[str] = None
    previous_unit_id: Optional[uuid.UUID] = None
    previous_manager_id: Optional[uuid.UUID] = None
    previous_position_id: Optional[uuid.UUID] = None
    new_manager_name: Optional[str] = None
    previous_manager_name: Optional[str] = None
    new_position_label: Optional[str] = None
    previous_position_label: Optional[str] = None

    post_ref: Optional[uuid.UUID] = None
    post_title: Optional[str] = None
    post_type: Optional[str] = None
    new_time_share: Optional[Decimal] = None
    end_date: Optional[date] = None
    has_allowance_change: bool = False
    new_monthly_allowance: Optional[Decimal] = None

    # Pay is only shown to those who may see it; everyone else just learns that pay changes.
    has_salary_change: bool = False
    new_annual_ctc: Optional[Decimal] = None
    previous_annual_ctc: Optional[Decimal] = None

    requested_by: uuid.UUID
    decided_by: Optional[uuid.UUID] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None
    applied_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    steps: List[RoleChangeStepResponse] = []
    awaiting_step: Optional[str] = None  # the name of the approval waiting for a decision
    access_impact: Optional[AccessImpact] = None  # for a change still waiting for approval
    created_at: datetime


class RoleChangeList(BaseModel):
    data: List[RoleChangeResponse]


class StandingApproversUpdate(BaseModel):
    user_ids: List[uuid.UUID] = Field(default_factory=list, max_length=50)


class StandingApprovers(BaseModel):
    role_key: str
    user_ids: List[uuid.UUID]


class StandingApproversList(BaseModel):
    data: List[StandingApprovers]


class DelegationCreate(BaseModel):
    to_user_id: uuid.UUID
    valid_from: date
    valid_to: date
    reason: Optional[str] = Field(None, max_length=255)


class DelegationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    valid_from: date
    valid_to: date
    reason: Optional[str] = None


class DelegationList(BaseModel):
    data: List[DelegationResponse]


class RoleChangePreview(BaseModel):
    steps: List[RoleChangeStepResponse]
    access_impact: AccessImpact
