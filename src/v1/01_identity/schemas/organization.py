import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Fiscal year start as DD-MM (e.g. "01-04" = 1 April). Set by the client admin.
FISCAL_YEAR_START_PATTERN = r"^(0[1-9]|[12][0-9]|3[01])-(0[1-9]|1[0-2])$"
DEFAULT_FISCAL_YEAR_START = "01-04"


class OrganizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # The owning client is always taken from the caller's token, never the body.
    name: str
    code: str  # unique slug, e.g. "ACME-IN"
    email: EmailStr
    base_currency: str
    fiscal_year_start: str = Field(default=DEFAULT_FISCAL_YEAR_START, pattern=FISCAL_YEAR_START_PATTERN)  # DD-MM
    timezone: str
    # When provided, a first admin user is invited into the new organization.
    admin_email: Optional[EmailStr] = None
    admin_name: Optional[str] = None


class OrganizationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    email: Optional[EmailStr] = None
    base_currency: Optional[str] = None
    fiscal_year_start: Optional[str] = Field(default=None, pattern=FISCAL_YEAR_START_PATTERN)  # DD-MM
    timezone: Optional[str] = None
    status: Optional[str] = None


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    client_id: Optional[uuid.UUID] = None
    name: str
    code: Optional[str] = None
    email: str
    base_currency: str
    fiscal_year_start: str
    timezone: str
    status: str
    created_at: Optional[str] = None
