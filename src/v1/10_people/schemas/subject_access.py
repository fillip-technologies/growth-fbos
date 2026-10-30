from typing import Optional
import uuid

from pydantic import BaseModel


class SubjectAccessResponse(BaseModel):
    """The caller may act on this record; documents shows `label` next to the attached file."""

    type: str
    id: uuid.UUID
    organization_id: uuid.UUID
    label: Optional[str] = None
