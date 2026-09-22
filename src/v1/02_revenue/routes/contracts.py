import uuid
from typing import Optional

from fastapi import APIRouter, Header, Response, status

from dependencies import DatabaseSession, OrgId
from schemas.contract import ContractCreate, ContractResponse
from services.contract_service import ContractService

router = APIRouter(prefix="/contracts", tags=["contracts"])


@router.post("", response_model=ContractResponse, status_code=status.HTTP_201_CREATED)
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


@router.get("/{contract_id}", response_model=ContractResponse)
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


@router.post("/{contract_id}/activate", response_model=ContractResponse)
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
