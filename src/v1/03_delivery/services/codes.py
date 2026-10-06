"""Human-readable references (`WU-2026-0001`, `TSK-2026-000042`, `CR-003`), never handed out twice."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.insert_ignore import insert_ignore
from models.code_sequence import CodeSequence


async def next_number(session: AsyncSession, organization_id: uuid.UUID, scope: str) -> int:
    """
    Take the next number of the organization's `scope` series. The series row stays locked
    until the caller's transaction ends, so concurrent requests queue for it instead of
    reading the same number.
    """
    series_filter = (CodeSequence.organization_id == organization_id, CodeSequence.scope == scope)
    # Insert only when the series is new: on InnoDB an INSERT that meets an existing key takes a
    # shared lock, and two requests holding it would deadlock upgrading to FOR UPDATE below.
    series_exists = (await session.execute(select(CodeSequence.id).where(*series_filter))).first()
    if not series_exists:
        # A concurrent first request may create it meanwhile; the insert then skips.
        await session.execute(
            insert_ignore(CodeSequence).values(id=uuid.uuid4(), organization_id=organization_id, scope=scope)
        )
    series = (await session.execute(select(CodeSequence).where(*series_filter).with_for_update())).scalar_one()
    number = series.next_value
    series.next_value += 1
    await session.flush()
    return number


async def next_work_unit_code(session: AsyncSession, organization_id: uuid.UUID) -> str:
    year = datetime.now(timezone.utc).year
    return f"WU-{year}-{await next_number(session, organization_id, f'WU-{year}'):04d}"


async def next_task_code(session: AsyncSession, organization_id: uuid.UUID) -> str:
    year = datetime.now(timezone.utc).year
    return f"TSK-{year}-{await next_number(session, organization_id, f'TSK-{year}'):06d}"


async def next_change_request_no(session: AsyncSession, organization_id: uuid.UUID, work_unit_id: uuid.UUID) -> str:
    return f"CR-{await next_number(session, organization_id, f'CR:{work_unit_id}'):03d}"
