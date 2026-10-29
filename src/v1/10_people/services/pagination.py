"""
Shared cursor-pagination helper.

Every list endpoint uses keyset (cursor) pagination so pages never skip or repeat rows while
data changes.
"""

from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence, TypeVar

from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from exceptions import ValidationFailedError
from schemas.common import PageMeta, decode_cursor, encode_cursor

ModelT = TypeVar("ModelT")


def _cursor_value(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "hex"):
        return str(v)
    return v


def _parse_cursor_key(raw: Any, column: InstrumentedAttribute) -> Any:
    col_type = getattr(column, "type", None)
    python_type = getattr(col_type, "python_type", None) if col_type is not None else None
    if python_type is datetime:
        return datetime.fromisoformat(str(raw))
    if python_type is date:
        return date.fromisoformat(str(raw))
    return raw


def _after_cursor(cursor: dict[str, Any], sort_column: InstrumentedAttribute, model: type, descending: bool):
    key = cursor.get("key")
    last_id = cursor.get("id")
    if key is None or last_id is None:
        raise ValidationFailedError("cursor", "Malformed cursor payload")
    key = _parse_cursor_key(key, sort_column)

    if descending:
        return or_(
            sort_column < key,
            and_(sort_column == key, model.id < last_id),
        )
    return or_(
        sort_column > key,
        and_(sort_column == key, model.id > last_id),
    )


async def paginate(
    session: AsyncSession,
    query: Select,
    model: type,
    limit: int,
    cursor: Optional[str],
    order_by: Optional[InstrumentedAttribute] = None,
    descending: bool = False,
) -> tuple[list[Any], PageMeta]:
    """One page of `query` ordered by (`order_by`, id), or by id alone when no column is given."""
    sort_column = order_by if order_by is not None else model.id
    if cursor:
        query = query.where(_after_cursor(decode_cursor(cursor), sort_column, model, descending))

    if descending:
        query = query.order_by(sort_column.desc(), model.id.desc())
    else:
        query = query.order_by(sort_column.asc(), model.id.asc())
    rows = list((await session.execute(query.limit(limit + 1))).scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor({"key": _cursor_value(getattr(last, sort_column.key)), "id": str(last.id)})
    return rows, PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit)


async def paginate_by_id(
    session: AsyncSession,
    query: Select,
    model: type,
    limit: int,
    cursor: Optional[str],
) -> tuple[Sequence[Any], PageMeta]:
    """Fallback helper for simple ID-based pagination."""
    return await paginate(session, query, model, limit, cursor, order_by=model.id, descending=False)
