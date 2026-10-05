from typing import Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

Classification = Literal["public", "internal", "confidential", "restricted"]


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_\-]*$")
    name: str = Field(..., min_length=1, max_length=255)
    default_classification: Classification = "internal"
    # Empty means any file type is accepted.
    allowed_mime_types: list[str] = Field(default_factory=list)
    # Null means the service-wide limit (100 MB).
    max_file_size_bytes: Optional[int] = Field(None, gt=0)


class CategoryUpdate(BaseModel):
    """Fields left out are unchanged; `max_file_size_bytes` may be set to null to clear it."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    default_classification: Optional[Classification] = None
    allowed_mime_types: Optional[list[str]] = None
    max_file_size_bytes: Optional[int] = Field(None, gt=0)


class CategoryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    code: str
    name: str
    default_classification: str
    allowed_mime_types: list[str] = Field(default_factory=list)
    max_file_size_bytes: Optional[int] = None


class CategoryListResponse(BaseModel):
    data: list[CategoryResponse] = Field(default_factory=list)
