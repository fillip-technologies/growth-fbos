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
    user_type: Optional[str] = None
    client_id: Optional[str] = None
    family_id: Optional[str] = None
    token_type: Optional[str] = None

    @property
    def user_id(self) -> uuid.UUID:
        return uuid.UUID(self.sub)

    @property
    def organization_id(self) -> uuid.UUID:
        return uuid.UUID(self.org_id) if self.org_id else uuid.UUID("00000000-0000-0000-0000-000000000000")

    @property
    def client_uuid(self) -> Optional[uuid.UUID]:
        return uuid.UUID(self.client_id) if self.client_id else None

    @property
    def is_platform_admin(self) -> bool:
        return self.user_type == "platform_admin"

    @property
    def is_client_admin(self) -> bool:
        return self.user_type == "client_admin"
