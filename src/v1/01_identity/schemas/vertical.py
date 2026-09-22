from datetime import datetime
from typing import Any, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from schemas.rbac import VerticalRef


class ObjectTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    owning_service: str
    display_name: str


class FieldDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_type: str
    vertical_id: Optional[uuid.UUID] = None
    json_schema: dict[str, Any]
    ui_schema: Optional[dict[str, Any]] = None


class FieldDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    object_type: str
    vertical_id: Optional[uuid.UUID] = None
    version_no: int
    json_schema: dict[str, Any]
    ui_schema: Optional[dict[str, Any]] = None
    status: str


class VerticalPackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertical_id: uuid.UUID
    pack_code: str
    version_no: int
    manifest: dict[str, Any]


class ImportResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service: str
    status: str
    items: Optional[int] = None


class VerticalPackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vertical: VerticalRef
    pack_code: str
    version_no: int
    status: str
    import_results: Optional[list[ImportResult]] = None
    activated_at: Optional[datetime] = None
