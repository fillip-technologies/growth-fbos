from fastapi import APIRouter, Depends, Response, status

import services.notification_service as service
from dependencies import DatabaseSession, verify_internal_caller
from schemas.notifications import NotificationCreate, NotificationCreated

# Service-to-service endpoints. Mounted outside the public /api/communication/v1 prefix,
# so neither the gateway nor the consoles' proxies expose them to browsers.
router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(verify_internal_caller)])


@router.post("/notifications", response_model=NotificationCreated, status_code=status.HTTP_201_CREATED)
async def create_notification(
    payload: NotificationCreate,
    session: DatabaseSession,
    response: Response,
) -> NotificationCreated:
    """Raise a notification: one inbox item for each recipient."""
    result, created = await service.create_notification(session, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
        return result
    await session.commit()
    return result
