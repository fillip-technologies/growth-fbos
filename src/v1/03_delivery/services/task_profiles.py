"""
What a task's type asks of it: its fields (checked here), its outcomes and its SLA clocks.

Attributes not named by the type's fields pass through unchecked: the organization's custom
fields for tasks (identity's field definitions, installed by vertical packs) live there too,
and delivery can't read their schemas. Keys the service writes itself are refused from callers.

SLA clocks run from the task's creation, as the type's targets for the task's priority say:
around the clock, or, given the team's working calendar (the organization's `working_hours`
setting, services/calendars.py), in working time only. A block that pauses the SLA (`pause_sla`)
stops the resolution clock until the task is unblocked; the pause is counted the same way.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import TaskAttributesInvalidError
from models.task import Task
from models.task_type_profile import TaskTypeProfile
from schemas.task_types import RESERVED_ATTRIBUTE_KEYS, TaskField, TaskOutcome, TaskTypeBehaviour
from services.work_calendar import WorkCalendar

AT_RISK_PCT = 75.0
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9 ()./-]{5,30}$")
_LONG_TEXT_MAX = 10_000
_TEXT_MAX = 500


@dataclass(frozen=True)
class Profile:
    """A task type's behaviour, read once per page of tasks."""

    discipline: str = "general"
    estimation_unit: str = "minutes"
    fields: list[TaskField] = field(default_factory=list)
    outcomes: list[TaskOutcome] = field(default_factory=list)
    response_sla_minutes: dict[str, int] = field(default_factory=dict)
    resolution_sla_minutes: dict[str, int] = field(default_factory=dict)
    review_rounds_included: Optional[int] = None
    archived: bool = False

    def outcome(self, code: str) -> Optional[TaskOutcome]:
        return next((o for o in self.outcomes if o.code == code), None)


DEFAULT_PROFILE = Profile()


def profile_from_row(row: Optional[TaskTypeProfile]) -> Profile:
    if row is None:
        return DEFAULT_PROFILE
    behaviour = TaskTypeBehaviour(
        discipline=row.discipline,
        estimation_unit=row.estimation_unit,
        fields=row.fields or [],
        outcomes=row.outcomes or [],
        response_sla_minutes=row.response_sla_minutes,
        resolution_sla_minutes=row.resolution_sla_minutes,
        review_rounds_included=row.review_rounds_included,
    )
    return Profile(
        discipline=behaviour.discipline,
        estimation_unit=behaviour.estimation_unit,
        fields=behaviour.fields,
        outcomes=behaviour.outcomes,
        response_sla_minutes=dict(behaviour.response_sla_minutes or {}),
        resolution_sla_minutes=dict(behaviour.resolution_sla_minutes or {}),
        review_rounds_included=behaviour.review_rounds_included,
        archived=row.archived,
    )


async def load_profiles(session: AsyncSession, task_type_ids: set[uuid.UUID]) -> dict[uuid.UUID, Profile]:
    """Profiles by task type id; a type without one behaves as a plain task."""
    if not task_type_ids:
        return {}
    rows = (
        await session.execute(select(TaskTypeProfile).where(TaskTypeProfile.task_type_id.in_(task_type_ids)))
    ).scalars()
    found = {row.task_type_id: profile_from_row(row) for row in rows}
    return {type_id: found.get(type_id, DEFAULT_PROFILE) for type_id in task_type_ids}


async def load_profile(session: AsyncSession, task_type_id: uuid.UUID) -> Profile:
    return (await load_profiles(session, {task_type_id}))[task_type_id]


# --- Attributes ----------------------------------------------------------


