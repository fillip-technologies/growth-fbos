import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

from dependencies import Authorization, CurrentActor, DatabaseSession, Documents, OrgId, require_permission
from schemas.common import PageResponse
from schemas.contract import ContractCreate, ContractEmailSent, ContractResponse, SignedDocumentSet
from schemas.customer_email import CustomerEmailCreate, CustomerEmailDraft
from services import contract_email_service
from services.contract_service import ContractService

router = APIRouter(prefix="/contracts", tags=["contracts"])

CAN_READ = Depends(require_permission("revenue.contract.read"))
CAN_WRITE = Depends(require_permission("revenue.contract.write"))


@router.get(
    "",
    response_model=PageResponse[ContractResponse],
    dependencies=[CAN_READ],
)
async def list_contracts(
    session: DatabaseSession,
    org_id: OrgId,
    client_id: Optional[uuid.UUID] = Query(None, description="Filter by client id"),
    opportunity_id: Optional[uuid.UUID] = Query(None, description="Filter by opportunity id"),
    status: Optional[str] = Query(None, description="Filter by status: pending_signature, active, ..."),
    limit: int = Query(25, ge=1, le=100, description="Page limit (1-100)"),
    cursor: Optional[str] = Query(None, description="Opaque cursor token"),
) -> PageResponse[ContractResponse]:
    """List contracts, e.g. one client's or the one made from an opportunity."""
    return await ContractService.list_contracts(
        session=session,
        org_id=org_id,
        client_id=client_id,
        opportunity_id=opportunity_id,
        status=status,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "", response_model=ContractResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def create_contract(
    payload: ContractCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ContractResponse:
    """Create a contract from an accepted quotation with 100% payment terms validation."""
    contract = await ContractService.create_contract(
        session=session,
        org_id=org_id,
        payload=payload,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{contract.version}"'
    response.headers["Location"] = f"/api/revenue/v1/contracts/{contract.id}"
    return contract


@router.get(
    "/{contract_id}", response_model=ContractResponse,
    dependencies=[CAN_READ],
)
async def get_contract(
    contract_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
) -> ContractResponse:
    """Get contract details with payment schedule terms."""
    contract = await ContractService.get_contract(
        session=session,
        contract_id=contract_id,
        org_id=org_id,
    )
    response.headers["ETag"] = f'"{contract.version}"'
    return contract


@router.put(
    "/{contract_id}/signed-document", response_model=ContractResponse,
    dependencies=[CAN_WRITE],
)
async def set_signed_document(
    contract_id: uuid.UUID,
    payload: SignedDocumentSet,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    authorization: Authorization,
    documents: Documents,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ContractResponse:
    """
    Mark an uploaded document as the signed copy. Upload it to the documents service first,
    linked to `revenue.contract` / this id; activation requires it.
    """
    contract = await ContractService.set_signed_document(
        session=session,
        contract_id=contract_id,
        org_id=org_id,
        document_id=payload.document_id,
        if_match=if_match,
        documents=documents,
        authorization=authorization,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{contract.version}"'
    return contract


@router.post(
    "/{contract_id}/activate", response_model=ContractResponse,
    dependencies=[CAN_WRITE],
)
async def activate_contract(
    contract_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ContractResponse:
    """Activate a contract whose signed copy is attached, starting delivery and billing."""
    contract = await ContractService.activate_contract(
        session=session,
        contract_id=contract_id,
        org_id=org_id,
        if_match=if_match,
        actor_user_id=actor.user_id,
    )
    await session.commit()
    response.headers["ETag"] = f'"{contract.version}"'
    return contract


@router.get(
    "/{contract_id}/email-draft", response_model=CustomerEmailDraft,
    dependencies=[CAN_READ],
)
async def get_contract_email_draft(
    contract_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
) -> CustomerEmailDraft:
    """What the send-by-email form starts from: the sender, the customer's contacts, a subject and message."""
    return await contract_email_service.build_draft(session, org_id, actor, contract_id)


@router.post(
    "/{contract_id}/emails", response_model=ContractEmailSent, status_code=status.HTTP_201_CREATED,
    dependencies=[CAN_WRITE],
)
async def email_contract(
    contract_id: uuid.UUID,
    payload: CustomerEmailCreate,
    session: DatabaseSession,
    org_id: OrgId,
    actor: CurrentActor,
    authorization: Authorization,
    documents: Documents,
) -> ContractEmailSent:
    """Email the contract and the files chosen from it (e.g. for signing) to the customer. Its status stays."""
    result = await contract_email_service.send(session, org_id, actor, documents, authorization, contract_id, payload)
    await session.commit()
    return result
