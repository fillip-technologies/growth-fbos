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
        last_id = decode_cursor(cursor).get("id")
        if last_id:
            query = query.where(model.id > last_id)
    query = query.order_by(model.id.asc()).limit(limit + 1)
    rows = list((await session.execute(query)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = encode_cursor({"id": str(rows[-1].id)}) if has_more and rows else None
    return rows, PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit)