def clean_attributes(fields: list[TaskField], attributes: Optional[dict], *, enforce_required: bool) -> dict:
    """
    The caller's attributes checked against the type's fields: values of the right kind, no
    reserved keys and, when `enforce_required`, every required field present. An empty value
    (None, "", []) means "not set" and is dropped. Raises TaskAttributesInvalidError listing
    every problem at once.
    """
    by_key = {f.key: f for f in fields}
    cleaned: dict[str, Any] = {}
    issues: list[dict[str, str]] = []
    for key, value in (attributes or {}).items():
        if key in RESERVED_ATTRIBUTE_KEYS:
            issues.append(_issue(key, "is set by the service itself"))
            continue
        if _is_empty(value):
            continue
        definition = by_key.get(key)
        problem = _value_problem(definition, value) if definition else None
        if problem:
            issues.append(_issue(key, problem))
            continue
        cleaned[key] = value
    if enforce_required:
        issues.extend(_issue(f.key, f"{f.label} is required") for f in fields if f.required and f.key not in cleaned)
    if issues:
        raise TaskAttributesInvalidError(issues)
    return cleaned


def merge_attributes(stored: dict, changes: dict, fields: list[TaskField]) -> dict:
    """
    `changes` applied over the stored attributes: an empty value removes the key. Refuses to
    remove a field the type requires. Returns the new attributes.
    """
    removed = {key for key, value in changes.items() if _is_empty(value)}
    cleaned = clean_attributes(fields, {k: v for k, v in changes.items() if k not in removed}, enforce_required=False)
    blocked_removals = [f for f in fields if f.required and f.key in removed]
    reserved_removals = removed & RESERVED_ATTRIBUTE_KEYS
    issues = [_issue(f.key, f"{f.label} is required") for f in blocked_removals]
    issues += [_issue(key, "is set by the service itself") for key in sorted(reserved_removals)]
    if issues:
        raise TaskAttributesInvalidError(issues)
    merged = {k: v for k, v in stored.items() if k not in removed}
    merged.update(cleaned)
    return merged


def missing_on_submit(fields: list[TaskField], attributes: dict) -> list[dict[str, str]]:
    return [_issue(f.key, f"{f.label} is needed before submitting") for f in fields if f.required_on_submit and _is_empty(attributes.get(f.key))]


def carried_attributes(fields: list[TaskField], attributes: dict) -> dict:
    """What a follow-up inherits: the context fields (who to call, where), not what the last touch recorded."""
    return {f.key: attributes[f.key] for f in fields if not f.required_on_submit and f.key in attributes and f.type != "long_text"}


def _issue(key: str, problem: str) -> dict[str, str]:
    return {"field": f"attributes.{key}", "issue": problem}


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _value_problem(definition: TaskField, value: Any) -> Optional[str]:
    """Why `value` doesn't fit the field, or None."""
    kind = definition.type
    if kind in ("text", "long_text"):
        limit = _LONG_TEXT_MAX if kind == "long_text" else _TEXT_MAX
        if not isinstance(value, str):
            return "must be text"
        return f"must be at most {limit} characters" if len(value) > limit else None
    if kind == "number":
        return None if _is_number(value) else "must be a number"
    if kind == "integer":
        return None if _is_number(value) and float(value).is_integer() else "must be a whole number"
    if kind == "boolean":
        return None if isinstance(value, bool) else "must be yes or no"
    if kind == "date":
        return None if _parses(value, date.fromisoformat) else "must be a date (YYYY-MM-DD)"
    if kind == "datetime":
        return None if _parses(value, datetime.fromisoformat) else "must be a date and time"
    if kind == "choice":
        return None if value in definition.options else f"must be one of: {', '.join(definition.options)}"
    if kind == "multi_choice":
        valid = isinstance(value, list) and all(item in definition.options for item in value)
        return None if valid else f"must be a list taken from: {', '.join(definition.options)}"
    if kind == "url":
        valid = isinstance(value, str) and value.startswith(("https://", "http://")) and len(value) <= 2000
        return None if valid else "must be a web link starting with http:// or https://"
    if kind == "email":
        return None if isinstance(value, str) and _EMAIL_RE.match(value) else "must be an email address"
    if kind == "phone":
        return None if isinstance(value, str) and _PHONE_RE.match(value) else "must be a phone number"
    return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parses(value: Any, parse) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parse(value)
    except ValueError:
        return False
    return True


