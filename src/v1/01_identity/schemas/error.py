from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: Optional[str] = None
    issue: str


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    message: str
    status: int
    details: Optional[list[ErrorDetail]] = None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: ErrorBody
