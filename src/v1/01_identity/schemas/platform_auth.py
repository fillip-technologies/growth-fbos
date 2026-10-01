from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class PlatformLoginRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Password cannot be empty")
        return value


class PlatformLoginResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    # Only for non-browser clients; browsers get it as the HttpOnly `fbos_prt` cookie.
    refresh_token: Optional[str] = None


class PlatformRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    refresh_token: Optional[str] = None
