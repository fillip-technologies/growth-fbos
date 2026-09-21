from pydantic import BaseModel
from uuid import UUID


class UserCreate(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    is_active: bool
