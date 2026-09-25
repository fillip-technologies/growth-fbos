import uuid
from typing import Annotated, Optional

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db_session

DEFAULT_ORG_ID = uuid.UUID("0191f3a2-0011-7011-8077-0000001b2aa9")
DEFAULT_USER_ID = uuid.UUID("0191f3a2-0015-7015-8093-000000218f0d")


async def get_organization_id(
    x_fbos_org_id: Optional[str] = Header(None, alias="X-FBOS-Org-Id"),
) -> uuid.UUID:
    if x_fbos_org_id:
        try:
            return uuid.UUID(x_fbos_org_id)
        except ValueError:
            pass
    return DEFAULT_ORG_ID


async def get_current_user_id(
    x_fbos_user_id: Optional[str] = Header(None, alias="X-FBOS-User-Id"),
) -> uuid.UUID:
    if x_fbos_user_id:
        try:
            return uuid.UUID(x_fbos_user_id)
        except ValueError:
            pass
    return DEFAULT_USER_ID


DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
OrgId = Annotated[uuid.UUID, Depends(get_organization_id)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
