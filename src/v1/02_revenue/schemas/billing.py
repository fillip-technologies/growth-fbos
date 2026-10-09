import uuid
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel

from schemas.common import Money


class BillingScheduleLineResponse(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    seq: int
    milestone_type: str
    milestone_code: Optional[str] = None
    due_date: Optional[date] = None
    # Before tax: the invoice drafted from the line adds the tax.
    amount: Money
    percent: Optional[float] = None
    description: Optional[str] = None
    status: Literal["planned", "ready", "invoiced", "cancelled"]
    # Ready to invoice now: marked ready (milestone reached), or its due date has come.
    billable: bool
    invoice_id: Optional[uuid.UUID] = None
    version: int


class BillingScheduleResponse(BaseModel):
    id: uuid.UUID
    contract_id: uuid.UUID
    client_id: uuid.UUID
    currency: str
    status: str
    basis_amount: Money
    lines: List[BillingScheduleLineResponse]


class BillingScheduleLineUpdate(BaseModel):
    # ready: the milestone was reached; cancelled: it will not be billed; planned: undo either.
    status: Literal["planned", "ready", "cancelled"]
