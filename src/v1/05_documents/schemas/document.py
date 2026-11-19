from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from schemas.common import CategoryRef, PageInfo, SubjectRef, SubjectRefInput, UserRef


class DocumentVersionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    version_no: int
    file_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    scan_status: str = "pending"
    status: str = "draft"
    uploaded_by: UserRef
    uploaded_at: str
    change_note: Optional[str] = None


class DocumentLinkResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: SubjectRef
    link_role: str
    linked_at: str


class DocumentLinkCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: SubjectRefInput
    link_role: str = "attachment"


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    code: str
    title: str
    category: CategoryRef
    classification: str = "internal"
    status: str = "active"
    locked: bool = False
    legal_hold: bool = False
    current_version: Optional[DocumentVersionResponse] = None
    links: list[DocumentLinkResponse] = Field(default_factory=list)
    owner: UserRef
    created_at: str


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[DocumentResponse] = Field(default_factory=list)
    page: PageInfo = Field(default_factory=PageInfo)


class DownloadUrlResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    expires_at: str
    file_name: str


class LinkCopyCreate(BaseModel):
    """Internal: link every document of `source` to `target` too."""

    model_config = ConfigDict(extra="forbid")

    source: SubjectRefInput
    target: SubjectRefInput
    target_label: Optional[str] = Field(None, max_length=500)


class StoredFileCreate(BaseModel):
    """
    Internal: a file another service generated (a proposal or quotation PDF), stored and linked
    to its record. With `document_id`, a new version of that document instead of a new one.
    """

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(..., min_length=1, max_length=255)
    mime_type: str = Field(..., min_length=1, max_length=100)
    content_base64: str = Field(..., min_length=1)
    category_code: str = Field(..., min_length=1, max_length=100)
    title: Optional[str] = Field(None, max_length=500)
    subject: SubjectRefInput
    link_role: str = Field("attachment", max_length=50)
    document_id: Optional[uuid.UUID] = None
    change_note: Optional[str] = Field(None, max_length=500)


class LinkCopyResult(BaseModel):
    copied: int
