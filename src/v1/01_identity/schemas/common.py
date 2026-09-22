from typing import Generic, Optional, TypeVar
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int = 25


class PaginatedResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="ignore")

    data: list[T]
    page: PageInfo
