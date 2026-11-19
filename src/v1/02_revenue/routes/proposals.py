import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status

from dependencies import Authorization, CurrentActor, DatabaseSession, Documents, OrgId, require_permission
from permissions import OPPORTUNITY_READ, OPPORTUNITY_WRITE
from schemas.common import PageMeta, PageResponse
from schemas.proposal import (
    ProposalCreate,
    ProposalDecision,
    ProposalEmailCreate,
    ProposalEmailDraft,
    ProposalEmailSent,
    ProposalEventResponse,
    ProposalFeedback,
    ProposalRejection,
    ProposalResponse,
    ProposalRevision,
    ProposalUpdate,
)
from schemas.quotation import QuotationResponse
from services import proposal_documents, proposal_service
from services.quotation_service import QuotationService

# Proposals hang off opportunities, and are reached on their own once made.
opportunity_router = APIRouter(prefix="/opportunities", tags=["proposals"])
router = APIRouter(prefix="/proposals", tags=["proposals"])

CAN_READ = Depends(require_permission(OPPORTUNITY_READ))
CAN_WRITE = Depends(require_permission(OPPORTUNITY_WRITE))


def _etag(response: Response, proposal: ProposalResponse) -> ProposalResponse:
    response.headers["ETag"] = f'"{proposal.version}"'
    return proposal


@opportunity_router.get(
    "/{opportunity_id}/proposals", response_model=PageResponse[ProposalResponse], dependencies=[CAN_READ],
)
async def list_opportunity_proposals(
    opportunity_id: uuid.UUID, session: DatabaseSession, org_id: OrgId,
) -> PageResponse[ProposalResponse]:
    """Every proposal version on the opportunity: newest proposal first, its latest version first."""
    proposals = await proposal_service.list_for_opportunity(session, org_id, opportunity_id)
    return PageResponse(data=proposals, page=PageMeta(has_more=False, limit=len(proposals)))


