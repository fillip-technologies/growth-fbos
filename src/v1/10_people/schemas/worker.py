import uuid
from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from schemas.common import PageMeta


class WorkerBase(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    work_email: EmailStr
    personal_email: Optional[EmailStr] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    residential_address: Optional[str] = None

    # Emergency Contact
    emergency_contact_name: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    # Organization Placement
    unit_id: Optional[uuid.UUID] = None  # Department / Branch
    designation: str = Field(..., min_length=1, max_length=255)
    job_title: Optional[str] = None
    manager_id: Optional[uuid.UUID] = None
    employment_type: str = "full_time"  # full_time, part_time, contractor, intern
    status: str = "active"  # active, probation, on_leave, noticed, exited

    # Milestone Dates (Allows full past/historical backdating for existing employees)
    date_of_joining: date = Field(..., description="Date joined company (can be back-dated)")
    probation_end_date: Optional[date] = None
    confirmation_date: Optional[date] = None
    resignation_date: Optional[date] = None
    last_working_date: Optional[date] = None


    # Banking & Tax Details
    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    ifsc_code: Optional[str] = None
    tax_id: Optional[str] = None


class WorkerCreate(WorkerBase):
    user_id: Optional[uuid.UUID] = None  # Link to existing user in 01_identity if already created
    custom_worker_code: Optional[str] = None  # Optional existing employee ID (e.g. EMP-101)


class WorkerUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    work_email: Optional[EmailStr] = None
    personal_email: Optional[EmailStr] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    residential_address: Optional[str] = None

    emergency_contact_name: Optional[str] = None
    emergency_contact_relation: Optional[str] = None
    emergency_contact_phone: Optional[str] = None

    worker_code: Optional[str] = Field(None, max_length=50, description="Employee code; blank clears it")
    unit_id: Optional[uuid.UUID] = None
    designation: Optional[str] = None
    job_title: Optional[str] = None
    manager_id: Optional[uuid.UUID] = None
    employment_type: Optional[str] = None
    status: Optional[str] = None

    date_of_joining: Optional[date] = None
    probation_end_date: Optional[date] = None
    confirmation_date: Optional[date] = None
    resignation_date: Optional[date] = None
    last_working_date: Optional[date] = None

    bank_name: Optional[str] = None
    bank_account_no: Optional[str] = None
    ifsc_code: Optional[str] = None
    tax_id: Optional[str] = None


class TimelineEventCreate(BaseModel):
    event_category: str = Field(..., description="hire, promotion, transfer, salary_revision, confirmation, exit")
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    effective_date: date = Field(..., description="Can be historical past date or future date")
    previous_state: Optional[dict[str, Any]] = None
    new_state: Optional[dict[str, Any]] = None


class TimelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_category: str
    title: str
    description: Optional[str] = None
    effective_date: date
    previous_state: Optional[dict[str, Any]] = None
    new_state: Optional[dict[str, Any]] = None
    recorded_at: datetime


class WorkerResponse(WorkerBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    worker_code: Optional[str] = None
    user_id: Optional[uuid.UUID] = None
    name: str = ""
    created_at: datetime
    updated_at: datetime


class ManagerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    worker_code: Optional[str] = None
    name: str
    designation: Optional[str] = None


class WorkerDetailResponse(WorkerResponse):
    manager: Optional[ManagerRef] = None
    direct_reports_count: int = 0
    timeline: List[TimelineEventResponse] = []


class ImportableUser(BaseModel):
    """An active employee user of identity who has no worker record yet."""

    user_id: uuid.UUID
    name: str
    email: str
    phone: Optional[str] = None
    employee_code: Optional[str] = None
    unit_id: Optional[uuid.UUID] = None
    manager_user_id: Optional[uuid.UUID] = None


class ImportableUsersResponse(BaseModel):
    data: List[ImportableUser]
    page: PageMeta


class WorkerImportItem(BaseModel):
    user_id: uuid.UUID
    # Identity does not hold these, so HR supplies them.
    designation: str = Field(..., min_length=1, max_length=255)
    date_of_joining: date
    employment_type: str = "full_time"
    # Left empty it falls back to the user's employee code in identity, and to none if that is empty or taken.
    worker_code: Optional[str] = Field(None, max_length=50)


class WorkerImportRequest(BaseModel):
    users: List[WorkerImportItem] = Field(..., min_length=1, max_length=100)


class WorkerImportSkipped(BaseModel):
    user_id: uuid.UUID
    reason: str


class WorkerImportResult(BaseModel):
    created: List[WorkerResponse]
    skipped: List[WorkerImportSkipped]
