import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ValidationFailedError
from models.audit import AuditAnchor, AuditEvent
from schemas.audit import (
    AuditActorRef,
    AuditChangeItem,
    AuditContextData,
    AuditEventResponse,
    AuditExportRequest,
    AuditSubjectRef,
    AuditVerifyResult,
    JobResponse,
)
from schemas.common import PageMeta, PageResponse, decode_cursor, encode_cursor


# --- Response builders -------------------------------------------------------


def _to_audit_event_response(event: AuditEvent) -> AuditEventResponse:
    changes = []
    if event.changes:
        raw = event.changes if isinstance(event.changes, list) else []
        changes = [AuditChangeItem(field=c.get("field", ""), old=c.get("old"), new=c.get("new")) for c in raw]

    context = None
    if event.context:
        ctx = event.context
        context = AuditContextData(
            ip=ctx.get("ip"),
            user_agent=ctx.get("user_agent"),
            request_id=ctx.get("request_id"),
            correlation_id=ctx.get("correlation_id"),
        )

    return AuditEventResponse(
        id=event.id,
        occurred_at=event.occurred_at,
        category=event.category,
        source_service=event.source_service,
        event_type=event.event_type,
        action=event.action,
        actor=AuditActorRef(type=event.actor_type, id=event.actor_id, name="User"),
        subject=AuditSubjectRef(type=event.subject_type, id=event.subject_id),
        changes=changes,
        context=context,
        severity=event.severity,
    )


# --- Cursor pagination for audit events (sorted by occurred_at DESC) ---------


async def _paginate_audit_events(
    session: AsyncSession,
    query,
    limit: int,
    cursor: Optional[str],
) -> tuple[list[AuditEvent], PageMeta]:
    if cursor:
        cursor_data = decode_cursor(cursor)
        last_occurred_at = cursor_data.get("occurred_at")
        last_id = cursor_data.get("id")
        if last_occurred_at and last_id:
            query = query.where(
                or_(
                    AuditEvent.occurred_at < last_occurred_at,
                    and_(AuditEvent.occurred_at == last_occurred_at, AuditEvent.id > last_id),
                )
            )

    query = query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.asc()).limit(limit + 1)
    result = await session.execute(query)
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor({"occurred_at": last.occurred_at.isoformat(), "id": str(last.id)})

    return rows, PageMeta(next_cursor=next_cursor, has_more=has_more, limit=limit)


# --- Audit endpoints ---------------------------------------------------------


async def search_audit_events(
    session: AsyncSession,
    org_id: uuid.UUID,
    subject_type: Optional[str],
    subject_id: Optional[uuid.UUID],
    actor_id: Optional[uuid.UUID],
    category: Optional[str],
    from_: Optional[datetime],
    to: Optional[datetime],
    event_type: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> PageResponse[AuditEventResponse]:
    query = select(AuditEvent).where(AuditEvent.organization_id == org_id)

    if subject_type is not None:
        query = query.where(AuditEvent.subject_type == subject_type)
    if subject_id is not None:
        query = query.where(AuditEvent.subject_id == subject_id)
    if actor_id is not None:
        query = query.where(AuditEvent.actor_id == actor_id)
    if category is not None:
        query = query.where(AuditEvent.category == category)
    if from_ is not None:
        query = query.where(AuditEvent.occurred_at >= from_)
    if to is not None:
        query = query.where(AuditEvent.occurred_at <= to)
    if event_type is not None:
        query = query.where(AuditEvent.event_type == event_type)

    rows, page = await _paginate_audit_events(session, query, limit, cursor)
    data = [_to_audit_event_response(e) for e in rows]
    return PageResponse(data=data, page=page)


async def export_audit_events(
    session: AsyncSession,
    org_id: uuid.UUID,
    payload: AuditExportRequest,
    idempotency_key: Optional[str],
) -> JobResponse:
    valid_formats = {"csv", "jsonl"}
    if payload.format not in valid_formats:
        raise ValidationFailedError([{"field": "format", "code": "invalid_enum", "message": "format must be csv or jsonl"}])

    if payload.to <= payload.from_:
        raise ValidationFailedError([{"field": "to", "code": "must_be_after_from", "message": "to must be later than from"}])

    # Async export job — no worker in this pass; return queued status
    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    return JobResponse(
        id=job_id,
        status="queued",
        status_url=None,
        created_at=now,
    )


async def verify_audit_integrity(
    session: AsyncSession,
    org_id: uuid.UUID,
    target_date: date,
) -> AuditVerifyResult:
    start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, 999999, tzinfo=timezone.utc)

    events_result = await session.execute(
        select(AuditEvent)
        .where(
            AuditEvent.organization_id == org_id,
            AuditEvent.occurred_at >= start,
            AuditEvent.occurred_at <= end,
        )
        .order_by(AuditEvent.occurred_at.asc(), AuditEvent.id.asc())
    )
    events = list(events_result.scalars().all())

    row_hashes = [e.row_hash for e in events if e.row_hash]
    computed_root = _compute_merkle_root(row_hashes)

    anchor_result = await session.execute(
        select(AuditAnchor).where(
            AuditAnchor.organization_id == org_id,
            AuditAnchor.anchor_date == target_date,
        )
    )
    anchor = anchor_result.scalars().first()

    expected_root = anchor.merkle_root if anchor else None
    archive_key = anchor.archive_object_key if anchor else None
    is_valid = expected_root is not None and computed_root == expected_root

    return AuditVerifyResult(
        date=target_date,
        event_count=len(events),
        expected_merkle_root=expected_root,
        computed_merkle_root=computed_root,
        valid=is_valid,
        archive_object_key=archive_key,
    )


def _compute_merkle_root(row_hashes: list[str]) -> str:
    if not row_hashes:
        return hashlib.sha256(b"").hexdigest()
    # Iteratively pair and hash until a single root remains
    level = row_hashes[:]
    while len(level) > 1:
        next_level = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            combined = hashlib.sha256((left + right).encode()).hexdigest()
            next_level.append(combined)
        level = next_level
    return level[0]
