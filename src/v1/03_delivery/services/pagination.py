"""Shared cursor-pagination helper.

Every list endpoint uses keyset (cursor) pagination so pages never skip or repeat rows while
data changes. Each list names the order people expect (newest tasks first, milestones in
sequence...); the primary key breaks ties. Primary keys are random UUIDv4s, so the id alone
is a stable order but a meaningless one to a reader.
"""

from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from exceptions import ValidationFailedError
from schemas.common import PageMeta, decode_cursor, encode_cursor


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


def _after_cursor(cursor_data: dict, sort_column: InstrumentedAttribute, model: type, descending: bool):
    raw_key, last_id = cursor_data.get("key"), cursor_data.get("id")
    if raw_key is None or last_id is None:
        raise ValidationFailedError("cursor", "Unknown cursor: start again from the first page")
    key = _parse_cursor_value(sort_column, raw_key)
    if descending:
        return or_(sort_column < key, and_(sort_column == key, model.id < last_id))
    return or_(sort_column > key, and_(sort_column == key, model.id > last_id))


def _cursor_value(value: Any) -> str:
    if isinstance(value, datetime):
        # Stored without a zone (UTC): compare like with like whatever the driver returned.
        return (value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_cursor_value(sort_column: InstrumentedAttribute, raw_key: str) -> Any:
    python_type = sort_column.type.python_type
    try:
        if python_type is datetime:
            return datetime.fromisoformat(raw_key)
        if python_type is date:
            return date.fromisoformat(raw_key)
        if python_type is int:
            return int(raw_key)
    except ValueError:
        raise ValidationFailedError("cursor", "Unknown cursor: start again from the first page") from None
    return raw_key
