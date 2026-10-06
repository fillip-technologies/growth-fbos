"""
The project types and task types every organization starts with.

They are global rows (no organization), inserted by seed.py when the service starts. Their
ids are fixed, so seeding again (on every start, by every running instance) inserts nothing.
Organizations add their own types next to these. Seeding never updates an existing row:
rename a built-in only together with a migration that renames the stored one.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from database.insert_ignore import insert_ignore
from models.task_template import TaskType
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
]


def _builtin_id(kind: str, code: str) -> uuid.UUID:
    return uuid.uuid5(_BUILTIN_NAMESPACE, f"{kind}:{code}")


BUILTIN_WORK_UNIT_TYPE_IDS = {t["code"]: _builtin_id("work_unit_type", t["code"]) for t in BUILTIN_WORK_UNIT_TYPES}
BUILTIN_TASK_TYPE_IDS = {t["code"]: _builtin_id("task_type", t["code"]) for t in BUILTIN_TASK_TYPES}


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
