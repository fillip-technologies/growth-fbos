import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from schemas.common import SubjectRef, SubjectRefInput, UserRef


class PolicyRef(BaseModel):
    code: str
    version_no: int


class StepAssigneeResponse(BaseModel):
    user: UserRef
    status: str
    delegated_from: Optional[UserRef] = None
    acted_at: Optional[datetime] = None


class ApprovalStepResponse(BaseModel):
    seq: int
    name: str
    mode: str
    quorum: str
    status: str
    assignees: list[StepAssigneeResponse]


class ApprovalRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: SubjectRef
    subject_version: Optional[str] = None
    request_type: str
    title: str
    status: str
    requested_by: UserRef
    reason: Optional[str] = None
    priority: str
    context: dict[str, Any]
    policy: PolicyRef
    steps: list[ApprovalStepResponse]
    created_at: datetime
    decided_at: Optional[datetime] = None


class ApprovalRequestCreate(BaseModel):
    id: Optional[uuid.UUID] = None
    subject: SubjectRefInput
    subject_version: Optional[str] = None
    request_type: str
    title: str
    context: dict[str, Any]
    reason: Optional[str] = None
    priority: str = "normal"


class DecisionCreate(BaseModel):
    decision: str  # approve | reject | request_revision
    comment: Optional[str] = None


class DecisionResult(BaseModel):
    request: ApprovalRequestResponse
    step_completed: bool
    request_completed: bool


class ApprovalCancel(BaseModel):
    reason: str


class DelegationCreate(BaseModel):
    to_user_id: uuid.UUID
    request_types: Optional[list[str]] = None
    valid_from: datetime
    valid_to: datetime
    reason: str


class DelegationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_user: UserRef
    to_user: UserRef
    request_types: list[str]
    valid_from: datetime
    valid_to: datetime
    reason: Optional[str] = None


class ApprovalPolicyStepInput(BaseModel):
    seq: int
    name: str
    mode: str = "sequential"
    approver_selector: dict[str, Any]
    quorum: str = "all"
    min_approvals: int = 1
    skip_condition: Optional[dict[str, Any]] = None
    allow_delegation: bool = True


class ApprovalPolicyInput(BaseModel):
    code: str
    name: str
    subject_type: str
    request_type: str
    condition: dict[str, Any]
    priority: int
    steps: list[ApprovalPolicyStepInput]
    version_no: int
    status: str  # draft | active | retired


class ApprovalPolicyStepResponse(BaseModel):
    seq: int
    name: str
    mode: str
    approver_selector: dict[str, Any]
    quorum: str
    skip_condition: Optional[dict[str, Any]] = None


class ApprovalPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    subject_type: str
    request_type: str
    condition: dict[str, Any]
    priority: int
    steps: list[ApprovalPolicyStepResponse]
    version_no: int
    status: str
