import base64
import json
import uuid
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

T = TypeVar("T")


class Money(BaseModel):
    """Money amount and ISO 4217 currency.

    Kept as a float internally so services can do arithmetic on ``.amount``
    without conversions, but the spec requires money to travel on the wire as
    a decimal string with 2 places (never floating-point), so the amount is
    rendered as a string on serialization.
    """

    amount: float = Field(..., description="Numeric money amount")
    currency: str = Field("INR", description="ISO 4217 3-letter currency code")

    @field_serializer("amount")
    def serialize_amount(self, amount: float) -> str:
        return f"{amount:.2f}"


class PageMeta(BaseModel):
    next_cursor: Optional[str] = Field(None, description="Opaque cursor token for next page")
    has_more: bool = Field(False, description="Whether more records exist")
    limit: int = Field(25, description="Page limit requested")


class PageResponse(BaseModel, Generic[T]):
    data: List[T]
    page: PageMeta


class UserRef(BaseModel):
    """Compact reference to a user. name is a placeholder: this service has no
    direct access to the identity service's user directory, so it is not
    resolved here (see the report for this simplification)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    avatar_url: Optional[str] = None


class UnitRef(BaseModel):
    """Compact reference to an org unit. name/unit_type are placeholders for
    the same cross-service resolution reason as UserRef."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    unit_type: Optional[str] = None


class VerticalRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class ClientRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class SubjectRef(BaseModel):
    """Reference to any business object (the universal attachment pattern)."""

    type: str
    id: uuid.UUID
    label: Optional[str] = None


class SubjectRefInput(BaseModel):
    type: str
    id: uuid.UUID


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
        # Covers binascii.Error (bad base64), json.JSONDecodeError and
        # UnicodeDecodeError -- all raised by a malformed or tampered cursor.
        return {}
