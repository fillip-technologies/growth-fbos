from pydantic import BaseModel


class TasksSummary(BaseModel):
    assigned_open: int
    due_today: int
    overdue: int


class HomeSummary(BaseModel):
    tasks: TasksSummary
    approvals_pending: int
    escalations_open: int
    unread_notifications: int
    degraded: list[str]
