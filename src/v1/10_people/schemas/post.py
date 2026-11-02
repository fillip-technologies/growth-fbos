import uuid
from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class WorkerPostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    post_ref: uuid.UUID
    worker_id: uuid.UUID
    post_type: str
    title: str
    unit_id: Optional[uuid.UUID] = None
    position_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    manager_name: Optional[str] = None
    time_share: Optional[Decimal] = None
    # The allowance amount is pay data: only those who may see pay get it.
    has_allowance: bool = False
    monthly_allowance: Optional[Decimal] = None
    start_date: date
    end_date: Optional[date] = None
    status: str
    role_change_id: Optional[uuid.UUID] = None


class WorkerPostList(BaseModel):
    data: List[WorkerPostResponse]


class OrgChartNode(BaseModel):
    worker_id: uuid.UUID
    name: str
    designation: str
    unit_id: Optional[uuid.UUID] = None
    status: str
    manager_id: Optional[uuid.UUID] = None  # the primary post's manager: a solid line
    dotted_manager_ids: List[uuid.UUID] = []  # managers of the other posts: dotted lines
    extra_post_titles: List[str] = []


class OrgChart(BaseModel):
    data: List[OrgChartNode]
    truncated: bool = False


class PostsReportRow(BaseModel):
    unit_id: Optional[uuid.UUID] = None  # none: posts and seats with no department
    people: int
    primary_posts: int
    concurrent_posts: int
    additional_charge_posts: int
    acting_posts: int
    allocated_fte: float  # the posts' shares of time added up (acting and additional-charge posts add none)
    budgeted_fte: float  # the seats' budget
    seat_used_fte: float
    open_fte: float


class PostsReportTotals(BaseModel):
    people: int
    posts: int
    allocated_fte: float
    budgeted_fte: float
    seat_used_fte: float


class PostsReport(BaseModel):
    data: List[PostsReportRow]
    totals: PostsReportTotals
