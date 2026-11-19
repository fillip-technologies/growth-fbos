"""Tasks for activities other services log (revenue's calls), through /internal/tasks."""
from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import SubjectRefInput


class ActivityTaskCompletion(BaseModel):
    """The activity done: the task is finished with it, and its follow-up scheduled if asked."""

    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(None, max_length=10000, description="What was done; kept in the task's history.")
    follow_up_at: Optional[datetime] = Field(None, description="Schedule a follow-up task for then; none when empty.")
    follow_up_title: Optional[str] = Field(None, max_length=255, description="The follow-up's title (the next action).")


class ActivityTaskCreate(BaseModel):
    """A personal task about a revenue record for the caller: open, or already done (`completion`)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    task_type_code: str = "call"
    subject: SubjectRefInput
    due_at: Optional[datetime] = None
    completion: Optional[ActivityTaskCompletion] = None


class ActivityTaskComplete(ActivityTaskCompletion):
    """Finish one of the caller's own open tasks about `subject`."""

    subject: SubjectRefInput


class ActivityTaskRef(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    status: str


class ActivityTaskResult(BaseModel):
    task: ActivityTaskRef
    follow_up_task: Optional[ActivityTaskRef] = None
