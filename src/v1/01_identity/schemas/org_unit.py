import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class HeadUserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class OrgUnitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., pattern=r"^[A-Za-z0-9\-]+$", description="Unique per organization. Letters, digits, dash.")
    name: str = Field(..., min_length=1, max_length=255)
    # The organization itself is the company: branches sit directly under it (no parent).
    unit_type: Literal["branch", "department", "team"]
    parent_id: Optional[uuid.UUID] = Field(None, description="Required for departments and teams; a branch has none")
    head_user_id: Optional[uuid.UUID] = None
    calendar_id: Optional[uuid.UUID] = None


class OrgUnitUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    head_user_id: Optional[uuid.UUID] = None
    calendar_id: Optional[uuid.UUID] = None
    status: Optional[Literal["active", "inactive"]] = None


class OrgUnitMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_parent_id: uuid.UUID
    reason: str = Field(..., min_length=1)


class OrgUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    unit_type: Optional[str] = None
    parent_id: Optional[uuid.UUID] = None
    path: str
    head_user: Optional[HeadUserRef] = None
    calendar_id: Optional[uuid.UUID] = None
    status: str
    version: int
    vertical_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Verticals set on this unit itself; empty means it inherits its parent's",
    )
    created_at: datetime
    updated_at: datetime


class OrgUnitVerticalsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertical_ids: list[uuid.UUID] = Field(
        ..., max_length=50, description="Replaces the unit's own verticals; empty means inherit from the parent"
    )


class UnitVerticalRef(BaseModel):
    id: uuid.UUID
    name: str
    status: str


class InheritedFromRef(BaseModel):
    id: uuid.UUID
    name: str
    unit_type: Optional[str] = None


class OrgUnitVerticalsResponse(BaseModel):
    """The verticals a unit works in. A team never sets its own; it inherits its department's."""

    unit_id: uuid.UUID
    own: list[UnitVerticalRef] = Field(..., description="Set on this unit itself")
    effective: list[UnitVerticalRef] = Field(
        ..., description="What applies: its own, else the nearest parent's (active verticals only)"
    )
    inherited_from: Optional[InheritedFromRef] = Field(
        None, description="The parent the effective verticals come from, when the unit has none of its own"
    )
