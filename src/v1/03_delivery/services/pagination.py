"""Shared cursor-pagination helper.

Every list endpoint in the spec uses keyset (cursor) pagination so pages
never skip or repeat rows while data changes. Primary keys in this service
are random UUIDv4s (not time-ordered), so ordering by id does not produce a
chronological default order -- it produces a stable, deterministic one,
which is what keyset pagination actually requires for correctness. Callers
that need a specific documented default order (e.g. tasks: due_at then
priority) pass an already-ordered query in; this helper only adds the id
tie-breaker and the cursor boundary, it does not choose sort fields itself.
"""

from typing import Sequence, TypeVar

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.common import PageMeta, decode_cursor, encode_cursor

ModelT = TypeVar("ModelT")


async def paginate_by_id(
    session: AsyncSession,
    query: Select,
    model: type,
    limit: int,
    cursor: str | None,
) -> tuple[Sequence[ModelT], PageMeta]:
    if cursor:
        cursor_data = decode_cursor(cursor)
        last_id = cursor_data.get("id")
        if last_id:
            query = query.where(model.id > last_id)

    query = query.order_by(model.id.asc()).limit(limit + 1)
    result = await session.execute(query)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor({"id": str(rows[-1].id)}) if has_more and rows else None

    return rows, PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit)
