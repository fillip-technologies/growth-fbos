import base64
import json
import uuid
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

T = TypeVar("T")


class Money(BaseModel):
    """Money amount and ISO 4217 currency.

    Kept as a float internally so services can do arithmetic on ``.amount``
    without conversions, but travels on the wire as a decimal string with
    2 places.
    """

    amount: float = Field(..., description="Numeric money amount")
    currency: str = Field("INR", description="ISO 4217 3-letter currency code")

    @field_serializer("amount")
    def serialize_amount(self, amount: float) -> str:
        return f"{amount:.2f}"


class MoneyInput(BaseModel):
    amount: float | str
    currency: str = "INR"

    def as_float(self) -> float:
        return float(self.amount)


class MoneyResponse(BaseModel):
    amount: str
    currency: str


class PageMeta(BaseModel):
    next_cursor: Optional[str] = Field(None, description="Opaque cursor token for next page")
    has_more: bool = Field(False, description="Whether more records exist")
    limit: int = Field(25, description="Page limit requested")


class PageResponse(BaseModel, Generic[T]):
    data: List[T]
    page: PageMeta


class SubjectRef(BaseModel):
    """Reference to any business object (the universal attachment pattern)."""

    type: str  # e.g., "identity.user", "identity.org_unit", "delivery.work_unit"
    id: uuid.UUID
    label: Optional[str] = None


class SubjectRefInput(BaseModel):
    type: str
    id: uuid.UUID


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: Optional[str] = None
    email: Optional[str] = None


class UnitRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: Optional[str] = None
    unit_type: Optional[str] = None


class CustodianRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: Optional[str] = None


class TypeRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    family: str


class VendorRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


class VendorAccountRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vendor: str
    account: str


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode a dictionary into an opaque, URL-safe cursor string."""
    json_bytes = json.dumps(payload, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("ascii")


def decode_cursor(cursor_str: str) -> dict[str, Any]:
    """Decode an opaque, URL-safe cursor string back into a dictionary."""
    try:
        decoded_bytes = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
        return json.loads(decoded_bytes.decode("utf-8"))
    except ValueError:
        return {}
