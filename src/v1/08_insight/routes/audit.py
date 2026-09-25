import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Header, Query, status

import services.audit as service
from dependencies import DatabaseSession, OrgId
from schemas.audit import AuditEventResponse, AuditExportRequest, AuditVerifyResult, JobResponse
from schemas.common import PageResponse

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=PageResponse[AuditEventResponse])
async def search_audit_events(
    session: DatabaseSession,
    org_id: OrgId,
    subject_type: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    actor_id: Optional[uuid.UUID] = Query(None),
    category: Optional[str] = Query(None),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    sort: Optional[str] = Query(None),
) -> PageResponse[AuditEventResponse]:
    """Search the audit trail."""
    return await service.search_audit_events(
        session, org_id, subject_type, subject_id, actor_id,
        category, from_, to, event_type, limit, cursor,
    )


@router.post("/exports", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def export_audit_events(
    payload: AuditExportRequest,
    session: DatabaseSession,
    org_id: OrgId,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> JobResponse:
    """Export audit events asynchronously."""
    return await service.export_audit_events(session, org_id, payload, idempotency_key)


@router.get("/verify", response_model=AuditVerifyResult)
async def verify_audit_integrity(
    session: DatabaseSession,
    org_id: OrgId,
    date: date = Query(...),
) -> AuditVerifyResult:
    """Verify audit integrity for a day."""
    return await service.verify_audit_integrity(session, org_id, date)
