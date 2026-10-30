import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChangeType = Literal["promotion", "demotion", "transfer", "correction"]


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

    @model_validator(mode="after")
    def _changes_something(self) -> "RoleChangeCreate":
        if not any(
            value is not None
            for value in (self.new_designation, self.new_unit_id, self.new_manager_id, self.new_position_id, self.new_annual_ctc)
        ):
            raise ValueError("Change at least one of designation, department, manager, position or salary")
        return self


class DecisionNote(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)


class RejectionNote(BaseModel):
    note: str = Field(..., min_length=1, max_length=1000)


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
    created_at: datetime


class RoleChangeList(BaseModel):
    data: List[RoleChangeResponse]
