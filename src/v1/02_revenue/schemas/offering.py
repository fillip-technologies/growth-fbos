import uuid
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money


class OfferingCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, description="SKU / Unique offering code")
    name: str = Field(..., min_length=1, max_length=255, description="Display name of service")
    vertical_id: Optional[uuid.UUID] = None
    sac_code: Optional[str] = Field(None, max_length=20, description="Services Accounting Code for GST")
    gst_rate: Optional[float] = Field(18.0, ge=0, le=100, description="Applicable GST percentage")
    unit: Optional[str] = Field("project", max_length=50, description="Unit of measurement: hour, month, project")
    billing_model: Literal["one_time", "recurring", "milestone", "time_and_material"] = "one_time"
    list_price: Money
    default_work_template_code: Optional[str] = None


class OfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    vertical_id: Optional[uuid.UUID] = None
    sac_code: Optional[str] = None
    gst_rate: Optional[float] = 18.0
    unit: Optional[str] = "project"
    billing_model: str
    list_price: Optional[Money] = None
    default_work_template_code: Optional[str] = None
    status: str
    version: int = 1
