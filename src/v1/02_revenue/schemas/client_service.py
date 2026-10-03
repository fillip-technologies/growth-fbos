import uuid
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import Money, PastDate

ManagedBy = Literal["us", "client", "third_party"]
BillingCycle = Literal["one_time", "monthly", "quarterly", "half_yearly", "yearly", "other"]
ServiceStatus = Literal["active", "expired", "cancelled"]


# --- Categories ----------------------------------------------------------


class ServiceCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class ServiceCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


class ServiceCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_active: bool


class CategoryRef(BaseModel):
    id: uuid.UUID
    name: str


# --- Providers -----------------------------------------------------------


class ServiceProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    category_id: Optional[uuid.UUID] = None
    contact_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    website: Optional[str] = Field(None, max_length=512)
    notes: Optional[str] = None


class ServiceProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category_id: Optional[uuid.UUID] = None
    contact_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    website: Optional[str] = Field(None, max_length=512)
    notes: Optional[str] = None


class ServiceProviderResponse(BaseModel):
    id: uuid.UUID
    name: str
    category: Optional[CategoryRef] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    notes: Optional[str] = None
    version: int


class ProviderRef(BaseModel):
    id: uuid.UUID
    name: str


# --- Client services -----------------------------------------------------


class ClientServiceCreate(BaseModel):
    provider_id: uuid.UUID
    category_id: Optional[uuid.UUID] = Field(None, description="Defaults to the provider's category")
    name: str = Field(..., min_length=1, max_length=255, description="What it is, e.g. 'acme.com' or 'Fire insurance policy'")
    reference_no: Optional[str] = Field(None, max_length=255, description="Account / policy / contract number. Never a password.")
    managed_by: ManagedBy = "client"
    start_date: Optional[PastDate] = None
    end_date: Optional[date] = None
    renewal_date: Optional[date] = None
    auto_renew: bool = False
    cost: Optional[Money] = None
    billing_cycle: Optional[BillingCycle] = None
    status: ServiceStatus = "active"
    attributes: Optional[dict] = Field(None, description="Free-form details specific to this kind of service")
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _check_dates(self) -> "ClientServiceCreate":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ClientServiceUpdate(BaseModel):
    provider_id: Optional[uuid.UUID] = None
    category_id: Optional[uuid.UUID] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    reference_no: Optional[str] = Field(None, max_length=255)
    managed_by: Optional[ManagedBy] = None
    start_date: Optional[PastDate] = None
    end_date: Optional[date] = None
    renewal_date: Optional[date] = None
    auto_renew: Optional[bool] = None
    cost: Optional[Money] = None
    billing_cycle: Optional[BillingCycle] = None
    status: Optional[ServiceStatus] = None
    attributes: Optional[dict] = None
    notes: Optional[str] = None


class ClientServiceResponse(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    provider: ProviderRef
    category: Optional[CategoryRef] = None
    name: str
    reference_no: Optional[str] = None
    managed_by: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    renewal_date: Optional[date] = None
    auto_renew: bool
    cost: Optional[Money] = None
    billing_cycle: Optional[str] = None
    status: str
    attributes: dict = Field(default_factory=dict)
    notes: Optional[str] = None
    version: int
    created_at: datetime
