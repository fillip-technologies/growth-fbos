from typing import Optional
from fastapi import HTTPException, status


class DocumentNotFoundError(HTTPException):
    def __init__(self, document_id: Optional[str] = None) -> None:
        message = f"Document '{document_id}' not found" if document_id is not None else "Document not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": message, "status": 404},
        )


class DocumentCategoryNotFoundError(HTTPException):
    def __init__(self, category_id: Optional[str] = None) -> None:
        message = (
            f"Document category '{category_id}' not found"
            if category_id is not None
            else "Document category not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DOCUMENT_CATEGORY_NOT_FOUND", "message": message, "status": 404},
        )


class DocumentVersionNotFoundError(HTTPException):
    def __init__(self, version_id: Optional[str] = None) -> None:
        message = (
            f"Document version '{version_id}' not found"
            if version_id is not None
            else "Document version not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DOCUMENT_VERSION_NOT_FOUND", "message": message, "status": 404},
        )


class DocumentShareNotFoundError(HTTPException):
    def __init__(self, share_id: Optional[str] = None) -> None:
        message = (
            f"Document share '{share_id}' not found"
            if share_id is not None
            else "Document share not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DOCUMENT_SHARE_NOT_FOUND", "message": message, "status": 404},
        )


class DocumentShareExpiredError(HTTPException):
    def __init__(self, share_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "DOCUMENT_SHARE_EXPIRED",
                "message": f"Document share '{share_id}' has expired or reached download limit",
                "status": 410,
            },
        )


class DocumentLockedError(HTTPException):
    def __init__(self, document_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "code": "DOCUMENT_LOCKED",
                "message": f"Document '{document_id}' is locked or under legal hold",
                "status": 423,
            },
        )


class NotificationNotFoundError(HTTPException):
    def __init__(self, notification_id: Optional[str] = None) -> None:
        message = (
            f"Notification '{notification_id}' not found"
            if notification_id is not None
            else "Notification not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOTIFICATION_NOT_FOUND", "message": message, "status": 404},
        )


class NotificationTemplateNotFoundError(HTTPException):
    def __init__(self, template_code: Optional[str] = None) -> None:
        message = (
            f"Notification template '{template_code}' not found"
            if template_code is not None
            else "Notification template not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "TEMPLATE_NOT_FOUND", "message": message, "status": 404},
        )


class NotificationRuleNotFoundError(HTTPException):
    def __init__(self, rule_id: Optional[str] = None) -> None:
        message = (
            f"Notification rule '{rule_id}' not found"
            if rule_id is not None
            else "Notification rule not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOTIFICATION_RULE_NOT_FOUND", "message": message, "status": 404},
        )


class DeliveryNotFoundError(HTTPException):
    def __init__(self, delivery_id: Optional[str] = None) -> None:
        message = f"Delivery '{delivery_id}' not found" if delivery_id is not None else "Delivery not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DELIVERY_NOT_FOUND", "message": message, "status": 404},
        )


class ChannelNotFoundError(HTTPException):
    def __init__(self, channel_type: Optional[str] = None) -> None:
        message = (
            f"Notification channel for '{channel_type}' not found or inactive"
            if channel_type is not None
            else "Notification channel not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CHANNEL_NOT_FOUND", "message": message, "status": 404},
        )


class SuppressedRecipientError(HTTPException):
    def __init__(self, address: str, channel_type: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "RECIPIENT_SUPPRESSED",
                "message": f"Recipient '{address}' is suppressed for channel '{channel_type}'",
                "status": 422,
            },
        )


class GovernancePolicyNotFoundError(HTTPException):
    def __init__(self, policy_id: Optional[str] = None) -> None:
        message = (
            f"Governance policy '{policy_id}' not found"
            if policy_id is not None
            else "Governance policy not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "GOVERNANCE_POLICY_NOT_FOUND", "message": message, "status": 404},
        )


class ComplianceRequirementNotFoundError(HTTPException):
    def __init__(self, requirement_id: Optional[str] = None) -> None:
        message = (
            f"Compliance requirement '{requirement_id}' not found"
            if requirement_id is not None
            else "Compliance requirement not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPLIANCE_REQUIREMENT_NOT_FOUND", "message": message, "status": 404},
        )


class ComplianceEvidenceNotFoundError(HTTPException):
    def __init__(self, evidence_id: Optional[str] = None) -> None:
        message = (
            f"Compliance evidence '{evidence_id}' not found"
            if evidence_id is not None
            else "Compliance evidence not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "COMPLIANCE_EVIDENCE_NOT_FOUND", "message": message, "status": 404},
        )


class DuplicateDocumentCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_DOCUMENT_CODE",
                "message": f"Document with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicatePolicyCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_POLICY_CODE",
                "message": f"Governance policy with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateComplianceCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_COMPLIANCE_CODE",
                "message": f"Compliance requirement with code '{code}' already exists",
                "status": 409,
            },
        )
