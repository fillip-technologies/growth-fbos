import uuid
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import Money
from schemas.opportunity import VerticalRef


class OfferingCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=100, description="SKU / Unique offering code")
    name: str = Field(..., min_length=1, max_length=255, description="Display name of service")
    vertical_id: uuid.UUID
    sac_code: str = Field(..., max_length=20, description="Services Accounting Code for GST")
    tax_category_code: Optional[str] = Field(None, max_length=100, description="Tax category from the tax configuration")
    gst_rate: Optional[float] = Field(None, ge=0, le=100, description="Legacy: a GST percentage, used when no tax category is given")
    unit: Literal["project", "hour", "month", "unit"] = "project"
    billing_model: Literal["one_time", "recurring", "milestone", "time_and_material"] = "one_time"
    list_price: Money
    default_work_template_code: Optional[str] = None

    @model_validator(mode="after")
    def taxed_somehow(self) -> "OfferingCreate":
        if self.tax_category_code is None and self.gst_rate is None:
            raise ValueError("give a tax_category_code (or, for older clients, a gst_rate)")
        return self


class OfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    vertical: Optional[VerticalRef] = None
    sac_code: str
    tax_category_code: Optional[str] = None
    # The category's rate today (or the legacy percentage); None when neither is set.
    gst_rate: Optional[float] = None
    unit: Literal["project", "hour", "month", "unit"]
    billing_model: str
    list_price: Money
    default_work_template_code: Optional[str] = None
    status: Literal["active", "retired"]
