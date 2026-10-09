"""How the organization runs billing (finance_settings): one resource per organization."""

from typing import Optional

from fastapi import APIRouter, Depends, Header, Response

from dependencies import DatabaseSession, OrgId, UserId, require_permission
import permissions
from schemas.tax import FinanceSettingsResponse, FinanceSettingsUpdate
from services.tax_config_service import TaxConfigService

router = APIRouter(prefix="/finance-settings", tags=["tax"])

CAN_READ = Depends(require_permission(permissions.TAX_READ))
CAN_MANAGE = Depends(require_permission(permissions.TAX_MANAGE))


@router.get("", response_model=FinanceSettingsResponse, dependencies=[CAN_READ])
async def get_finance_settings(session: DatabaseSession, org_id: OrgId, response: Response) -> FinanceSettingsResponse:
    """The organization's settings; every one at its default until changed (version 0)."""
    settings = await TaxConfigService.get_settings(session, org_id)
    response.headers["ETag"] = f'"{settings.version}"'
    return settings


@router.patch("", response_model=FinanceSettingsResponse, dependencies=[CAN_MANAGE])
async def update_finance_settings(
    payload: FinanceSettingsUpdate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
    response: Response,
    if_match: Optional[str] = Header(None, alias="If-Match"),
) -> FinanceSettingsResponse:
    settings = await TaxConfigService.update_settings(session, org_id, user_id, payload, if_match)
    await session.commit()
    response.headers["ETag"] = f'"{settings.version}"'
    return settings
