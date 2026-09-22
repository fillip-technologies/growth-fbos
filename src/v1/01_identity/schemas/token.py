from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict


class Token(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str
    email: Optional[str] = None
    org_id: Optional[str] = None
    family_id: Optional[str] = None
    token_type: Optional[str] = None
