import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import (
    CustodianRef,
    Money,
    MoneyInput,
    SubjectRef,
    SubjectRefInput,
    TypeRef,
    UnitRef,
    VendorAccountRef,
)


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_tag: str
    name: str
    type: TypeRef
    status: str
    criticality: str
    owner_unit: Optional[UnitRef] = None
    location_branch_id: Optional[uuid.UUID] = None
    location_details: Optional[str] = None
    custody: Optional[SubjectRef] = None
    custodian: Optional[CustodianRef] = None
    vendor_account: Optional[VendorAccountRef] = None
    serial_no: Optional[str] = None
    acquired_on: Optional[date] = None
    acquisition_cost: Optional[Money] = None
    expires_at: Optional[date] = None
    renewal_due_on: Optional[date] = None
    auto_renew: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)
    version: int


class AssetCreate(BaseModel):
    name: str = Field(..., max_length=255)
    type_code: str = Field(..., max_length=100)
    owner_unit_id: uuid.UUID
    location_branch_id: Optional[uuid.UUID] = None
    location_details: Optional[str] = None
    criticality: str = "medium"
    serial_no: Optional[str] = None
    vendor_account_id: Optional[uuid.UUID] = None
    acquired_on: Optional[date] = None
    acquisition_cost: Optional[MoneyInput] = None
    expires_at: Optional[date] = None
    auto_renew: bool = False
    attributes: Optional[dict[str, Any]] = None


class AssetUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    owner_unit_id: Optional[uuid.UUID] = None
    location_branch_id: Optional[uuid.UUID] = None
    location_details: Optional[str] = None
    criticality: Optional[str] = None
    serial_no: Optional[str] = None
    vendor_account_id: Optional[uuid.UUID] = None
    expires_at: Optional[date] = None
    auto_renew: bool = False
    attributes: Optional[dict[str, Any]] = None


class AssetAssignmentCreate(BaseModel):
    assignee_type: str = Field(..., description="'identity.user', 'identity.org_unit', 'delivery.work_unit', etc.")
    assignee_id: uuid.UUID
    custodian_user_id: Optional[uuid.UUID] = None
    condition_out: Optional[str] = "Good"
    note: Optional[str] = None


class AssetTransferCreate(BaseModel):
    to_assignee_type: str
    to_assignee_id: uuid.UUID
    to_custodian_user_id: Optional[uuid.UUID] = None
    condition_transfer: Optional[str] = "Good"
    note: Optional[str] = None


class AssetReturn(BaseModel):
    condition_in: str = "Good"
    note: Optional[str] = None


class AssetAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    assignee: SubjectRef
    custodian_user_id: Optional[uuid.UUID] = None
    assigned_at: datetime
    returned_at: Optional[datetime] = None
    condition_out: Optional[str] = None
    condition_in: Optional[str] = None
    assigned_by: Optional[uuid.UUID] = None


class CredentialReveal(BaseModel):
    reason: str


class CredentialSecretResponse(BaseModel):
    value: str
    expires_in: int = 60
    revealed_at: datetime
