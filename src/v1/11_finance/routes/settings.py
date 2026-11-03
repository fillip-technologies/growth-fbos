from fastapi import APIRouter, Depends

from dependencies import DatabaseSession, OrgId, UserId, require_permission
import permissions
from schemas.finance import SettingsResponse, SettingsUpdate
from services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse, dependencies=[Depends(require_permission(permissions.EXPENSE_READ))])
async def get_finance_settings(session: DatabaseSession, org_id: OrgId) -> SettingsResponse:
    return await settings_service.read(session, org_id)


@router.patch("", response_model=SettingsResponse, dependencies=[Depends(require_permission(permissions.SETUP_MANAGE))])
async def update_finance_settings(
    body: SettingsUpdate, session: DatabaseSession, org_id: OrgId, user_id: UserId
) -> SettingsResponse:
    """A new threshold applies to expenses recorded or changed from now on."""
    return await settings_service.update(session, org_id, user_id, body)
