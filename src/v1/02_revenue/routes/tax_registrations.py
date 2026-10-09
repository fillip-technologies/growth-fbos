"""The organization's own tax registrations (a GSTIN per state): who the supplier is on its documents."""

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, Header, Response, status

from dependencies import DatabaseSession, OrgId, require_permission
import permissions
from schemas.tax import TaxRegistrationCreate, TaxRegistrationResponse, TaxRegistrationUpdate
from services.tax_config_service import TaxConfigService

router = APIRouter(prefix="/tax-registrations", tags=["tax"])

CAN_READ = Depends(require_permission(permissions.TAX_READ))
CAN_MANAGE = Depends(require_permission(permissions.TAX_MANAGE))


@router.get("", response_model=List[TaxRegistrationResponse], dependencies=[CAN_READ])
async def list_registrations(session: DatabaseSession, org_id: OrgId) -> List[TaxRegistrationResponse]:
    return await TaxConfigService.list_registrations(session, org_id)


@router.post("", response_model=TaxRegistrationResponse, status_code=status.HTTP_201_CREATED, dependencies=[CAN_MANAGE])
async def create_registration(
    payload: TaxRegistrationCreate, session: DatabaseSession, org_id: OrgId, response: Response
) -> TaxRegistrationResponse:
    """Add a registration. The number is checked by the regime's validator and its jurisdiction derived from it."""
    registration = await TaxConfigService.create_registration(session, org_id, payload)
    await session.commit()
    response.headers["ETag"] = f'"{registration.version}"'
    response.headers["Location"] = f"/api/revenue/v1/tax-registrations/{registration.id}"
    return registration


@router.get("/{registration_id}", response_model=TaxRegistrationResponse, dependencies=[CAN_READ])
async def get_registration(
    registration_id: uuid.UUID, session: DatabaseSession, org_id: OrgId, response: Response
) -> TaxRegistrationResponse:
    registration = TaxRegistrationResponse.model_validate(
        await TaxConfigService.get_registration(session, org_id, registration_id)
    )
    response.headers["ETag"] = f'"{registration.version}"'
    return registration


@router.patch("/{registration_id}", response_model=TaxRegistrationResponse, dependencies=[CAN_MANAGE])
async def update_registration(
    registration_id: uuid.UUID,
    payload: TaxRegistrationUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> TaxRegistrationResponse:
    """Edit names, address, LUT, default flag or validity. Issued documents keep their own copy."""
    registration = await TaxConfigService.update_registration(session, org_id, registration_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{registration.version}"'
    return registration
