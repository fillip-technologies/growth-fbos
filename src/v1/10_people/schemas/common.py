import base64
import json
import uuid
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_serializer

T = TypeVar("T")


class Money(BaseModel):
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


class WorkerRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    worker_code: Optional[str] = None
    name: str
    work_email: Optional[str] = None
    designation: Optional[str] = None


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
