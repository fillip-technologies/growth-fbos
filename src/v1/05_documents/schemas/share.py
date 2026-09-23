from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version_no: Optional[int] = None
    expires_at: str
    password: Optional[str] = None
    max_downloads: Optional[int] = None


class ShareResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    url: str
    expires_at: str
    max_downloads: Optional[int] = None
    download_count: int = 0
    password_protected: bool = False
    created_at: str
