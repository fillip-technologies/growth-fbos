import base64
import json
import uuid
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


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
    name: str


class SubjectRef(BaseModel):
    type: str
    id: uuid.UUID
    label: Optional[str] = None


class SubjectRefInput(BaseModel):
    type: str
    id: uuid.UUID


def encode_cursor(payload: dict[str, Any]) -> str:
    json_bytes = json.dumps(payload, default=str).encode("utf-8")
    return base64.urlsafe_b64encode(json_bytes).decode("ascii")


def decode_cursor(cursor_str: str) -> dict[str, Any]:
    try:
        decoded_bytes = base64.urlsafe_b64decode(cursor_str.encode("ascii"))
        return json.loads(decoded_bytes.decode("utf-8"))
    except ValueError:
        return {}
