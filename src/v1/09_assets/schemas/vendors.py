import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VendorCreate(BaseModel):
    code: Optional[str] = Field(None, max_length=100)
    name: str = Field(..., max_length=255)
    vendor_type: str = Field("supplier", max_length=50)  # oem, saas, telecom, maintenance, contractor
    gstin: Optional[str] = Field(None, max_length=50)


class VendorUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    vendor_type: Optional[str] = Field(None, max_length=50)
    gstin: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = Field(None, max_length=50)


class VendorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    code: str
    name: str
    vendor_type: str
    gstin: Optional[str] = None
    status: str


class VendorAccountCreate(BaseModel):
    vendor_id: uuid.UUID
    account_identifier: str = Field(..., max_length=255)
    owner_user_id: Optional[uuid.UUID] = None
    billing_email: Optional[str] = Field(None, max_length=255)


class VendorAccountUpdate(BaseModel):
    account_identifier: Optional[str] = Field(None, max_length=255)
    owner_user_id: Optional[uuid.UUID] = None
    billing_email: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(None, max_length=50)


class VendorAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor_id: uuid.UUID
    account_identifier: str
    owner_user_id: Optional[uuid.UUID] = None
    billing_email: Optional[str] = None
    status: str
