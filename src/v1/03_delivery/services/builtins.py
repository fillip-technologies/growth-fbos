"""
The project types and task types every organization starts with.

They are global rows (no organization), inserted by seed.py when the service starts. Their
ids are fixed, so seeding again (on every start, by every running instance) inserts nothing.
Organizations add their own types next to these. Seeding never updates an existing row:
rename a built-in only together with a migration that renames the stored one.

Task types come with a profile (models/task_type_profile.py) per discipline, modelled on how
each kind of team works its tasks:
  * software   — stories sized in points, bugs graded by severity, pull-request links on submit;
  * sales      — cadence touches (call, email, meeting) that record a disposition and schedule
                 the next touch, with an inbound response SLA;
  * creative   — deliverables with an asset link, reviewed over a set number of revision rounds;
  * operations — tickets and work orders with response and resolution SLAs per priority.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from database.insert_ignore import insert_ignore
from models.task_template import TaskType
from models.task_type_profile import TaskTypeProfile
from models.work_unit_template import WorkUnitType

_BUILTIN_NAMESPACE = uuid.UUID("5b0c6f0e-3d1a-4c8e-9f27-03de11e7b001")

BUILTIN_WORK_UNIT_TYPES = [
    {"code": "project", "name": "Project", "category": "project", "requires_client": True},
    {"code": "retainer", "name": "Retainer", "category": "retainer", "requires_client": True},
    {"code": "internal", "name": "Internal initiative", "category": "internal", "requires_client": False},
]
BUILTIN_TASK_TYPES = [
    {"code": "task", "name": "Task", "category": "general", "requires_review": False, "default_estimate_minutes": 60},
    {"code": "bug", "name": "Bug fix", "category": "defect", "requires_review": True, "default_estimate_minutes": 120},
    {"code": "feature", "name": "Feature", "category": "development", "requires_review": True, "default_estimate_minutes": 240},
    {"code": "review", "name": "Review", "category": "review", "requires_review": False, "default_estimate_minutes": 60},
    {"code": "story", "name": "User story", "category": "development", "requires_review": True, "default_estimate_minutes": None},
    {"code": "call", "name": "Call", "category": "outreach", "requires_review": False, "default_estimate_minutes": 15},
    {"code": "email", "name": "Email", "category": "outreach", "requires_review": False, "default_estimate_minutes": 10},
    {"code": "meeting", "name": "Meeting", "category": "outreach", "requires_review": False, "default_estimate_minutes": 45},
    {"code": "deliverable", "name": "Deliverable", "category": "creative", "requires_review": True, "default_estimate_minutes": 480},
    {"code": "ticket", "name": "Service ticket", "category": "service", "requires_review": False, "default_estimate_minutes": 60},
    {"code": "work_order", "name": "Work order", "category": "field_service", "requires_review": True, "default_estimate_minutes": 120},
]

_POINTS = ["1", "2", "3", "5", "8", "13"]
_SEVERITIES = ["critical", "major", "minor", "trivial"]
_PULL_REQUEST = {"key": "pull_request_url", "label": "Pull request", "type": "url", "show_on_card": True}
# The four original built-ins (task, bug, feature, review) only gain optional fields, so tasks
# made before profiles existed submit exactly as before; the newer types may require more.
_PULL_REQUEST_ON_SUBMIT = {**_PULL_REQUEST, "required_on_submit": True}
_BRANCH = {"key": "branch", "label": "Branch", "type": "text"}
_SALES_FOLLOW_UP = [
    {"code": "connected", "label": "Connected", "kind": "success", "follow_up_in_days": 3},
    {"code": "meeting_booked", "label": "Meeting booked", "kind": "success"},
    {"code": "left_voicemail", "label": "Left voicemail", "kind": "neutral", "follow_up_in_days": 2},
    {"code": "no_answer", "label": "No answer", "kind": "neutral", "follow_up_in_days": 1},
    {"code": "gatekeeper", "label": "Gatekeeper", "kind": "neutral", "follow_up_in_days": 2},
    {"code": "not_interested", "label": "Not interested", "kind": "failure"},
    {"code": "wrong_number", "label": "Wrong number", "kind": "failure"},
]
# Inbound leads go cold within minutes: first touch inside 5 / 15 / 60 / 240 minutes.
_SALES_RESPONSE_SLA = {"p1": 5, "p2": 15, "p3": 60, "p4": 240}
_OPS_RESPONSE_SLA = {"p1": 15, "p2": 60, "p3": 240, "p4": 480}
_OPS_RESOLUTION_SLA = {"p1": 240, "p2": 480, "p3": 1440, "p4": 4320}

BUILTIN_TASK_TYPE_PROFILES = {
    "task": {"discipline": "general"},
    "review": {"discipline": "general"},
    "story": {
        "discipline": "software",
        "estimation_unit": "points",
        "fields": [
            {"key": "story_points", "label": "Story points", "type": "choice", "options": _POINTS, "show_on_card": True},
            {"key": "acceptance_criteria", "label": "Acceptance criteria", "type": "long_text"},
            _BRANCH,
            _PULL_REQUEST_ON_SUBMIT,
        ],
    },
    "feature": {
        "discipline": "software",
        "estimation_unit": "points",
        "fields": [
            {"key": "story_points", "label": "Story points", "type": "choice", "options": _POINTS, "show_on_card": True},
            _BRANCH,
            _PULL_REQUEST,
        ],
    },
    "bug": {
        "discipline": "software",
        "fields": [
            {"key": "severity", "label": "Severity", "type": "choice", "options": _SEVERITIES, "show_on_card": True},
            {"key": "environment", "label": "Environment", "type": "choice", "options": ["production", "staging", "development"]},
            {"key": "steps_to_reproduce", "label": "Steps to reproduce", "type": "long_text"},
            _PULL_REQUEST,
            {"key": "resolution", "label": "Resolution", "type": "choice", "options": ["fixed", "cannot_reproduce", "duplicate", "wont_fix"]},
        ],
    },
    "call": {
        "discipline": "sales",
        "estimation_unit": "count",
        "fields": [
            {"key": "phone", "label": "Phone", "type": "phone", "show_on_card": True},
            {"key": "contact_name", "label": "Contact", "type": "text", "show_on_card": True},
            {"key": "talk_track", "label": "Talk track", "type": "long_text"},
            {"key": "call_notes", "label": "Call notes", "type": "long_text"},
        ],
        "outcomes": _SALES_FOLLOW_UP,
        "response_sla_minutes": _SALES_RESPONSE_SLA,
    },
    "email": {
        "discipline": "sales",
        "estimation_unit": "count",
        "fields": [
            {"key": "email_address", "label": "Email", "type": "email", "show_on_card": True},
            {"key": "contact_name", "label": "Contact", "type": "text", "show_on_card": True},
            {"key": "template", "label": "Template", "type": "text"},
        ],
        "outcomes": [
            {"code": "sent", "label": "Sent", "kind": "neutral", "follow_up_in_days": 3},
            {"code": "replied", "label": "Replied", "kind": "success"},
            {"code": "bounced", "label": "Bounced", "kind": "failure"},
        ],
        "response_sla_minutes": _SALES_RESPONSE_SLA,
    },
    "meeting": {
        "discipline": "sales",
        "fields": [
            {"key": "meeting_url", "label": "Meeting link", "type": "url", "show_on_card": True},
            {"key": "meeting_at", "label": "Meeting time", "type": "datetime", "show_on_card": True},
            {"key": "attendees", "label": "Attendees", "type": "text"},
        ],
        "outcomes": [
            {"code": "held_qualified", "label": "Held: qualified", "kind": "success"},
            {"code": "held_nurture", "label": "Held: nurture", "kind": "neutral", "follow_up_in_days": 14},
            {"code": "no_show", "label": "No show", "kind": "failure", "follow_up_in_days": 1},
            {"code": "rescheduled", "label": "Rescheduled", "kind": "neutral"},
        ],
    },
    "deliverable": {
        "discipline": "creative",
        "fields": [
            {
                "key": "deliverable_type",
                "label": "Deliverable",
                "type": "choice",
                "options": ["design", "copy", "video", "web", "social", "print"],
                "show_on_card": True,
            },
            {"key": "brief", "label": "Brief", "type": "long_text"},
            {"key": "asset_url", "label": "Asset link", "type": "url", "required_on_submit": True, "show_on_card": True},
            {"key": "client_feedback", "label": "Client feedback", "type": "long_text"},
        ],
        "review_rounds_included": 2,
    },
    "ticket": {
        "discipline": "operations",
        "fields": [
            {"key": "category", "label": "Category", "type": "choice", "options": ["incident", "request", "problem", "change"], "show_on_card": True},
            {"key": "reported_by", "label": "Reported by", "type": "text"},
            {"key": "resolution_notes", "label": "Resolution notes", "type": "long_text", "required_on_submit": True},
        ],
        "outcomes": [
            {"code": "resolved", "label": "Resolved", "kind": "success"},
            {"code": "workaround", "label": "Workaround given", "kind": "neutral"},
            {"code": "escalated", "label": "Escalated", "kind": "neutral"},
            {"code": "not_a_fault", "label": "Not a fault", "kind": "neutral"},
        ],
        "response_sla_minutes": _OPS_RESPONSE_SLA,
        "resolution_sla_minutes": _OPS_RESOLUTION_SLA,
    },
    "work_order": {
        "discipline": "operations",
        "fields": [
            {"key": "site", "label": "Site", "type": "text", "required": True, "show_on_card": True},
            {"key": "equipment_id", "label": "Equipment", "type": "text", "show_on_card": True},
            {"key": "safety_confirmed", "label": "Safety checks confirmed", "type": "boolean", "required_on_submit": True},
            {"key": "customer_signoff_by", "label": "Signed off by", "type": "text", "required_on_submit": True},
        ],
        "response_sla_minutes": _OPS_RESPONSE_SLA,
        "resolution_sla_minutes": _OPS_RESOLUTION_SLA,
    },
}


def _builtin_id(kind: str, code: str) -> uuid.UUID:
    return uuid.uuid5(_BUILTIN_NAMESPACE, f"{kind}:{code}")


BUILTIN_WORK_UNIT_TYPE_IDS = {t["code"]: _builtin_id("work_unit_type", t["code"]) for t in BUILTIN_WORK_UNIT_TYPES}
BUILTIN_TASK_TYPE_IDS = {t["code"]: _builtin_id("task_type", t["code"]) for t in BUILTIN_TASK_TYPES}


def _profile_row(code: str) -> dict:
    profile = BUILTIN_TASK_TYPE_PROFILES.get(code, {})
    return {
        "task_type_id": BUILTIN_TASK_TYPE_IDS[code],
        "discipline": profile.get("discipline", "general"),
        "estimation_unit": profile.get("estimation_unit", "minutes"),
        "fields": profile.get("fields", []),
        "outcomes": profile.get("outcomes", []),
        "response_sla_minutes": profile.get("response_sla_minutes"),
        "resolution_sla_minutes": profile.get("resolution_sla_minutes"),
        "review_rounds_included": profile.get("review_rounds_included"),
        "archived": False,
    }


async def ensure_builtin_types(session: AsyncSession) -> None:
    """Insert whichever built-in types are missing; the caller commits."""
    await session.execute(
        insert_ignore(WorkUnitType),
        [{"id": BUILTIN_WORK_UNIT_TYPE_IDS[t["code"]], "organization_id": None, **t} for t in BUILTIN_WORK_UNIT_TYPES],
    )
    await session.execute(
        insert_ignore(TaskType),
        [{"id": BUILTIN_TASK_TYPE_IDS[t["code"]], "organization_id": None, **t} for t in BUILTIN_TASK_TYPES],
    )
    await session.execute(insert_ignore(TaskTypeProfile), [_profile_row(t["code"]) for t in BUILTIN_TASK_TYPES])
