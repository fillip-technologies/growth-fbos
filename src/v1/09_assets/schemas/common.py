import base64
import json
import uuid
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PageMeta(BaseModel):
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int = 25


class PageResponse(BaseModel, Generic[T]):
    data: List[T]
    page: PageMeta


class MoneyInput(BaseModel):
    amount: str
    currency: str = "INR"


class MoneyResponse(BaseModel):
    amount: str
    currency: str


class TypeRef(BaseModel):
    code: str
    name: str
    family: str


class UnitRef(BaseModel):
    id: uuid.UUID
    name: str
    unit_type: Optional[str] = None


class CustodianRef(BaseModel):
    id: uuid.UUID
    name: str


class VendorAccountRef(BaseModel):
    id: uuid.UUID
    vendor: str
    account: str


def encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except ValueError:
        return {}
