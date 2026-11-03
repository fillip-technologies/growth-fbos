"""Records matching a few typed words, across everything revenue keeps (the console's one search box)."""
import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel

from schemas.common import Money

SearchType = Literal["customer", "lead", "opportunity", "quotation", "contract", "invoice", "payment"]


class SearchHit(BaseModel):
    type: SearchType
    id: uuid.UUID
    title: str  # what the record is called: a name, else its number
    subtitle: Optional[str] = None  # its number, customer or contact, whichever the title isn't
    status: Optional[str] = None
    amount: Optional[Money] = None


class SearchResponse(BaseModel):
    q: str
    data: List[SearchHit]
    # Kinds of record the caller may not read, so weren't searched.
    not_searched: List[SearchType] = []
