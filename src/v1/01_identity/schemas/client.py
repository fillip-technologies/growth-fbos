import uuid
from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class ClientCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    code: str  # unique slug, e.g. "ACME"
    # Required; also becomes the email of the client's auto-created first organization.
    contact_email: EmailStr
    # When provided, a first client_admin user is invited into the auto-created org.
    admin_email: Optional[EmailStr] = None
    admin_name: Optional[str] = None
    # Settings for the client's auto-created first organization. Defaults match the
    # platform's home region; the client admin can change them later via PATCH. The
    # fiscal year is owned by the client admin, so it is not set here (default "01-04").
    base_currency: str = "INR"
    timezone: str = "Asia/Kolkata"
    # Service window (inclusive) during which the client may use the platform.
    # Defaults to today .. one year later when subscription_end is omitted; an explicit
    # null means no expiry (see client_service.create_client).
    subscription_start: Optional[date] = None
    subscription_end: Optional[date] = None
    # Quotas controlled exclusively by platform_admin. Omitted -> the default below;
    # an explicit null means unlimited.
    max_organizations: Optional[int] = Field(default=2, ge=1, le=1000)
    max_users_per_org: Optional[int] = Field(default=50, ge=1, le=10000)

    @model_validator(mode="after")
    def _check_window(self) -> "ClientCreateRequest":
        if self.subscription_start and self.subscription_end and self.subscription_end < self.subscription_start:
            raise ValueError("subscription_end must be on or after subscription_start")
        return self


class ClientUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    status: Optional[str] = None
    # For the quotas and subscription_end, an explicit null means unlimited / no expiry;
    # an omitted field is left unchanged (see client_service.update_client).
    max_organizations: Optional[int] = Field(default=None, ge=1, le=1000)
    max_users_per_org: Optional[int] = Field(default=None, ge=1, le=10000)
    subscription_start: Optional[date] = None
    subscription_end: Optional[date] = None


class ClientResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    code: str
    contact_email: str
    status: str
    # None = unlimited
    max_organizations: Optional[int] = None
    max_users_per_org: Optional[int] = None
    subscription_start: Optional[date] = None
    # None = no expiry
    subscription_end: Optional[date] = None
    # "upcoming" | "active" | "expiring" (<= 30 days left) | "expired" | "unlimited" (no end date)
    subscription_state: Optional[str] = None
    active_organizations_count: Optional[int] = None
    created_at: Optional[str] = None

