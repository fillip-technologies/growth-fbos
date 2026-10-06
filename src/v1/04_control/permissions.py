"""
Control's permission codes, as identity's catalog names them (`control.<entity>.<action>`).

Routes are guarded with them (`require_permission`); the approval rules that depend on who is
asking stay in the service: only an approver of the active step decides it, and only whoever
raised a request cancels it unless they hold APPROVAL_MANAGE.
"""

APPROVAL_READ = "control.approval.read"
APPROVAL_WRITE = "control.approval.write"
APPROVAL_MANAGE = "control.approval.manage"

SLA_READ = "control.sla.read"
SLA_WRITE = "control.sla.write"
SLA_MANAGE = "control.sla.manage"
