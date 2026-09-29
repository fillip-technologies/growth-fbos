import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class OrganizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Required when the caller is a platform admin; ignored for client admins,
    # whose client_id is taken from their token.
    client_id: Optional[uuid.UUID] = None
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
