"""Human-readable references (`EMP-2026-0001`, `POS-2026-0001`), never handed out twice."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.insert_ignore import insert_ignore
from models.platform import CodeSequence


async def next_number(
    session: AsyncSession,
    organization_id: uuid.UUID,
    sequence_key: str,
    period_key: str = "ALL",
    prefix: str = "",
) -> int:
    """
    Take the next number of the organization's sequence. The series row stays locked
    until the caller's transaction ends, so concurrent requests queue for it instead of
    reading the same number.
    """
    series_filter = (
        CodeSequence.organization_id == organization_id,
        CodeSequence.sequence_key == sequence_key,
        CodeSequence.period_key == period_key,
    )
    series_exists = (await session.execute(select(CodeSequence.next_value).where(*series_filter))).first()
    if not series_exists:
        await session.execute(
            insert_ignore(CodeSequence).values(
                organization_id=organization_id,
                sequence_key=sequence_key,
                period_key=period_key,
                prefix=prefix or sequence_key,
                next_value=1,
            )
        )
    series = (await session.execute(select(CodeSequence).where(*series_filter).with_for_update())).scalar_one()
    number = series.next_value
    series.next_value += 1
    await session.flush()
    return number


async def next_worker_code(session: AsyncSession, organization_id: uuid.UUID, prefix: str = "EMP") -> str:
    year = datetime.now(timezone.utc).year
    num = await next_number(session, organization_id, sequence_key=f"WORKER:{prefix}", period_key=str(year), prefix=prefix)
    return f"{prefix}-{year}-{num:04d}"


async def next_position_code(session: AsyncSession, organization_id: uuid.UUID, prefix: str = "POS") -> str:
    year = datetime.now(timezone.utc).year
    num = await next_number(session, organization_id, sequence_key=f"POSITION:{prefix}", period_key=str(year), prefix=prefix)
    return f"{prefix}-{year}-{num:04d}"


async def next_requisition_code(session: AsyncSession, organization_id: uuid.UUID, prefix: str = "REQ") -> str:
    year = datetime.now(timezone.utc).year
    num = await next_number(session, organization_id, sequence_key=f"REQ:{prefix}", period_key=str(year), prefix=prefix)
    return f"{prefix}-{year}-{num:04d}"
