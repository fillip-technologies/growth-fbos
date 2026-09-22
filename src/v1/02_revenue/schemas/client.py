import uuid
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Address


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    designation: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    is_primary: bool = False


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    designation: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_primary: bool = False


class ClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Client display / trade name")
    legal_name: str = Field(..., min_length=1, max_length=512, description="Registered business legal name")
    client_type: Literal["company", "individual", "government"] = "company"
    gstin: Optional[str] = Field(None, description="15-character GST identification number")
    pan: Optional[str] = Field(None, description="10-character Permanent Account Number")
    billing_address: Address
    owner_user_id: uuid.UUID
    source: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    legal_name: Optional[str] = Field(None, min_length=1, max_length=512)
    gstin: Optional[str] = None
    billing_address: Optional[Address] = None
    owner_user_id: Optional[uuid.UUID] = None
    status: Optional[Literal["prospect", "active", "inactive"]] = None


class ClientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    legal_name: Optional[str] = None
    client_type: str
    pan: Optional[str] = None
    gstin: Optional[str] = None
    status: str
    billing_address: Optional[Address] = None
    owner_user_id: uuid.UUID
    version: int
    contacts: List[ContactResponse] = []