@opportunity_router.post(
    "/{opportunity_id}/proposals", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_proposal(
    opportunity_id: uuid.UUID,
    payload: ProposalCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
) -> ProposalResponse:
    """
    Start a proposal (version 1, a draft). Its requirements start as those written down on the
    lead's calls. One proposal is open on an opportunity at a time.
    """
    proposal = await proposal_service.create(session, org_id, opportunity_id, payload, actor.user_id)
    await session.commit()
    response.headers["Location"] = f"/api/revenue/v1/proposals/{proposal.id}"
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.get("/{proposal_id}", response_model=ProposalResponse, dependencies=[CAN_READ])
async def get_proposal(
    proposal_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, response: Response,
) -> ProposalResponse:
    proposal = await proposal_service.get_in_org(session, org_id, proposal_id)
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.patch("/{proposal_id}", response_model=ProposalResponse, dependencies=[CAN_WRITE])
async def update_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ProposalResponse:
    """Change a draft: its title, requirements, scope, timeline, terms, or its services (`items` replaces them)."""
    proposal = await proposal_service.update(session, org_id, proposal_id, payload, actor.user_id, if_match)
    await session.commit()
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.get(
    "/{proposal_id}/pdf",
    dependencies=[CAN_READ],
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The proposal as a PDF"}},
)
async def proposal_pdf(
    proposal_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    authorization: Authorization,
    documents: Documents,
) -> Response:
    """
    The PDF: for a draft, a preview marked "Draft" (not stored); once sent, the copy the
    customer got, from documents.
    """
    proposal = await proposal_service.get_in_org(session, org_id, proposal_id)
    if proposal.pdf_document_id and proposal.pdf_version_no:
        content = (await proposal_documents.final_pdf(session, org_id, proposal, documents, authorization)).content
    else:
        content = await proposal_documents.render(session, org_id, proposal, draft=proposal.status == "draft")
    name = proposal_documents.file_name(proposal)
    return Response(
        content=content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'}
    )


@router.post("/{proposal_id}/send", response_model=ProposalResponse, dependencies=[CAN_WRITE])
async def send_proposal(
    proposal_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    authorization: Authorization,
    documents: Documents,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ProposalResponse:
    """Mark a draft sent when it reached the customer another way. Its PDF is stored as for an email."""
    proposal = await proposal_documents.mark_sent(session, org_id, actor, documents, authorization, proposal_id, if_match)
    await session.commit()
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.get("/{proposal_id}/email-draft", response_model=ProposalEmailDraft, dependencies=[CAN_READ])
async def get_proposal_email_draft(
    proposal_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, actor: CurrentActor,
) -> ProposalEmailDraft:
    """What the send-by-email form starts from: the sender, the customer's contacts, a subject and message."""
    return await proposal_documents.build_draft(session, org_id, actor, proposal_id)


@router.post(
    "/{proposal_id}/emails", response_model=ProposalEmailSent, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def email_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalEmailCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    authorization: Authorization,
    documents: Documents,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ProposalEmailSent:
    """
    Email the proposal's PDF, and any files chosen from it, to the customer. A draft is marked
    sent too (If-Match required) and its PDF stored; nothing changes unless the mail left.
    """
    result = await proposal_documents.send(
        session, org_id, actor, documents, authorization, proposal_id, payload, if_match
    )
    await session.commit()
    response.headers["ETag"] = f'"{result.proposal.version}"'
    return result


@router.post("/{proposal_id}/change-requests", response_model=ProposalResponse, dependencies=[CAN_WRITE])
async def record_proposal_feedback(
    proposal_id: uuid.UUID,
    payload: ProposalFeedback,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ProposalResponse:
    """The customer's feedback on a sent proposal: it is under discussion until revised, accepted or rejected."""
    proposal = await proposal_service.request_changes(session, org_id, proposal_id, payload.feedback, actor.user_id, if_match)
    await session.commit()
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.post(
    "/{proposal_id}/revisions", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def revise_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalRevision,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
) -> ProposalResponse:
    """The next version as a draft, with this one's content; this one is replaced by it and kept."""
    proposal = await proposal_service.revise(session, org_id, proposal_id, payload.note, actor.user_id)
    await session.commit()
    response.headers["Location"] = f"/api/revenue/v1/proposals/{proposal.id}"
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.post("/{proposal_id}/accept", response_model=ProposalResponse, dependencies=[CAN_WRITE])
async def accept_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalDecision,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ProposalResponse:
    """The customer accepted it: the quotation is made from it next."""
    proposal = await proposal_service.decide(session, org_id, proposal_id, True, payload.note, actor.user_id, if_match)
    await session.commit()
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.post("/{proposal_id}/reject", response_model=ProposalResponse, dependencies=[CAN_WRITE])
async def reject_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalRejection,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ProposalResponse:
    """The customer turned it down, saying why. It can still be revised into a new version."""
    proposal = await proposal_service.decide(session, org_id, proposal_id, False, payload.reason, actor.user_id, if_match)
    await session.commit()
    return _etag(response, await proposal_service.to_response(session, proposal))


@router.post(
    "/{proposal_id}/quotation", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def quote_proposal(
    proposal_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
) -> QuotationResponse:
    """The quotation for an accepted proposal, as a draft with its services and terms."""
    quotation = await QuotationService.create_from_proposal(session, org_id, proposal_id, actor.user_id)
    await session.commit()
    response.headers["ETag"] = f'"{quotation.version}"'
    response.headers["Location"] = f"/api/revenue/v1/quotations/{quotation.id}"
    return quotation


@router.get("/{proposal_id}/events", response_model=list[ProposalEventResponse], dependencies=[CAN_READ])
async def list_proposal_events(
    proposal_id: uuid.UUID, session: DatabaseSession, org_id: OrgId,
) -> list[ProposalEventResponse]:
    """The proposal's history, oldest first: created, edited, sent and emailed (with what was sent), the customer's answers."""
    return await proposal_service.list_events(session, org_id, proposal_id)
