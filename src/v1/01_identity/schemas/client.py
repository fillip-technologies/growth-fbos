import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClientCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    code: str  # unique slug, e.g. "ACME"
    contact_email: Optional[EmailStr] = None
    # When provided, a first client_admin user is invited into the auto-created org.
    admin_email: Optional[EmailStr] = None
    admin_name: Optional[str] = None
    # Settings for the client's auto-created first organization. Defaults match the
    # platform's home region; the client admin can change them later via PATCH.
    base_currency: str = "INR"
    fiscal_year_start: str = "04-01"
    timezone: str = "Asia/Kolkata"
    # Quotas controlled exclusively by platform_admin
    max_organizations: Optional[int] = Field(default=2, ge=1, le=1000)
    max_users_per_org: Optional[int] = Field(default=50, ge=1, le=10000)


class ClientUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    status: Optional[str] = None
    max_organizations: Optional[int] = Field(default=None, ge=1, le=1000)
    max_users_per_org: Optional[int] = Field(default=None, ge=1, le=10000)


class ClientResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    code: str
    contact_email: Optional[str] = None
    status: str
    max_organizations: int = 2
    max_users_per_org: int = 50
    active_organizations_count: Optional[int] = None
    created_at: Optional[str] = None

