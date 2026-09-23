import base64
import json
from datetime import datetime, timezone
from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field, field_serializer

T = TypeVar("T")


class Address(BaseModel):
    line1: str = Field(..., description="Street address line 1")
    line2: Optional[str] = Field(None, description="Street address line 2")
    city: str = Field(..., description="City / District")
    state: str = Field(..., description="State name")
    state_code: str = Field(..., description="2-digit GST state code e.g. 10, 27")
    postal_code: str = Field(..., description="PIN / Postal code")
    country: str = Field("IN", description="ISO 3166-1 alpha-2 country code")


class Money(BaseModel):
    """Money amount and ISO 4217 currency.

    Internally kept as a float so services can do arithmetic on ``.amount``
    without conversions, but the spec requires money to travel on the wire as
    a decimal string with 2 places (never floating-point), so the amount is
    rendered as a string on serialization.
    """

    amount: float = Field(..., description="Numeric money amount")
    currency: str = Field("INR", description="ISO 4217 3-letter currency code")

    @field_serializer("amount")
    def serialize_amount(self, amount: float) -> str:
        return f"{amount:.2f}"


class Consent(BaseModel):
    """Consent evidence captured with personal data (DPDP Act, 2023)."""

    given: bool = Field(..., description="Whether consent was given")
    text: str = Field(..., description="The consent text shown to the person")
    captured_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="When consent was captured"
    )
    channel: str = Field(..., description="Channel consent was captured on e.g. website_form")


class PageMeta(BaseModel):
    next_cursor: Optional[str] = Field(None, description="Opaque cursor token for next page")
    has_more: bool = Field(False, description="Whether more records exist")
    limit: int = Field(25, description="Page limit requested")


class PageResponse(BaseModel, Generic[T]):
    data: List[T]
    page: PageMeta


def encode_cursor(payload: dict[str, Any]) -> str:
    """Encode dictionary into URL-safe opaque cursor string."""
    json_bytes = json.dumps(payload, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("ascii")


def decode_cursor(cursor_str: str) -> dict[str, Any]:
    """Decode opaque URL-safe cursor string into dictionary."""
    try:
        decoded_bytes = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
        return json.loads(decoded_bytes.decode("utf-8"))
    except ValueError:
        # Covers binascii.Error (bad base64), json.JSONDecodeError and
        # UnicodeDecodeError — all ValueError subclasses raised by a
        # malformed or tampered opaque cursor.
        return {}
