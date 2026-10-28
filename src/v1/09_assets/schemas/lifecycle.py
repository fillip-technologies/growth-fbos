import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money, MoneyInput


# --- Maintenance -------------------------------------------------------------


class MaintenanceRecordCreate(BaseModel):
    maintenance_type: str = Field(..., max_length=50)  # preventive, repair, calibration, inspection, upgrade
    vendor_id: Optional[uuid.UUID] = None
    scheduled_on: date
    completed_on: Optional[date] = None
    cost: Optional[MoneyInput] = None
    task_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class MaintenanceRecordUpdate(BaseModel):
    completed_on: Optional[date] = None
    cost: Optional[MoneyInput] = None
    notes: Optional[str] = None


class MaintenanceRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    maintenance_type: str
    vendor_id: Optional[uuid.UUID] = None
    scheduled_on: date
    completed_on: Optional[date] = None
    cost: Optional[Money] = None
    task_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


# --- Renewals ----------------------------------------------------------------


class AssetRenewalCreate(BaseModel):
    due_on: date
    approval_request_id: Optional[uuid.UUID] = None
    notes: Optional[str] = None


class AssetRenewalDecision(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
    new_expires_at: Optional[date] = None


class AssetRenewalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    due_on: date
    status: str
    approval_request_id: Optional[uuid.UUID] = None
    decided_by: Optional[uuid.UUID] = None
    new_expires_at: Optional[date] = None


# --- Disposals ---------------------------------------------------------------


class AssetDisposalCreate(BaseModel):
    method: str = Field(..., max_length=50)  # scrapped, sold, recycled, donated, returned_to_lessor
    disposed_on: date
    value_realised: Optional[MoneyInput] = None
    data_wiped: bool = False
    certificate_document_id: Optional[uuid.UUID] = None


class AssetDisposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    method: str
    disposed_on: date
    value_realised: Optional[Money] = None
    data_wiped: bool
    certificate_document_id: Optional[uuid.UUID] = None


# --- Costs & TCO -------------------------------------------------------------


class AssetCostCreate(BaseModel):
    cost_type: str = Field(..., max_length=50)  # acquisition, lease, maintenance, license, repair
    amount: float | str
    currency: str = "INR"
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    vendor_invoice_ref: Optional[str] = Field(None, max_length=100)


class AssetCostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    cost_type: str
    amount: Money
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    vendor_invoice_ref: Optional[str] = None


class AssetCostSummary(BaseModel):
    total_cost: Money
    costs_by_type: dict[str, float]


# --- Relationships -----------------------------------------------------------


class AssetRelationshipCreate(BaseModel):
    relation_type: str = Field(..., max_length=50)  # parent_of, depends_on, installed_on, backup_for
    related_asset_id: uuid.UUID


class AssetRelationshipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    relation_type: str
    related_asset_id: uuid.UUID
