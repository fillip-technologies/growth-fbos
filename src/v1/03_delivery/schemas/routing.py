import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import SubjectRefInput, UnitRef, VerticalRef
from schemas.task_types import KEY_PATTERN
from schemas.tasks import TaskPriority


class RoutingRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type_code: Optional[str] = Field(None, description="Tasks of this type; or set `discipline` instead")
    discipline: Optional[str] = Field(
        None, min_length=1, max_length=50, pattern=KEY_PATTERN, description="Every task type of this discipline"
    )
    vertical_id: Optional[uuid.UUID] = Field(None, description="Only work for this vertical; omitted: any")
    unit_id: uuid.UUID = Field(..., description="The team the work goes to")
    accepts_requests: bool = Field(False, description="Anyone may ask this team for such work")

    @model_validator(mode="after")
    def matches_one_kind_of_work(self) -> "RoutingRuleCreate":
        # A type has one discipline, so naming both would be redundant or contradictory.
        if bool(self.task_type_code) == bool(self.discipline):
            raise ValueError("Set either the task type or the discipline the rule is for, not both")
        return self


class RoutingRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: Optional[uuid.UUID] = None
    accepts_requests: Optional[bool] = None
    active: Optional[bool] = None


class RoutingRuleResponse(BaseModel):
    id: uuid.UUID
    task_type_code: Optional[str] = None
    discipline: Optional[str] = None
    vertical: Optional[VerticalRef] = None
    unit: UnitRef
    accepts_requests: bool
    active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class RouteResponse(BaseModel):
    """Where a kind of work goes: the matching rule's team, or none."""

    unit: Optional[UnitRef] = None
    rule_id: Optional[uuid.UUID] = None
    accepts_requests: bool = False


class RequestableType(BaseModel):
    """A kind of work some team takes requests for."""

    task_type_code: str
    name: str
    discipline: str
    # The vertical the team takes these requests for; none: work for any other vertical.
    vertical: Optional[VerticalRef] = None
    unit: UnitRef


class RequestableTypesResponse(BaseModel):
    data: list[RequestableType]


class RequestCreate(BaseModel):
    """Ask another team for work: delivery picks the team from the routing rules."""

    model_config = ConfigDict(extra="forbid")

    task_type_code: str
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    vertical_id: Optional[uuid.UUID] = Field(
        None, description="The vertical (business line) it is for; a project subject's own vertical decides instead"
    )
    subject: Optional[SubjectRefInput] = None
    priority: Optional[TaskPriority] = "p3"
    due_at: Optional[datetime] = None
    attributes: Optional[dict] = None