# --- SLA -------------------------------------------------------------------


def as_utc(moment: datetime) -> datetime:
    """Stored timestamps come back without a zone on some drivers; they are UTC."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def clock_minutes(start: datetime, end: datetime, calendar: Optional[WorkCalendar] = None) -> float:
    """Minutes from `start` to `end`: working minutes on `calendar`, else every minute."""
    if calendar is not None:
        return calendar.minutes_between(as_utc(start), as_utc(end))
    return (as_utc(end) - as_utc(start)).total_seconds() / 60


def clock_add(start: datetime, minutes: float, calendar: Optional[WorkCalendar] = None) -> datetime:
    """When `minutes` from `start` run out: working minutes on `calendar`, else every minute."""
    if calendar is not None:
        return calendar.add_minutes(as_utc(start), minutes)
    return as_utc(start) + timedelta(minutes=minutes)


def resolution_due_at(
    created_at: datetime, profile: Profile, priority: str, paused_minutes: int = 0, calendar: Optional[WorkCalendar] = None
) -> Optional[datetime]:
    target = profile.resolution_sla_minutes.get(priority)
    if not target:
        return None
    return clock_add(created_at, target + paused_minutes, calendar)


def paused_minutes(task: Task, until: datetime, calendar: Optional[WorkCalendar] = None) -> int:
    """Minutes the resolution clock has been paused, including a pause still running."""
    attributes = task.attributes or {}
    total = int(attributes.get("sla_paused_minutes") or 0)
    since = attributes.get("sla_paused_since")
    if since:
        total += max(0, int(clock_minutes(datetime.fromisoformat(since), until, calendar)))
    return total


def resolution_sla(task: Task, profile: Profile, now: datetime, calendar: Optional[WorkCalendar] = None) -> Optional[dict]:
    target = profile.resolution_sla_minutes.get(task.priority)
    if not target or task.status == "cancelled":
        return None
    finished_at = as_utc(task.completed_at) if task.status == "done" and task.completed_at else None
    paused = paused_minutes(task, finished_at or now, calendar)
    due_at = clock_add(task.created_at, target + paused, calendar)
    elapsed = clock_minutes(task.created_at, finished_at or now, calendar) - paused
    consumed = round(max(0.0, elapsed) / target * 100, 1)
    if finished_at:
        state = "met" if finished_at <= due_at else "breached_closed"
    elif (task.attributes or {}).get("sla_paused_since"):
        state = "paused"
    else:
        state = _running_state(consumed)
    return {
        "kind": "resolution", "state": state, "due_at": due_at, "consumed_pct": consumed, "target_minutes": target,
        "paused_minutes": paused, "working_hours": calendar is not None,
    }


def response_sla(task: Task, profile: Profile, now: datetime, calendar: Optional[WorkCalendar] = None) -> Optional[dict]:
    """Time to first response: the task is started (picked up) within the target."""
    target = profile.response_sla_minutes.get(task.priority)
    if not target or task.status == "cancelled":
        return None
    created_at = as_utc(task.created_at)
    due_at = clock_add(created_at, target, calendar)
    responded = (task.attributes or {}).get("responded_at")
    responded_at = as_utc(datetime.fromisoformat(responded)) if responded else None
    if responded_at is None and task.status == "done" and task.completed_at:
        responded_at = as_utc(task.completed_at)
    elapsed = clock_minutes(created_at, responded_at or now, calendar)
    consumed = round(max(0.0, elapsed) / target * 100, 1)
    if responded_at:
        state = "met" if responded_at <= due_at else "breached_closed"
    else:
        state = _running_state(consumed)
    return {
        "kind": "response", "state": state, "due_at": due_at, "consumed_pct": consumed, "target_minutes": target,
        "paused_minutes": 0, "working_hours": calendar is not None,
    }


def _running_state(consumed_pct: float) -> str:
    if consumed_pct >= 100:
        return "breached"
    return "at_risk" if consumed_pct >= AT_RISK_PCT else "running"
