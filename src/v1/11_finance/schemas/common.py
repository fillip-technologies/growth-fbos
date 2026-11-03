import base64
import binascii
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field, PlainSerializer

T = TypeVar("T")

# Money travels as a decimal string with two places ("1250.00"), like every other service.
MoneyOut = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]
# Input accepts a number or a numeric string; at most two decimal places.
MoneyIn = Annotated[Decimal, Field(max_digits=14, decimal_places=2)]
Currency = Annotated[str, Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")]


class PageMeta(BaseModel):
    next_cursor: Optional[str] = Field(None, description="Opaque cursor token for next page")
    has_more: bool = Field(False, description="Whether more records exist")
    limit: int = Field(25, description="Page limit requested")


class PageResponse(BaseModel, Generic[T]):
    data: List[T]
    page: PageMeta


class Period(BaseModel):
    from_date: date
    to_date: date


def encode_cursor(payload: dict[str, Any]) -> str:
    json_bytes = json.dumps(payload, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("ascii")


def decode_cursor(cursor_str: str) -> dict[str, Any]:
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor_str.encode("ascii")).decode("utf-8"))
    except (ValueError, binascii.Error):
        return {}
    return decoded if isinstance(decoded, dict) else {}
