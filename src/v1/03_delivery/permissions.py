"""
Delivery's permission codes, as identity's catalog names them (`delivery.<entity>.<action>`).

Routes are guarded with them (`require_permission`), and services use them for decisions
that also depend on who is asking: an assignee may tick their own checklist, anyone else
needs TASK_WRITE.
"""

WORK_UNIT_READ = "delivery.work_unit.read"
WORK_UNIT_WRITE = "delivery.work_unit.write"
CHANGE_REQUEST_APPROVE = "delivery.change_request.approve"

TASK_READ = "delivery.task.read"
TASK_WRITE = "delivery.task.write"
TASK_REVIEW = "delivery.task.review"
TASK_REQUEST = "delivery.task.request"
TIME_ENTRY_READ = "delivery.time_entry.read"

HANDOVER_READ = "delivery.handover.read"
HANDOVER_WRITE = "delivery.handover.write"

TEMPLATE_MANAGE = "delivery.template.manage"

WORKFLOW_READ = "delivery.workflow.read"
WORKFLOW_MANAGE = "delivery.workflow.manage"
WORKFLOW_OPERATE = "delivery.workflow.operate"
WORKFLOW_APPROVE = "delivery.workflow.approve"
