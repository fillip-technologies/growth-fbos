from typing import Any, Optional

from fastapi import HTTPException, status


class DeliveryServiceError(HTTPException):
    """Base exception for all delivery service domain errors."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[list[dict[str, Any]]] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details
        self.meta = meta
        payload: dict[str, Any] = {
            "code": code,
            "message": message,
            "status": status_code,
        }
        if details is not None:
            payload["details"] = details
        if meta is not None:
            payload["meta"] = meta
        super().__init__(status_code=status_code, detail=payload)


# --- Not found (404) -----------------------------------------------------


class WorkUnitNotFoundError(DeliveryServiceError):
    def __init__(self, work_unit_id: Optional[str] = None) -> None:
        message = f"Work unit '{work_unit_id}' not found" if work_unit_id is not None else "Work unit not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "WORK_UNIT_NOT_FOUND", message)


class WorkUnitTypeNotFoundError(DeliveryServiceError):
    def __init__(self, type_id: Optional[str] = None) -> None:
        message = f"Work unit type '{type_id}' not found" if type_id is not None else "Work unit type not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "WORK_UNIT_TYPE_NOT_FOUND", message)


class TemplateNotFoundError(DeliveryServiceError):
    def __init__(self, template_code: Optional[str] = None) -> None:
        message = f"Template '{template_code}' not found" if template_code is not None else "Template not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "TEMPLATE_NOT_FOUND", message)


class TemplateVersionNotFoundError(DeliveryServiceError):
    def __init__(self, version_no: Optional[Any] = None) -> None:
        message = f"Template version '{version_no}' not found" if version_no is not None else "Template version not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "TEMPLATE_VERSION_NOT_FOUND", message)


class PhaseNotFoundError(DeliveryServiceError):
    def __init__(self, phase_id: Optional[str] = None) -> None:
        message = f"Phase '{phase_id}' not found" if phase_id is not None else "Phase not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "PHASE_NOT_FOUND", message)


class MilestoneNotFoundError(DeliveryServiceError):
    def __init__(self, milestone_id: Optional[str] = None) -> None:
        message = f"Milestone '{milestone_id}' not found" if milestone_id is not None else "Milestone not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "MILESTONE_NOT_FOUND", message)


class WorkPackageNotFoundError(DeliveryServiceError):
    def __init__(self, package_id: Optional[str] = None) -> None:
        message = f"Work package '{package_id}' not found" if package_id is not None else "Work package not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "WORK_PACKAGE_NOT_FOUND", message)


class DeliverableNotFoundError(DeliveryServiceError):
    def __init__(self, deliverable_id: Optional[str] = None) -> None:
        message = f"Deliverable '{deliverable_id}' not found" if deliverable_id is not None else "Deliverable not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "DELIVERABLE_NOT_FOUND", message)


class RiskNotFoundError(DeliveryServiceError):
    def __init__(self, risk_id: Optional[str] = None) -> None:
        message = f"Risk '{risk_id}' not found" if risk_id is not None else "Risk not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "RISK_NOT_FOUND", message)


class IssueNotFoundError(DeliveryServiceError):
    def __init__(self, issue_id: Optional[str] = None) -> None:
        message = f"Issue '{issue_id}' not found" if issue_id is not None else "Issue not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "ISSUE_NOT_FOUND", message)


class ChangeRequestNotFoundError(DeliveryServiceError):
    def __init__(self, cr_id: Optional[str] = None) -> None:
        message = f"Change request '{cr_id}' not found" if cr_id is not None else "Change request not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "CHANGE_REQUEST_NOT_FOUND", message)


class WorkflowDefinitionNotFoundError(DeliveryServiceError):
    def __init__(self, definition_code: Optional[str] = None) -> None:
        message = (
            f"Workflow definition '{definition_code}' not found"
            if definition_code is not None
            else "Workflow definition not found"
        )
        super().__init__(status.HTTP_404_NOT_FOUND, "WORKFLOW_DEFINITION_NOT_FOUND", message)


class WorkflowVersionNotFoundError(DeliveryServiceError):
    def __init__(self, version_no: Optional[Any] = None) -> None:
        message = (
            f"Workflow version '{version_no}' not found" if version_no is not None else "Workflow version not found"
        )
        super().__init__(status.HTTP_404_NOT_FOUND, "WORKFLOW_VERSION_NOT_FOUND", message)


class WorkflowInstanceNotFoundError(DeliveryServiceError):
    def __init__(self, instance_id: Optional[str] = None) -> None:
        message = f"Workflow instance '{instance_id}' not found" if instance_id is not None else "Workflow instance not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "WORKFLOW_INSTANCE_NOT_FOUND", message)


class TaskNotFoundError(DeliveryServiceError):
    def __init__(self, task_id: Optional[str] = None) -> None:
        message = f"Task '{task_id}' not found" if task_id is not None else "Task not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "TASK_NOT_FOUND", message)


class TaskTypeNotFoundError(DeliveryServiceError):
    def __init__(self, task_type_code: Optional[str] = None) -> None:
        message = f"Task type '{task_type_code}' not found" if task_type_code is not None else "Task type not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "TASK_TYPE_NOT_FOUND", message)


class TaskTemplateNotFoundError(DeliveryServiceError):
    def __init__(self, template_code: Optional[str] = None) -> None:
        message = (
            f"Task template '{template_code}' not found" if template_code is not None else "Task template not found"
        )
        super().__init__(status.HTTP_404_NOT_FOUND, "TASK_TEMPLATE_NOT_FOUND", message)


class ChecklistItemNotFoundError(DeliveryServiceError):
    def __init__(self, item_id: Optional[str] = None) -> None:
        message = f"Checklist item '{item_id}' not found" if item_id is not None else "Checklist item not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "CHECKLIST_ITEM_NOT_FOUND", message)


class HandoverNotFoundError(DeliveryServiceError):
    def __init__(self, handover_id: Optional[str] = None) -> None:
        message = f"Handover '{handover_id}' not found" if handover_id is not None else "Handover not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "HANDOVER_NOT_FOUND", message)


class TimeEntryNotFoundError(DeliveryServiceError):
    def __init__(self, entry_id: Optional[str] = None) -> None:
        message = f"Time entry '{entry_id}' not found" if entry_id is not None else "Time entry not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "TIME_ENTRY_NOT_FOUND", message)


class RecurringRuleNotFoundError(DeliveryServiceError):
    def __init__(self, rule_id: Optional[str] = None) -> None:
        message = f"Recurring task rule '{rule_id}' not found" if rule_id is not None else "Recurring task rule not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "RECURRING_RULE_NOT_FOUND", message)


# --- Conflict (409) --------------------------------------------------------


class DuplicateCodeError(DeliveryServiceError):
    """409: A record with the same code already exists in this organization."""

    def __init__(self, code: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_CODE",
            f"A record with code '{code}' already exists in this organization.",
        )


class InvalidStateTransitionError(DeliveryServiceError):
    """409: The state machine does not allow this action from the record's current status."""

    def __init__(self, from_state: str, to_state: str, reason: Optional[str] = None) -> None:
        message = f"Cannot transition from '{from_state}' to '{to_state}'" + (f": {reason}" if reason else "")
        super().__init__(status.HTTP_409_CONFLICT, "INVALID_STATE_TRANSITION", message)


