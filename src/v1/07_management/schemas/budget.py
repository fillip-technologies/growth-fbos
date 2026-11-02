import uuid
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class BudgetScope(BaseModel):
    unit_id: Optional[uuid.UUID] = None
    vertical_id: Optional[uuid.UUID] = None


class FiscalYearRef(BaseModel):
    id: uuid.UUID
    code: str


class BudgetCreate(BaseModel):
    fiscal_year_id: uuid.UUID
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    currency: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    scope: BudgetScope = Field(default_factory=BudgetScope)


class BudgetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    currency: Optional[str] = Field(None, min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    scope: Optional[BudgetScope] = None


class BudgetLineCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    planned_amount: float = Field(ge=0)


class BudgetLineUpdate(BaseModel):
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    planned_amount: Optional[float] = Field(None, ge=0)


class BudgetLineResponse(BaseModel):
    id: uuid.UUID
    category: str
    description: Optional[str] = None
    planned_amount: float
    approved_amount: float
    allocated_amount: float
    actual_amount: float


class BudgetTotals(BaseModel):
    planned: float
    approved: float
    actual: float


class BudgetResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    fiscal_year: FiscalYearRef
    scope: BudgetScope
    currency: str
    revision_no: int
    status: str  # draft | pending_approval | approved | rejected
    approval_request_id: Optional[uuid.UUID] = None
    lines: list[BudgetLineResponse]
    totals: BudgetTotals


class BudgetTarget(BaseModel):
    type: Literal["initiative"]
    id: uuid.UUID


class BudgetAllocationCreate(BaseModel):
    target: BudgetTarget
    amount: float = Field(gt=0)


class BudgetAllocationResponse(BaseModel):
    id: uuid.UUID
    budget_line_id: uuid.UUID
    target: BudgetTarget
    amount: float


class BudgetActualCreate(BaseModel):
    amount: float
    occurred_on: date


class InternalBudgetActualCreate(BaseModel):
    """An actual mirrored from the service that owns the money; idempotent on `source_event_id`."""

    organization_id: uuid.UUID
    budget_line_id: Optional[uuid.UUID] = None
    budget_code: Optional[str] = None
    category: Optional[str] = None
    amount: float
    occurred_on: date
    source_type: str = Field(min_length=1, max_length=50)
    source_event_id: uuid.UUID

    @model_validator(mode="after")
    def _names_a_line(self) -> "InternalBudgetActualCreate":
        if self.budget_line_id is None and not (self.budget_code and self.category):
            raise ValueError("give budget_line_id, or budget_code and category")
        return self


class BudgetActualResponse(BaseModel):
    id: uuid.UUID
    budget_line_id: uuid.UUID
    amount: float
    occurred_on: date
    source_type: str
    source_event_id: Optional[uuid.UUID] = None


class VarianceLine(BaseModel):
    budget_line_id: uuid.UUID
    category: str
    planned: float
    approved: float
    actual: float
    # Promised but not yet spent: confirmed bookings from `as_of` on initiatives this line funds, at cost rates.
    committed: float
    available: float  # approved - actual - committed
    variance_abs: float  # actual - approved (positive: over budget)
    variance_pct: Optional[float] = None
    last_year_actual: Optional[float] = None  # same category, same scope, previous fiscal year


class VarianceResponse(BaseModel):
    budget_id: uuid.UUID
    currency: str
    as_of: date
    # Bookings whose resource has no cost rate can't be priced; they are left out of `committed`.
    unpriced_bookings: int
    lines: list[VarianceLine]
    totals: VarianceLine
