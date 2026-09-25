from fastapi import APIRouter, status

import services.preferences_service as service
from dependencies import DatabaseSession, OrgId, UserId
from schemas.preferences import DeviceTokenCreate, PreferencesReplace

router = APIRouter(tags=["preferences"])


@router.get("/preferences", response_model=PreferencesReplace)
async def get_preferences(
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
) -> PreferencesReplace:
    """Get my notification preferences."""
    return await service.get_preferences(session, org_id, user_id)


@router.put("/preferences", response_model=PreferencesReplace)
async def replace_preferences(
    payload: PreferencesReplace,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
) -> PreferencesReplace:
    """Replace my notification preferences."""
    result = await service.replace_preferences(session, org_id, user_id, payload)
    await session.commit()
    return result


@router.post("/device-tokens", status_code=status.HTTP_204_NO_CONTENT)
async def register_device_token(
    payload: DeviceTokenCreate,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
) -> None:
    """Register a push device token."""
    await service.register_device_token(session, org_id, user_id, payload)
    await session.commit()
