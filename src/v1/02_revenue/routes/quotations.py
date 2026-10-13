import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status

from dependencies import Authorization, CurrentActor, DatabaseSession, Documents, OrgId, require_permission
from schemas.quotation import (
    QuotationEmailCreate,
    QuotationEmailDraft,
    QuotationEmailSent,
    QuotationChangeRequest,
    QuotationEventResponse,
    QuotationItemsReplace,
    QuotationReject,
    QuotationResponse,
    QuotationValidityUpdate,
    QuotationWithdrawal,
)
from services import notifications, quotation_email_service, quotation_events
from services.documents_client import SubjectRef
from services.quotation_service import QuotationService, get_quote_in_org

router = APIRouter(prefix="/quotations", tags=["quotations"])

CAN_READ = Depends(require_permission("revenue.opportunity.read"))
CAN_WRITE = Depends(require_permission("revenue.opportunity.write"))
CAN_APPROVE = Depends(require_permission("revenue.quotation.approve"))


@router.get(
    "/{quotation_id}", response_model=QuotationResponse,
    dependencies=[CAN_READ],
)
async def get_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> QuotationResponse:
    """Get a quotation revision details."""
    quotation = await QuotationService.get_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
    )
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.put(
    "/{quotation_id}/items", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def replace_quotation_items(
    quotation_id: uuid.UUID,
    payload: QuotationItemsReplace,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Replace line items on a draft quotation and recalculate totals."""
    quotation = await QuotationService.replace_quotation_items(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/submit", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def submit_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Submit quotation for internal review and discount approval."""
    quotation = await QuotationService.submit_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/approve",
    response_model=QuotationResponse,
    dependencies=[CAN_APPROVE],
)
async def approve_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Approve a quotation held for its discount, so it can be sent."""
    quotation = await QuotationService.approve_quotation(
        session=session, quotation_id=quotation_id, org_id=org_id, if_match=if_match, actor_user_id=actor.user_id
    )
    await session.commit()
    await notifications.quotation_approved(session, actor, quotation)
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/send", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def send_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Send approved quotation to the client and freeze revision."""
    quotation = await QuotationService.send_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/revise", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def revise_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    authorization: Authorization,
    documents: Documents,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Create revision N+1 of this quotation and supersede the current one; its documents carry over."""
    quotation = await QuotationService.revise_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        actor_user_id=actor.user_id,
    )
    # Before the commit: if documents can't be reached the revision isn't created, rather
    # than created without its files.
    await documents.copy_links(
        authorization,
        org_id,
        source=SubjectRef("revenue.quotation", quotation_id),
        target=SubjectRef("revenue.quotation", quotation.id),
        target_label=f"{quotation.quote_no} rev {quotation.revision_no}",
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/accept", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def accept_quotation(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> QuotationResponse:
    """Record client acceptance and advance opportunity to won."""
    quotation = await QuotationService.accept_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    await notifications.deal_won(session, actor, quotation)
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/reject", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def reject_quotation(
    quotation_id: uuid.UUID,
    payload: QuotationReject,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Record client rejection with reason and negotiation notes."""
    quotation = await QuotationService.reject_quotation(
        session=session,
        quotation_id=quotation_id,
        org_id=org_id,
        payload=payload,
        if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/change-requests", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def request_quotation_changes(
    quotation_id: uuid.UUID,
    payload: QuotationChangeRequest,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Record that the customer asked for changes to a sent quotation (what they asked, in `note`)."""
    quotation = await QuotationService.request_changes(
        session=session, quotation_id=quotation_id, org_id=org_id, payload=payload, if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.post(
    "/{quotation_id}/withdrawal", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def withdraw_quotation(
    quotation_id: uuid.UUID,
    payload: QuotationWithdrawal,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Take a quotation back before the customer has answered it, with the reason."""
    quotation = await QuotationService.withdraw_quotation(
        session=session, quotation_id=quotation_id, org_id=org_id, payload=payload, if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.patch(
    "/{quotation_id}/validity", response_model=QuotationResponse,
    dependencies=[CAN_WRITE],
)
async def update_quotation_validity(
    quotation_id: uuid.UUID,
    payload: QuotationValidityUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationResponse:
    """Change how long an open quotation is valid for (today or later); its status stays."""
    quotation = await QuotationService.update_validity(
        session=session, quotation_id=quotation_id, org_id=org_id, payload=payload, if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    return quotation


@router.get(
    "/{quotation_id}/events", response_model=list[QuotationEventResponse],
    dependencies=[CAN_READ],
)
async def list_quotation_events(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
) -> list[QuotationEventResponse]:
    """The quotation's history, oldest first."""
    await get_quote_in_org(session, org_id, quotation_id)
    return await quotation_events.list_events(session, org_id, quotation_id)


@router.get(
    "/{quotation_id}/email-draft", response_model=QuotationEmailDraft,
    dependencies=[CAN_READ],
)
async def get_quotation_email_draft(
    quotation_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
) -> QuotationEmailDraft:
    """What the send-by-email form starts from: the sender, the customer's contacts, a subject and message."""
    return await quotation_email_service.build_draft(session, org_id, actor, quotation_id)


@router.post(
    "/{quotation_id}/emails", response_model=QuotationEmailSent, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def email_quotation(
    quotation_id: uuid.UUID,
    payload: QuotationEmailCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    authorization: Authorization,
    documents: Documents,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> QuotationEmailSent:
    """
    Email the quotation and the files chosen from it to the customer. A draft or approved
    quotation is marked sent too (If-Match required); nothing changes unless the mail left.
    """
    result = await quotation_email_service.send(
        session, org_id, actor, documents, authorization, quotation_id, payload, if_match
    )
    await session.commit()
    response.headers["ETag"] = f'"{result.quotation.version}"'
    return result
