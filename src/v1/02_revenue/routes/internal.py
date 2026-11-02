from datetime import date
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from dependencies import CurrentActor, DatabaseSession, verify_internal_caller
from exceptions import InvalidDateRangeError
from models.invoice import Invoice
from schemas.revenue_feed import RevenueActualListResponse, RevenueActualRow
from schemas.activity import ActivityResponse, InternalActivityCreate
from schemas.subject_access import SubjectAccessResponse
from services.activity_service import log_from_source
from services.subject_access_service import check_subject_access

# What counts as revenue for management, with the same rules as the GST-vs-cash report.
REVENUE_DOC_TYPES = ("tax_invoice", "debit_note", "credit_note")
UNISSUED_STATUSES = ("draft", "pending_approval")

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_caller)])


@router.get(
    "/subject-access/{subject_type}/{subject_id}",
    response_model=SubjectAccessResponse,
    summary="May the caller see / attach documents to this record? (internal)",
    description=(
        "Asked by the documents service with the user's forwarded credentials. 200 when allowed; "
        "404 for an unknown or other-organization record, 403 without the permission, "
        "409 SUBJECT_LOCKED when the record is closed to new files."
    ),
)
async def get_subject_access(
    subject_type: str,
    subject_id: uuid.UUID,
    session: DatabaseSession,
    actor: CurrentActor,
    action: Literal["read", "attach"] = Query("read"),
) -> SubjectAccessResponse:
    return await check_subject_access(session, actor, subject_type, subject_id, action)


@router.post(
    "/activities",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log an activity from another service's record (internal)",
    description=(
        "Delivery logs a finished sales task (a call, an email, a meeting) on the lead, opportunity or "
        "contract it was about. Once per source: the same source again answers 200 with that activity."
    ),
)
async def log_activity_from_source(payload: InternalActivityCreate, session: DatabaseSession, response: Response) -> ActivityResponse:
    activity, created = await log_from_source(session, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
        return activity
    await session.commit()
    return activity


@router.get(
    "/revenue-actuals",
    response_model=RevenueActualListResponse,
    summary="Revenue earned in a window: issued documents net of tax (internal)",
    description=(
        "Read by the management service to mirror revenue against its budgets. One row per issued tax "
        "invoice or debit note (positive) and credit note (negative), dated by its issue date, at its "
        "taxable value: GST collected is owed to the government, not earned. Issued documents never "
        "change, and the document id is stable, so the same window can be asked for again."
    ),
)
async def list_revenue_actuals(
    session: DatabaseSession,
    organization_id: uuid.UUID = Query(...),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
) -> RevenueActualListResponse:
    if to_date < from_date:
        raise InvalidDateRangeError("'to' must be on or after 'from'")
    documents = (
        await session.execute(
            select(Invoice)
            .where(
                Invoice.organization_id == organization_id,
                Invoice.doc_type.in_(REVENUE_DOC_TYPES),
                Invoice.status.not_in(UNISSUED_STATUSES),
                Invoice.issue_date >= from_date,
                Invoice.issue_date <= to_date,
            )
            .order_by(Invoice.issue_date, Invoice.id)
        )
    ).scalars().all()
    return RevenueActualListResponse(
        data=[
            RevenueActualRow(
                id=doc.id,
                doc_type=doc.doc_type,
                occurred_on=doc.issue_date,
                amount=float(-doc.taxable_total if doc.doc_type == "credit_note" else doc.taxable_total),
                currency=doc.currency,
            )
            for doc in documents
        ]
    )
