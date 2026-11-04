from typing import Literal, Optional
import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from dependencies import DatabaseSession, OrgId, UserId, require_permission
import permissions
from schemas.common import PageResponse
from schemas.finance import InvestmentCreate, InvestmentResponse, InvestmentUpdate
from services import investment_service

router = APIRouter(prefix="/investments", tags=["investments"])

CAN_READ = Depends(require_permission(permissions.INVESTMENT_READ))
CAN_WRITE = Depends(require_permission(permissions.INVESTMENT_WRITE))


@router.get("", response_model=PageResponse[InvestmentResponse], dependencies=[CAN_READ])
async def list_investments(
    session: DatabaseSession,
    org_id: OrgId,
    status_filter: Optional[Literal["active", "matured", "closed"]] = Query(None, alias="status"),
    investment_type: Optional[str] = None,
    investee_organization_id: Optional[uuid.UUID] = None,
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = None,
) -> PageResponse[InvestmentResponse]:
    rows, page = await investment_service.list_investments(
        session,
        org_id,
        limit=limit,
        cursor=cursor,
        status=status_filter,
        investment_type=investment_type,
        investee_organization_id=investee_organization_id,
    )
    return PageResponse(data=rows, page=page)


@router.post("", response_model=InvestmentResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_WRITE])
async def create_investment(
    body: InvestmentCreate, session: DatabaseSession, org_id: OrgId, user_id: UserId
) -> InvestmentResponse:
    return await investment_service.create_investment(session, org_id, user_id, body)


@router.get("/{investment_id}", response_model=InvestmentResponse, dependencies=[CAN_READ])
async def get_investment(investment_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> InvestmentResponse:
    return await investment_service.read_investment(session, org_id, investment_id)


@router.patch("/{investment_id}", response_model=InvestmentResponse, dependencies=[CAN_WRITE])
async def update_investment(
    investment_id: uuid.UUID, body: InvestmentUpdate, session: DatabaseSession, org_id: OrgId
) -> InvestmentResponse:
    return await investment_service.update_investment(session, org_id, investment_id, body)


@router.delete("/{investment_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[CAN_WRITE])
async def delete_investment(investment_id: uuid.UUID, session: DatabaseSession, org_id: OrgId) -> Response:
    await investment_service.delete_investment(session, org_id, investment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
