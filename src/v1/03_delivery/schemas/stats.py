"""Counts over the tasks and projects someone may see, for the console's overview."""
import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CountBucket(BaseModel):
    key: str
    label: Optional[str] = None
    count: int


class PersonWork(BaseModel):
    """One assignee's open work per board column, what of it is late, and what they finished lately.
    `user_id` is null for the tasks nobody has taken yet."""

    user_id: Optional[uuid.UUID] = None
    todo: int = 0
    in_progress: int = 0
    in_review: int = 0
    blocked: int = 0
    open: int = 0
    overdue: int = 0
    done_recent: int = 0


class WeekFlow(BaseModel):
    week_start: date  # Monday
    created: int
    completed: int


class TaskStats(BaseModel):
    as_of: datetime
    done_within_days: int
    open: int
    overdue: int
    due_next_7_days: int
    unassigned: int
    by_column: list[CountBucket]  # to do, in progress, in review, blocked, done (recently)
    by_priority: list[CountBucket]  # open tasks
    people: list[PersonWork]  # most open work first; the unassigned row last
    weekly: list[WeekFlow]  # oldest first


class ProjectRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    health: str
    status: str
    progress_pct: float
    planned_end: Optional[date] = None
    manager_user_id: Optional[uuid.UUID] = None


class ProjectStats(BaseModel):
    as_of: date
    total: int
    running: int  # planned, active or on hold
    by_status: list[CountBucket]
    by_health: list[CountBucket]  # running projects
    average_progress_pct: float  # running projects
    late: int  # running projects past their planned end
    needs_attention: list[ProjectRef]  # running projects that are red, amber or late; worst first