class VersionNotDraftError(DeliveryServiceError):
    """409: The version is published or retired."""

    def __init__(self, version_no: Any) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "VERSION_NOT_DRAFT",
            f"Version '{version_no}' is not a draft and can no longer be edited.",
        )


class BaselineChangeRequiresCrError(DeliveryServiceError):
    """409: Baseline dates/budget can't change directly after approval."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "BASELINE_CHANGE_REQUIRES_CR",
            "Baseline dates/budget can't change directly after approval; submit a change request instead.",
        )


class WorkUnitHasOpenItemsError(DeliveryServiceError):
    """409: Closing with open tasks, risks, change requests or incomplete milestones."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "WORK_UNIT_HAS_OPEN_ITEMS",
            "The work unit has open tasks, risks, change requests or incomplete milestones.",
        )


class DocumentScanPendingError(DeliveryServiceError):
    """409: Virus scan not finished (usually under 30 seconds). Retryable."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DOCUMENT_SCAN_PENDING",
            "One or more attached documents are still being scanned. Retry shortly.",
        )


class InstanceAlreadyRunningError(DeliveryServiceError):
    """409: One running instance per definition and subject."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "INSTANCE_ALREADY_RUNNING",
            "A running instance of this workflow definition already exists for this subject.",
        )


class TransitionNotAvailableError(DeliveryServiceError):
    """409: Unknown code, or not an outgoing transition of the active stage."""

    def __init__(self, transition_code: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "TRANSITION_NOT_AVAILABLE",
            f"Transition '{transition_code}' is unknown or not available from the active stage.",
        )


class TransitionConditionFailedError(DeliveryServiceError):
    """409: The JSON Logic condition evaluated to false."""

    def __init__(self, transition_code: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "TRANSITION_CONDITION_FAILED",
            f"The condition guarding transition '{transition_code}' evaluated to false.",
        )


class InstanceNotRunningError(DeliveryServiceError):
    """409: Instance is on hold, waiting for approval, completed or cancelled."""

    def __init__(self, status_val: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "INSTANCE_NOT_RUNNING",
            f"Instance is not running (current status: '{status_val}').",
        )


class FieldNotEditableInStatusError(DeliveryServiceError):
    """409: For example changing estimate after completion."""

    def __init__(self, field: str, status_val: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "FIELD_NOT_EDITABLE_IN_STATUS",
            f"Field '{field}' cannot be changed while the task is '{status_val}'.",
        )


