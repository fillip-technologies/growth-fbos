import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from schemas.common import CustodianRef, MoneyInput, MoneyResponse, TypeRef, UnitRef, VendorAccountRef


class AssetResponse(BaseModel):
    id: uuid.UUID
    asset_tag: str
    name: str
    type: TypeRef
    status: str
    criticality: str
    owner_unit: Optional[UnitRef] = None
    custodian: Optional[CustodianRef] = None
    vendor_account: Optional[VendorAccountRef] = None
    expires_at: Optional[date] = None
    renewal_due_on: Optional[date] = None
    auto_renew: bool = False
    attributes: dict[str, Any] = {}
    version: int


class AssetCreate(BaseModel):
    name: str
    type_code: str
    owner_unit_id: uuid.UUID
    criticality: str = "medium"
    vendor_account_id: Optional[uuid.UUID] = None
    expires_at: Optional[date] = None
    auto_renew: bool = False
    acquisition_cost: Optional[MoneyInput] = None
    attributes: Optional[dict[str, Any]] = None


class AssetAssignmentCreate(BaseModel):
    assignee_type: str  # user | team | work_unit
    assignee_id: uuid.UUID
    condition_out: Optional[str] = None
    note: Optional[str] = None


class AssetReturn(BaseModel):
    condition_in: str
    note: Optional[str] = None


class CredentialReveal(BaseModel):
    reason: str


class CredentialSecretResponse(BaseModel):
    value: str
    expires_in: int = 60
    revealed_at: datetime
