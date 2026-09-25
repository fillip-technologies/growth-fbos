import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditActorRef(BaseModel):
    type: str
    id: Optional[uuid.UUID] = None
    name: str


class AuditSubjectRef(BaseModel):
    type: str
    id: Optional[uuid.UUID] = None
    label: Optional[str] = None


class AuditChangeItem(BaseModel):
    field: str
    old: Optional[Any] = None
    new: Optional[Any] = None


class AuditContextData(BaseModel):
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    category: str
    source_service: str
    event_type: str
    action: str
    actor: AuditActorRef
    subject: AuditSubjectRef
    changes: list[AuditChangeItem]
    context: Optional[AuditContextData] = None
    severity: str


class AuditExportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: datetime = Field(alias="from")
    to: datetime
    category: Optional[str] = None
    subject_type: Optional[str] = None
    format: str


class AuditVerifyResult(BaseModel):
    date: date
    event_count: int
    expected_merkle_root: Optional[str]
    computed_merkle_root: str
    valid: bool
    archive_object_key: Optional[str] = None


class JobResponse(BaseModel):
    id: uuid.UUID
    status: str
    status_url: Optional[str] = None
    created_at: datetime
