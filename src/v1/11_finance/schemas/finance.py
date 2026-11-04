"""Request and response bodies for expenses, categories, settings, investments and income."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.common import Currency, MoneyIn, MoneyOut

PaymentStatus = Literal["unpaid", "paid"]
ApprovalStatus = Literal["pending_approval", "approved", "rejected"]
InvestmentType = Literal["fixed_deposit", "mutual_fund", "equity", "bond", "property", "other"]
InvestmentStatus = Literal["active", "matured", "closed"]
IncomeType = Literal["interest", "returns", "capital_gain", "dividend", "rent", "other"]


# --------------------------------------------------------------------------- categories


class CategoryCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, pattern="^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=500)
    is_active: Optional[bool] = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: Optional[str]
    is_builtin: bool
    is_active: bool


class CategoryRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


# --------------------------------------------------------------------------- expenses


class ExpenseCreate(BaseModel):
    category_id: uuid.UUID
    description: str = Field(..., min_length=1, max_length=500)
    vendor_name: Optional[str] = Field(None, max_length=200)
    expense_date: date
    amount: MoneyIn = Field(..., gt=0, description="Before tax")
    tax_amount: MoneyIn = Field(Decimal("0"), ge=0)
    currency: Optional[Currency] = Field(None, description="Defaults to the organization's currency")
    payment_status: PaymentStatus = "unpaid"
    paid_on: Optional[date] = None
    payment_reference: Optional[str] = Field(None, max_length=120)
    work_unit_id: Optional[uuid.UUID] = None
    org_unit_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    notes: Optional[str] = Field(None, max_length=5000)


class ExpenseUpdate(BaseModel):
    """Only the fields sent change; send null to clear an optional link."""

    category_id: Optional[uuid.UUID] = None
    description: Optional[str] = Field(None, min_length=1, max_length=500)
    vendor_name: Optional[str] = Field(None, max_length=200)
    expense_date: Optional[date] = None
    amount: Optional[MoneyIn] = Field(None, gt=0)
    tax_amount: Optional[MoneyIn] = Field(None, ge=0)
    currency: Optional[Currency] = None
    payment_status: Optional[PaymentStatus] = None
    paid_on: Optional[date] = None
    payment_reference: Optional[str] = Field(None, max_length=120)
    work_unit_id: Optional[uuid.UUID] = None
    org_unit_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    notes: Optional[str] = Field(None, max_length=5000)


class ExpenseDecision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _reason_for_rejection(self) -> "ExpenseDecision":
        if self.decision == "reject" and not (self.comment or "").strip():
            raise ValueError("a rejection needs a comment saying why")
        return self


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: CategoryRef
    description: str
    vendor_name: Optional[str]
    expense_date: date
    amount: MoneyOut
    tax_amount: MoneyOut
    total: MoneyOut
    currency: str
    payment_status: str
    paid_on: Optional[date]
    payment_reference: Optional[str]
    work_unit_id: Optional[uuid.UUID]
    org_unit_id: Optional[uuid.UUID]
    document_id: Optional[uuid.UUID]
    approval_status: str
    decided_by: Optional[uuid.UUID]
    decided_at: Optional[datetime]
    decision_comment: Optional[str]
    notes: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- settings


class SettingsResponse(BaseModel):
    expense_approval_threshold: Optional[MoneyOut]
    default_currency: str


class SettingsUpdate(BaseModel):
    """Send `expense_approval_threshold: null` to stop expenses waiting for approval."""

    expense_approval_threshold: Optional[MoneyIn] = Field(None, ge=0)
    default_currency: Optional[Currency] = None


# --------------------------------------------------------------------------- investments


class InvestmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    investment_type: InvestmentType
    institution: Optional[str] = Field(None, max_length=200)
    reference: Optional[str] = Field(None, max_length=120)
    investee_organization_id: Optional[uuid.UUID] = None
    principal: MoneyIn = Field(..., gt=0)
    currency: Optional[Currency] = None
    start_date: date
    maturity_date: Optional[date] = None
    expected_rate_pct: Optional[Decimal] = Field(None, ge=0, le=1000, max_digits=7, decimal_places=3)
    current_value: Optional[MoneyIn] = Field(None, ge=0)
    current_value_on: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=5000)


class InvestmentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    investment_type: Optional[InvestmentType] = None
    institution: Optional[str] = Field(None, max_length=200)
    reference: Optional[str] = Field(None, max_length=120)
    investee_organization_id: Optional[uuid.UUID] = None
    principal: Optional[MoneyIn] = Field(None, gt=0)
    currency: Optional[Currency] = None
    start_date: Optional[date] = None
    maturity_date: Optional[date] = None
    expected_rate_pct: Optional[Decimal] = Field(None, ge=0, le=1000, max_digits=7, decimal_places=3)
    current_value: Optional[MoneyIn] = Field(None, ge=0)
    current_value_on: Optional[date] = None
    status: Optional[InvestmentStatus] = None
    notes: Optional[str] = Field(None, max_length=5000)


class InvestmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    investment_type: str
    institution: Optional[str]
    reference: Optional[str]
    investee_organization_id: Optional[uuid.UUID]
    principal: MoneyOut
    currency: str
    start_date: date
    maturity_date: Optional[date]
    expected_rate_pct: Optional[Decimal]
    current_value: Optional[MoneyOut]
    current_value_on: Optional[date]
    status: str
    notes: Optional[str]
    income_to_date: MoneyOut = Decimal("0")
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- income


class IncomeCreate(BaseModel):
    income_type: IncomeType
    amount: MoneyIn = Field(..., gt=0, description="Gross, before tax deducted at source")
    tax_deducted: MoneyIn = Field(Decimal("0"), ge=0)
    currency: Optional[Currency] = None
    received_on: date
    investment_id: Optional[uuid.UUID] = None
    description: Optional[str] = Field(None, max_length=500)


class IncomeUpdate(BaseModel):
    income_type: Optional[IncomeType] = None
    amount: Optional[MoneyIn] = Field(None, gt=0)
    tax_deducted: Optional[MoneyIn] = Field(None, ge=0)
    currency: Optional[Currency] = None
    received_on: Optional[date] = None
    investment_id: Optional[uuid.UUID] = None
    description: Optional[str] = Field(None, max_length=500)


class IncomeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    income_type: str
    amount: MoneyOut
    tax_deducted: MoneyOut
    net_received: MoneyOut
    currency: str
    received_on: date
    investment_id: Optional[uuid.UUID]
    description: Optional[str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class SubjectAccessResponse(BaseModel):
    """The caller may act on this record; documents shows `label` next to the attached file."""

    type: str
    id: uuid.UUID
    organization_id: uuid.UUID
    label: Optional[str] = None
