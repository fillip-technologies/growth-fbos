import uuid
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.common import Money
from schemas.opportunity import VerticalRef


class OfferingCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, description="SKU / Unique offering code")
    name: str = Field(..., min_length=1, max_length=255, description="Display name of service")
    vertical_id: uuid.UUID
    sac_code: str = Field(..., max_length=20, description="Services Accounting Code for GST")
    gst_rate: float = Field(..., ge=0, le=100, description="Applicable GST percentage")
    unit: Literal["project", "hour", "month", "unit"] = "project"
    billing_model: Literal["one_time", "recurring", "milestone", "time_and_material"] = "one_time"
    list_price: Money
    default_work_template_code: Optional[str] = None


class OfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    vertical: VerticalRef
    sac_code: str
    gst_rate: float
    unit: Literal["project", "hour", "month", "unit"]
    billing_model: str
    list_price: Money
    default_work_template_code: Optional[str] = None
    status: Literal["active", "retired"]
