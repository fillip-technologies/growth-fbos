import re
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    password: str
    organization_code: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Password cannot be empty")
        return value


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mfa_required: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    mfa_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None


class MfaVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mfa_token: str
    code: str
    remember_device: Optional[bool] = False

    @field_validator("code")
    @classmethod
    def validate_totp_code(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"^\d{6}$", cleaned):
            raise ValueError("Code must be a 6-digit numeric TOTP code")
        return cleaned


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: Optional[str] = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    refresh_token: Optional[str] = None


class Me(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    email: str
    name: str
    phone: Optional[str] = None
    user_type: str
    organization_id: uuid.UUID
    roles: list[str]
    permissions: list[str]
    last_login_at: Optional[str] = None
