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


class SubjectRefInput(BaseModel):
    type: str
    id: uuid.UUID


class SubjectRef(BaseModel):
    type: str
    id: uuid.UUID
    label: Optional[str] = None


class UserRef(BaseModel):
    id: uuid.UUID
    name: str
    avatar_url: Optional[str] = None


class UnitRef(BaseModel):
    id: uuid.UUID
    name: str
    unit_type: Optional[str] = None


def encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except ValueError:
        return {}
