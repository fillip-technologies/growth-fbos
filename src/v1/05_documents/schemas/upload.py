from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import SubjectRefInput


class UploadLinkInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: SubjectRefInput
    link_role: str = "attachment"


class UploadInit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    category_code: str
    title: Optional[str] = None
    document_id: Optional[uuid.UUID] = None
    link: Optional[UploadLinkInput] = None


class UploadInitResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    upload_id: uuid.UUID
    document_id: uuid.UUID
    version_no: int
    upload_url: str
    upload_method: str = "PUT"
    upload_headers: dict[str, str] = Field(default_factory=dict)
    expires_at: str
