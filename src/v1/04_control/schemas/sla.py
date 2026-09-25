import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from schemas.common import SubjectRef, UserRef


class SlaPolicySummary(BaseModel):
    code: str
    name: str
    version_no: int


class SlaPolicyInput(BaseModel):
    code: str
    name: str
    subject_type: str
    metric: str  # response | resolution | stage_duration | approval_turnaround
    condition: dict[str, Any]
    priority: int
    target_minutes: int
    calendar_mode: str  # business_hours | calendar_24x7
    start_on: str
    stop_on: list[str]
    pause_on: Optional[dict[str, Any]] = None
    thresholds: list[dict[str, Any]]
    escalation_levels: list[dict[str, Any]]
    version_no: int
    status: str  # draft | active | retired


class SlaPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    subject_type: str
    metric: str
    condition: dict[str, Any]
    priority: int
    target_minutes: int
    calendar_mode: str
    start_on: str
    stop_on: list[str]
    pause_on: Optional[dict[str, Any]] = None
    thresholds: list[dict[str, Any]]
    escalation_levels: list[dict[str, Any]]
    version_no: int
    status: str


class SlaInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    policy: SlaPolicySummary
    subject: SubjectRef
    metric: str
    state: str
    started_at: datetime
    due_at: datetime
    target_minutes: int
    paused_minutes: int
    consumed_pct: float
    elapsed_business_minutes: int
    current_escalation_level: int
    breached_at: Optional[datetime] = None
    met_at: Optional[datetime] = None
    pauses: list[dict[str, Any]]


class SlaExceptionCreate(BaseModel):
    reason_code: str  # client_delay | dependency | scope_change | force_majeure | other
    description: str
    effect: str  # pause | extend | excuse_breach
    extend_minutes: Optional[int] = None
    evidence_document_id: Optional[uuid.UUID] = None


class SlaExceptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instance_id: uuid.UUID
    reason_code: str
    effect: str
    extend_minutes: Optional[int] = None
    status: str
    approval_request_id: Optional[uuid.UUID] = None


class EscalationAck(BaseModel):
    note: Optional[str] = None


class EscalationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instance_id: uuid.UUID
    subject: SubjectRef
    level: int
    status: str
    target: Optional[UserRef] = None
    triggered_at: datetime
    acknowledged_at: Optional[datetime] = None
