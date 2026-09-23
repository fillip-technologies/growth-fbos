from typing import Optional
import uuid

from fastapi import APIRouter, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dependencies import (
    DatabaseSession,
    OrgId,
    UserId,
    get_client_ip,
)
from schemas.document import DownloadUrlResponse
from services.share_service import share_service

router = APIRouter(tags=["shares"])


@router.delete(
    "/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a share link",
    description="Revokes an external document share link so it can no longer be accessed.",
)
async def revoke_share(
    share_id: uuid.UUID,
    session: DatabaseSession,
    org_id: OrgId,
    user_id: UserId,
) -> Response:
    await share_service.revoke_share(
        session=session,
        share_id=share_id,
        org_id=org_id,
        user_id=user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/public/shares/{token}",
    response_model=DownloadUrlResponse,
    status_code=status.HTTP_200_OK,
    summary="Open a shared document (external)",
    description="For people outside FBOS. Password-protected shares require the X-Share-Password header.",
)
async def open_share(
    token: str,
    request: Request,
    session: DatabaseSession,
    x_share_password: Optional[str] = Header(None, alias="X-Share-Password"),
) -> DownloadUrlResponse:
    client_ip = get_client_ip(request)
    return await share_service.open_share(
        session=session,
        token=token,
        password=x_share_password,
        client_ip=client_ip,
    )
