import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class OrganizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # The owning client is always taken from the caller's token, never the body.
    name: str
    code: str  # unique slug, e.g. "ACME-IN"
    base_currency: str
    fiscal_year_start: str  # e.g. "04-01"
    timezone: str
    # When provided, a first admin user is invited into the new organization.
    admin_email: Optional[EmailStr] = None
    admin_name: Optional[str] = None


class OrganizationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    base_currency: Optional[str] = None
    fiscal_year_start: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[str] = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    client_id: Optional[uuid.UUID] = None
    name: str
    code: Optional[str] = None
    base_currency: str
    fiscal_year_start: str
    timezone: str
    status: str
    created_at: Optional[str] = None
