import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class ClientCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    code: str  # unique slug, e.g. "ACME"
    contact_email: Optional[EmailStr] = None
    # When provided, a first client_admin user is invited into the auto-created org.
    admin_email: Optional[EmailStr] = None
    admin_name: Optional[str] = None


class ClientUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    status: Optional[str] = None


class ClientResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    code: str
    contact_email: Optional[str] = None
    status: str
    created_at: Optional[str] = None
