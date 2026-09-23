from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


class UserRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    avatar_url: Optional[str] = None


class SubjectRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    id: uuid.UUID
    label: Optional[str] = None


class SubjectRefInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    id: uuid.UUID


class CategoryRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    name: str


class PageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int = 25
