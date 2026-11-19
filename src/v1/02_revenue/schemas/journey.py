"""A deal's journey: the lead, opportunity, quotations, contracts, invoices and payments one sale
went through, read from any one of them, so a record's page can show where it stands and what
comes next.

Each stage is filled only when the caller may read that kind of record; otherwise it is named in
`hidden`, so the page can say "not shown" rather than "not there yet".
"""
import uuid
import datetime as dt
from typing import List, Literal, Optional

from pydantic import BaseModel

from schemas.common import Money

JourneySubject = Literal["lead", "opportunity", "quotation", "contract", "invoice"]
JourneyStage = Literal["lead", "opportunity", "proposals", "quotations", "contracts", "invoices", "payments"]


class JourneyRecord(BaseModel):
    """One record on the journey, as much as a step of it needs to show and link to."""

    id: uuid.UUID
    number: Optional[str] = None  # lead code, proposal no, quote no, contract no, invoice no, receipt no
    name: Optional[str] = None
    status: str
    amount: Optional[Money] = None
    date: Optional[dt.date] = None  # when it happened: created, issued, received
    kind: Optional[str] = None  # an invoice's doc_type; a quotation's revision ("R2"); a proposal's version ("v2")
    is_main: bool = False  # the opportunity's main quotation / the contract's accepted one


class JourneyClient(BaseModel):
    id: uuid.UUID
    name: str


class JourneyTotals(BaseModel):
    """Money across the journey's invoices (credit notes taken off): billed, received, still owed."""

    invoiced: Money
    received: Money
    balance_due: Money


class JourneyResponse(BaseModel):
    subject_type: JourneySubject
    subject_id: uuid.UUID
    client: Optional[JourneyClient] = None
    lead: Optional[JourneyRecord] = None
    opportunity: Optional[JourneyRecord] = None
    # Each proposal's latest version (a sale from a lead is quoted from its accepted one).
    proposals: List[JourneyRecord] = []
    quotations: List[JourneyRecord] = []
    contracts: List[JourneyRecord] = []
    invoices: List[JourneyRecord] = []
    payments: List[JourneyRecord] = []
    totals: Optional[JourneyTotals] = None  # null when invoices are hidden
    hidden: List[JourneyStage] = []
