from typing import Any, Optional

from fastapi import HTTPException, status


class CommunicationServiceError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, meta: Optional[dict[str, Any]] = None) -> None:
        payload: dict[str, Any] = {"code": code, "message": message, "status": status_code}
        if meta is not None:
            payload["meta"] = meta
        super().__init__(status_code=status_code, detail=payload)


class InboxItemNotFoundError(CommunicationServiceError):
    def __init__(self, item_id: Optional[str] = None) -> None:
        msg = f"Inbox item '{item_id}' not found" if item_id else "Inbox item not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class NotificationRuleNotFoundError(CommunicationServiceError):
    def __init__(self, rule_id: Optional[str] = None) -> None:
        msg = f"Notification rule '{rule_id}' not found" if rule_id else "Notification rule not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class WebhookSubscriptionNotFoundError(CommunicationServiceError):
    def __init__(self, sub_id: Optional[str] = None) -> None:
        msg = f"Webhook subscription '{sub_id}' not found" if sub_id else "Webhook subscription not found"
        super().__init__(status.HTTP_404_NOT_FOUND, "NOT_FOUND", msg)


class DuplicateRuleCodeError(CommunicationServiceError):
    def __init__(self, code: str) -> None:
        super().__init__(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_CODE",
            f"A notification rule with code '{code}' already exists in this organization.",
            meta={"existing_code": code},
        )


class ValidationFailedError(CommunicationServiceError):
    def __init__(self, errors: Optional[list[dict[str, Any]]] = None) -> None:
        payload: dict[str, Any] = {
            "code": "VALIDATION_FAILED",
            "message": "Schema or field-level business rules failed.",
            "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
        }
        if errors:
            payload["errors"] = errors
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_FAILED", "Schema or field-level business rules failed.")
