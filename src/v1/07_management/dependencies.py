from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db

DatabaseSession = Annotated[AsyncSession, Depends(get_db)]

__all__ = ["DatabaseSession", "get_db"]
