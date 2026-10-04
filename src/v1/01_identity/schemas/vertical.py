from typing import Any, Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.rbac import VerticalRef


class ObjectTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    owning_service: str
    display_name: str


# ---------------------------------------------------------------------------
# Verticals (per client)
# ---------------------------------------------------------------------------

class VerticalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9\-]*$")


class VerticalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[Literal["active", "archived"]] = None


class VerticalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    status: str


# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------

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
    source_pack_id: Optional[uuid.UUID] = None
    source_pack_version: Optional[int] = None


# ---------------------------------------------------------------------------
# Vertical pack content: a list of typed sections. Only "custom_fields" exists today;
# new section types (workflows, work templates) join the `PackSection` union.
# ---------------------------------------------------------------------------

PackFieldType = Literal["text", "number", "integer", "boolean", "date", "choice"]


class PackField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(..., min_length=1, max_length=120)
    type: PackFieldType
    required: bool = False
    options: list[str] = Field(default_factory=list, description="Choices, for type 'choice' only")

    @field_validator("label")
    @classmethod
    def strip_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a label")
        return value.strip()

    @model_validator(mode="after")
    def check_options(self) -> "PackField":
        self.options = list(dict.fromkeys(o.strip() for o in self.options if o.strip()))
        if self.type == "choice" and len(self.options) < 2:
            raise ValueError(f"'{self.key}': a choice list needs at least two options")
        if self.type != "choice" and self.options:
            raise ValueError(f"'{self.key}': only choice fields take options")
        return self


class CustomFieldsSection(BaseModel):
    """Custom fields added to one business object type (work unit, deal, invoice…)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["custom_fields"]
    object_type: str
    fields: list[PackField] = Field(..., min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> "CustomFieldsSection":
        keys = [f.key for f in self.fields]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise ValueError(f"Field keys used twice: {', '.join(duplicates)}")
        return self


PackSection = CustomFieldsSection


class PackContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[PackSection] = Field(default_factory=list)

    @model_validator(mode="after")
    def one_section_per_object_type(self) -> "PackContent":
        types = [s.object_type for s in self.sections]
        duplicates = sorted({t for t in types if types.count(t) > 1})
        if duplicates:
            raise ValueError(f"Only one custom fields section per record type: {', '.join(duplicates)}")
        return self


# ---------------------------------------------------------------------------
# Vertical packs
# ---------------------------------------------------------------------------

class VerticalPackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertical_id: uuid.UUID
    code: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    content: PackContent = Field(default_factory=PackContent, description="Content of the first draft (version 1)")


class VerticalPackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertical_id: Optional[uuid.UUID] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)


class PackVersionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: PackContent


class PackVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_no: int
    status: Literal["draft", "published"]
    revision: int
    content: PackContent
    created_at: str = Field(..., description="ISO 8601 UTC")
    published_at: Optional[str] = Field(None, description="ISO 8601 UTC")


PlanAction = Literal["create", "update", "unchanged", "retire"]


class PackPlanItem(BaseModel):
    """What installing a version does to one record type's custom fields."""

    object_type: str
    action: PlanAction
    added_fields: list[str] = Field(default_factory=list)
    removed_fields: list[str] = Field(default_factory=list)
    changed_fields: list[str] = Field(default_factory=list)
    field_definition_id: Optional[uuid.UUID] = None


class PackInstallationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: uuid.UUID
    version_no: int
    status: str
    results: list[PackPlanItem] = Field(default_factory=list)
    installed_at: str = Field(..., description="ISO 8601 UTC")


class VerticalPackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    vertical: VerticalRef
    versions: list[PackVersionResponse]
    latest_published_version: Optional[int] = None
    draft_version: Optional[int] = None
    installation: Optional[PackInstallationResponse] = Field(
        None, description="This pack's installation in the organization the request acts in"
    )


class PackInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_no: int = Field(..., ge=1)


class PackPreviewResponse(BaseModel):
    version_no: int
    installed_version_no: Optional[int] = None
    items: list[PackPlanItem]