class DependenciesOpenError(DeliveryServiceError):
    """409: A finish-to-start dependency is still open."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DEPENDENCIES_OPEN",
            "A finish-to-start dependency of this task is still open.",
        )


class TaskChecklistIncompleteError(DeliveryServiceError):
    """409: Submit attempted with unchecked mandatory items."""

    def __init__(self, pending_items: Optional[list[str]] = None) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "TASK_CHECKLIST_INCOMPLETE",
            "Mandatory checklist items are not done.",
            meta={"pending_items": pending_items} if pending_items else None,
        )


class DailyMinutesExceededError(DeliveryServiceError):
    """422: Sum of the user's minutes for work_date would exceed 1440."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "DAILY_MINUTES_EXCEEDED",
            "The sum of this user's logged minutes for the day would exceed 1440.",
        )


class TimeEntryLockedError(DeliveryServiceError):
    """409: The week was approved and locked."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "TIME_ENTRY_LOCKED",
            "This time entry's week was approved and locked.",
        )


class DependencyCycleError(DeliveryServiceError):
    """409: The new dependency makes the graph cyclic."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DEPENDENCY_CYCLE",
            "Adding this dependency would create a cycle in the task graph.",
        )


class HandoverAlreadyOpenError(DeliveryServiceError):
    """409: Only one open handover per subject."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "HANDOVER_ALREADY_OPEN",
            "There is already an open handover for this subject.",
        )


# --- Validation (422) -------------------------------------------------------


class TemplateInvalidError(DeliveryServiceError):
    """422: Structure fails the template JSON Schema."""

    def __init__(self, detail_msg: str = "Template structure fails validation.") -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, "TEMPLATE_INVALID", detail_msg)


class TemplateNotPublishedError(DeliveryServiceError):
    """422: The requested template (or version) is not published."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "TEMPLATE_NOT_PUBLISHED",
            "The requested template, or version, is not published.",
        )


class ClientRequiredError(DeliveryServiceError):
    """422: The work unit type requires client_id."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "CLIENT_REQUIRED",
            "The work unit type requires client_id.",
        )


class NoApprovalPolicyError(DeliveryServiceError):
    """422: No active policy matches and the organization requires one."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "NO_APPROVAL_POLICY",
            "No active approval policy matches and the organization requires one.",
        )


class SubjectTypeMismatchError(DeliveryServiceError):
    """422: definition.subject_type differs from subject.type."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "SUBJECT_TYPE_MISMATCH",
            "The workflow definition's subject_type differs from the subject's type.",
        )


class SubjectNotFoundError(DeliveryServiceError):
    """422: subject.type is unknown, or the object does not exist or is not visible to you."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "SUBJECT_NOT_FOUND",
            "subject.type is unknown, or the object does not exist or is not visible to you.",
        )


class WorkflowVersionInvalidError(DeliveryServiceError):
    """422: Publish-time validation failed."""

    def __init__(self, issues: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "WORKFLOW_VERSION_INVALID",
            "Publish-time validation failed.",
            details=issues,
        )


class AssigneeNotInUnitError(DeliveryServiceError):
    """422: Tasks are team-owned; the assignee must belong to the unit."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ASSIGNEE_NOT_IN_UNIT",
            "The assignee must be an active member of the owning unit.",
        )


class FeedbackRequiredError(DeliveryServiceError):
    """422: result=fail without feedback."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "FEEDBACK_REQUIRED",
            "Feedback is required when the review result is 'fail'.",
        )


class SameUnitError(DeliveryServiceError):
    """422: Handover to the same unit."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "SAME_UNIT",
            "from_unit_id and to_unit_id must be different units.",
        )


class RRuleInvalidError(DeliveryServiceError):
    """422: Not a valid RFC 5545 RRULE, or it produces no occurrences."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "RRULE_INVALID",
            "rrule is not a valid RFC 5545 recurrence rule, or it produces no occurrences.",
        )


# --- Forbidden (403) --------------------------------------------------------


class NotAssigneeError(DeliveryServiceError):
    """403: Start/submit attempted by someone other than the assignee."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "NOT_ASSIGNEE",
            "Only the task's assignee can perform this action.",
        )


class NotReviewerError(DeliveryServiceError):
    """403: Caller is not the reviewer and lacks review permission in scope."""

    def __init__(self) -> None:
        super().__init__(
            status.HTTP_403_FORBIDDEN,
            "NOT_REVIEWER",
            "Caller is not the task's reviewer and lacks review permission in scope.",
        )


# --- Concurrency (412 / 428) ------------------------------------------------


class PreconditionRequiredError(DeliveryServiceError):
    """428: If-Match header with the current ETag is required for this update."""

    def __init__(self, message: str = "If-Match header with the current ETag is required for this update.") -> None:
        super().__init__(status.HTTP_428_PRECONDITION_REQUIRED, "PRECONDITION_REQUIRED", message)


class VersionConflictError(DeliveryServiceError):
    """412: If-Match did not match the record's current version."""

    def __init__(self, current_version: Any) -> None:
        super().__init__(
            status.HTTP_412_PRECONDITION_FAILED,
            "VERSION_CONFLICT",
            f"The resource was modified by another request. Current version is '{current_version}'.",
            meta={"current_version": current_version},
        )
