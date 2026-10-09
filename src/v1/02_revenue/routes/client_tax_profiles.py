"""A customer's tax profile: registration type, place of supply, TDS section and certificates."""

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, Header, Response

from dependencies import DatabaseSession, OrgId, UserId, require_permission
import permissions
from schemas.tax import ClientTaxProfileResponse, ClientTaxProfileUpdate
from services.tax_config_service import TaxConfigService

router = APIRouter(prefix="/clients", tags=["clients"])

CAN_READ = Depends(require_permission(permissions.CLIENT_READ))
CAN_WRITE = Depends(require_permission(permissions.CLIENT_WRITE))


@router.get("/{client_id}/tax-profile", response_model=ClientTaxProfileResponse, dependencies=[CAN_READ])
async def get_client_tax_profile(
    client_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, response: Response
) -> ClientTaxProfileResponse:
    """The saved profile (version 0 when none) and what billing will actually use for this customer."""
    profile = await TaxConfigService.get_client_profile(session, org_id, client_id)
    await session.commit()
    response.headers["ETag"] = f'"{profile.version}"'
    return profile


@router.put("/{client_id}/tax-profile", response_model=ClientTaxProfileResponse, dependencies=[CAN_WRITE])
async def put_client_tax_profile(
    client_id: uuid.UUID,
    payload: ClientTaxProfileUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> ClientTaxProfileResponse:
    profile = await TaxConfigService.put_client_profile(session, org_id, user_id, client_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{profile.version}"'
    return profile
