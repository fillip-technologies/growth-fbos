from typing import Optional
from fastapi import HTTPException, status


class AssetNotFoundError(HTTPException):
    def __init__(self, asset_id: Optional[str] = None) -> None:
        message = f"Asset '{asset_id}' not found" if asset_id is not None else "Asset not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ASSET_NOT_FOUND", "message": message, "status": 404},
        )


class AssetCategoryNotFoundError(HTTPException):
    def __init__(self, category_id: Optional[str] = None) -> None:
        message = (
            f"Asset category '{category_id}' not found"
            if category_id is not None
            else "Asset category not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ASSET_CATEGORY_NOT_FOUND", "message": message, "status": 404},
        )


class AssetTypeNotFoundError(HTTPException):
    def __init__(self, type_id: Optional[str] = None) -> None:
        message = f"Asset type '{type_id}' not found" if type_id is not None else "Asset type not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ASSET_TYPE_NOT_FOUND", "message": message, "status": 404},
        )


class VendorNotFoundError(HTTPException):
    def __init__(self, vendor_id: Optional[str] = None) -> None:
        message = f"Vendor '{vendor_id}' not found" if vendor_id is not None else "Vendor not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "VENDOR_NOT_FOUND", "message": message, "status": 404},
        )


class VendorAccountNotFoundError(HTTPException):
    def __init__(self, account_id: Optional[str] = None) -> None:
        message = (
            f"Vendor account '{account_id}' not found"
            if account_id is not None
            else "Vendor account not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "VENDOR_ACCOUNT_NOT_FOUND", "message": message, "status": 404},
        )


class SubscriptionNotFoundError(HTTPException):
    def __init__(self, subscription_id: Optional[str] = None) -> None:
        message = (
            f"Subscription '{subscription_id}' not found"
            if subscription_id is not None
            else "Subscription not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SUBSCRIPTION_NOT_FOUND", "message": message, "status": 404},
        )


class LicenseNotFoundError(HTTPException):
    def __init__(self, license_id: Optional[str] = None) -> None:
        message = f"License '{license_id}' not found" if license_id is not None else "License not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "LICENSE_NOT_FOUND", "message": message, "status": 404},
        )


class LicenseSeatsExhaustedError(HTTPException):
    def __init__(self, license_id: str, total_seats: int) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "LICENSE_SEATS_EXHAUSTED",
                "message": f"All {total_seats} seats for license '{license_id}' are currently allocated",
                "status": 409,
            },
        )


class CredentialNotFoundError(HTTPException):
    def __init__(self, credential_id: Optional[str] = None) -> None:
        message = (
            f"Credential '{credential_id}' not found"
            if credential_id is not None
            else "Credential not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CREDENTIAL_NOT_FOUND", "message": message, "status": 404},
        )


class CredentialExpiredError(HTTPException):
    def __init__(self, credential_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "CREDENTIAL_EXPIRED",
                "message": f"Credential '{credential_id}' has expired and must be rotated",
                "status": 410,
            },
        )


class DashboardNotFoundError(HTTPException):
    def __init__(self, dashboard_id: Optional[str] = None) -> None:
        message = (
            f"Dashboard '{dashboard_id}' not found"
            if dashboard_id is not None
            else "Dashboard not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DASHBOARD_NOT_FOUND", "message": message, "status": 404},
        )


class ReportDefinitionNotFoundError(HTTPException):
    def __init__(self, report_id: Optional[str] = None) -> None:
        message = (
            f"Report definition '{report_id}' not found"
            if report_id is not None
            else "Report definition not found"
        )
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_DEFINITION_NOT_FOUND", "message": message, "status": 404},
        )


class ReportRunNotFoundError(HTTPException):
    def __init__(self, run_id: Optional[str] = None) -> None:
        message = f"Report run '{run_id}' not found" if run_id is not None else "Report run not found"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REPORT_RUN_NOT_FOUND", "message": message, "status": 404},
        )


class DuplicateAssetTagError(HTTPException):
    def __init__(self, tag: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_ASSET_TAG",
                "message": f"Asset with tag '{tag}' already exists",
                "status": 409,
            },
        )


class DuplicateCategoryCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_CATEGORY_CODE",
                "message": f"Asset category with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateVendorCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_VENDOR_CODE",
                "message": f"Vendor with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateDashboardCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_DASHBOARD_CODE",
                "message": f"Dashboard with code '{code}' already exists",
                "status": 409,
            },
        )


class DuplicateReportCodeError(HTTPException):
    def __init__(self, code: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DUPLICATE_REPORT_CODE",
                "message": f"Report definition with code '{code}' already exists",
                "status": 409,
            },
        )


class IdempotencyConflictError(HTTPException):
    def __init__(self, key: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": f"Request with idempotency key '{key}' is currently being processed with different parameters",
                "status": 409,
            },
        )
