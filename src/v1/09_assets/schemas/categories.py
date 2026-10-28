import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssetCategoryCreate(BaseModel):
    code: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    parent_id: Optional[uuid.UUID] = None


class AssetCategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    parent_id: Optional[uuid.UUID] = None


class AssetCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    code: str
    name: str
    parent_id: Optional[uuid.UUID] = None


class AssetTypeCreate(BaseModel):
    category_id: uuid.UUID
    code: str = Field(..., max_length=100)
    name: str = Field(..., max_length=255)
    family: str = Field(..., max_length=50)  # hardware, software, facility, credential, vehicle
    tracks_expiry: bool = False
    single_custodian: bool = True
    attribute_schema: Optional[dict[str, Any]] = None


class AssetTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    family: Optional[str] = Field(None, max_length=50)
    tracks_expiry: Optional[bool] = None
    single_custodian: Optional[bool] = None
    attribute_schema: Optional[dict[str, Any]] = None


class AssetTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    code: str
    name: str
    family: str
    tracks_expiry: bool
    single_custodian: bool
    attribute_schema: Optional[dict[str, Any]] = None
