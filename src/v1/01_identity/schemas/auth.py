import re
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from schemas.user import HomeUnitRef


class OrganizationRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    code: str
    name: str


class ScopeUnitRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str


class ScopeVerticalRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str


class MeRoleItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role_code: str
    scope_unit: Optional[ScopeUnitRef] = None
    scope_vertical: Optional[ScopeVerticalRef] = None
    self_only: bool = False


class Me(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    name: str
    email: str
    organization: OrganizationRef
    home_unit: Optional[HomeUnitRef] = None
    roles: list[MeRoleItem]
    permissions: list[str]
    mfa_enabled: bool
    timezone: Optional[str] = None
    locale: Optional[str] = None


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

    status: str  # "ok" or "mfa_required"
    mfa_token: Optional[str] = None
    mfa_methods: Optional[list[str]] = None
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    expires_in: Optional[int] = None
    refresh_token: Optional[str] = None
    user: Optional[Me] = None


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
    user: Optional[Me] = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    refresh_token: Optional[str] = None


class PasswordForgotRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    organization_code: Optional[str] = None


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token: str
    new_password: str


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token: str
    password: str


class MfaEnrollmentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    otpauth_uri: str
    qr_png_data_url: str
    expires_at: str


class MfaEnrollConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str


class RecoveryCodesResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    codes: list[str]


class ApiClientTokenRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    grant_type: str = "client_credentials"
    client_id: str
    client_secret: str
    scope: Optional[str] = None


class ClientTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 900
    scope: Optional[str] = None


class JwkKey(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kty: str = "RSA"
    kid: str
    use: str = "sig"
    alg: str = "RS256"
    n: str
    e: str


class JwksResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keys: list[JwkKey]
