from typing import Any, Optional
from fastapi import HTTPException, status


class DocumentsServiceError(HTTPException):
    """Base exception for all Documents service domain errors conforming to RFC 7807."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        meta: Optional[dict[str, Any]] = None,
        details: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.meta = meta
        self.details = details
        payload: dict[str, Any] = {
            "code": code,
            "message": message,
            "status": status_code,
        }
        if meta is not None:
            payload["meta"] = meta
        if details is not None:
            payload["details"] = details
        super().__init__(status_code=status_code, detail=payload)


class DocumentNotFoundError(DocumentsServiceError):
    """404: Document not found or outside caller scope."""

    def __init__(self, document_id: Optional[str] = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted. FBOS does not reveal which.",
        )


class VersionNotFoundError(DocumentsServiceError):
    """404: Version not found."""

    def __init__(self, version_no: Optional[int] = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The requested document version does not exist.",
        )


class ShareNotFoundError(DocumentsServiceError):
    """404: Share link not found."""

    def __init__(self, share_id: Optional[str] = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The id does not exist, or exists outside every scope you are granted. FBOS does not reveal which.",
        )


class UploadNotFoundError(DocumentsServiceError):
    """404: Upload session not found."""

    def __init__(self, upload_id: Optional[str] = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message="The upload session was not found.",
        )


class CategoryNotFoundError(DocumentsServiceError):
    """404: Document category not found."""

    def __init__(self, category_code: Optional[str] = None) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="NOT_FOUND",
            message=f"Document category '{category_code}' was not found.",
        )


class FileTooLargeError(DocumentsServiceError):
    """413: Exceeds 100 MB or the category limit."""

    def __init__(self, max_bytes: int = 104857600) -> None:
        super().__init__(
            status_code=getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413),
            code="FILE_TOO_LARGE",
            message="Exceeds 100 MB or the category limit.",
            meta={"max_bytes": max_bytes},
        )


class MimeTypeNotAllowedError(DocumentsServiceError):
    """415: The category doesn't accept this MIME type."""

    def __init__(self, mime_type: str) -> None:
        super().__init__(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            code="MIME_TYPE_NOT_ALLOWED",
            message="The category doesn't accept this MIME type.",
            meta={"mime_type": mime_type},
        )


class DocumentLockedError(DocumentsServiceError):
    """409: An approved version locks the document against new versions."""

    def __init__(self, message: str = "An approved version locks the document against new versions.") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="DOCUMENT_LOCKED",
            message=message,
        )


class ChecksumMismatchError(DocumentsServiceError):
    """422: SHA-256 or size of the stored object differs from declared values."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="CHECKSUM_MISMATCH",
            message="SHA-256 or size of the stored object differs from the declared values.",
        )


class DocumentScanPendingError(DocumentsServiceError):
    """409: Virus scan not finished (usually under 30 seconds). Retryable."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="DOCUMENT_SCAN_PENDING",
            message="Virus scan not finished (usually under 30 seconds).",
        )


class DocumentInfectedError(DocumentsServiceError):
    """409: File failed the virus scan."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            code="DOCUMENT_INFECTED",
            message="Malware detected; the file is quarantined.",
        )


class ShareExpiredError(DocumentsServiceError):
    """410: Share expired, was revoked or hit its download limit."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_410_GONE,
            code="SHARE_EXPIRED",
            message="Share expired, was revoked or hit its download limit.",
        )


class UploadExpiredError(DocumentsServiceError):
    """410: Upload session expired."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_410_GONE,
            code="UPLOAD_EXPIRED",
            message="Complete was called after the 1-hour upload window.",
        )


class SharePasswordRequiredError(DocumentsServiceError):
    """401: Password-protected share without (or with a wrong) X-Share-Password."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="SHARE_PASSWORD_REQUIRED",
            message="Password-protected share without (or with a wrong) X-Share-Password.",
        )


class SubjectNotFoundError(DocumentsServiceError):
    """422: Linked business object not found or invalid."""

    def __init__(self, message: str = "subject.type is unknown, or the object does not exist or is not visible to you.") -> None:
        super().__init__(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            code="SUBJECT_NOT_FOUND",
            message=message,
        )


class RestrictedDocumentCannotBeSharedError(DocumentsServiceError):
    """422/409: Only public, internal and confidential documents can be shared; restricted ones cannot."""

    def __init__(self) -> None:
        super().__init__(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            code="DOCUMENT_RESTRICTED",
            message="Only public, internal and confidential documents can be shared; restricted ones cannot.",
        )


class PermissionDeniedError(DocumentsServiceError):
    """403: Missing permission in scope."""

    def __init__(self, required_permission: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            code="PERMISSION_DENIED",
            message="The record is visible to you but your roles in its scope don't include the required permission.",
            meta={"required_permission": required_permission},
        )


class UnauthorizedError(DocumentsServiceError):
    """401: Missing or invalid authentication token."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="UNAUTHORIZED",
            message=message,
        )


class PreconditionRequiredError(DocumentsServiceError):
    """428: If-Match header is required for updating versioned resource."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            code="PRECONDITION_REQUIRED",
            message="The endpoint updates a versioned record and If-Match is missing.",
        )


class PreconditionFailedError(DocumentsServiceError):
    """412: If-Match version conflict."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            code="PRECONDITION_FAILED",
            message="The resource has been modified since it was fetched.",
        )
