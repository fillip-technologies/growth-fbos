import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status

from dependencies import DatabaseSession, OrgId, require_permission
from schemas.common import PageResponse
from schemas.contract import ContractCreate, ContractResponse
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
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ContractResponse:
    """Create a contract from an accepted quotation with 100% payment terms validation."""
    contract = await ContractService.create_contract(
        session=session,
        org_id=org_id,
        payload=payload,
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


@router.post(
    "/{contract_id}/activate", response_model=ContractResponse,
    dependencies=[CAN_WRITE],
)
async def activate_contract(
    contract_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> ContractResponse:
    """Activate a signed contract, starting delivery and billing."""
    contract = await ContractService.activate_contract(
        session=session,
        contract_id=contract_id,
        org_id=org_id,
        if_match=if_match,
    )
    await session.commit()
    response.headers["ETag"] = f'"{contract.version}"'
    return contract
