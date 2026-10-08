import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from schemas.common import UserRef


class DeliverySettingsResponse(BaseModel):
    """The organization's delivery settings (models/settings.py says what each one does)."""

    team_assignment_only: bool
    team_visibility: bool
    # 0 while every setting is still at its default; send it back as If-Match to change them.
    version: int
    updated_at: Optional[datetime] = None
    updated_by: Optional[UserRef] = None


class DeliverySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_assignment_only: Optional[bool] = None
    team_visibility: Optional[bool] = None


class AssignablePerson(BaseModel):
    id: uuid.UUID
    name: str
    # Belongs to the team asked about (identity's rule); listed first.
    in_unit: bool


class AssignablePeopleResponse(BaseModel):
    """Who may be given the team's work, by name."""

    data: list[AssignablePerson]
    # True when the organization assigns only within the team: `data` is then just its people.
    team_only: bool
