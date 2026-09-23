import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import uuid

from config import settings


class StorageService:
    """
    Physical storage and presigned URL management service for S3 / blob storage.
    """

    def generate_upload_url(
        self,
        org_id: uuid.UUID,
        object_key: str,
        mime_type: str,
        sha256_hex: str,
        expires_minutes: int = 15,
    ) -> tuple[str, dict[str, str], datetime]:
        """
        Generate a presigned PUT URL and required headers for client direct upload.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

        # Convert hex sha256 to base64 for AWS S3 checksum header
        sha_bytes = bytes.fromhex(sha256_hex)
        b64_sha256 = base64.b64encode(sha_bytes).decode("utf-8")

        bucket = settings.s3_bucket
        region = settings.s3_region
        base_url = (
            settings.s3_endpoint_url
            if settings.s3_endpoint_url
            else f"https://{bucket}.s3.{region}.amazonaws.com"
        )
        # Mock AWS HMAC signature for presigned URL
        sig = hmac.new(
            b"fbos-mock-secret-key",
            f"{org_id}/{object_key}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]

        upload_url = f"{base_url}/{object_key}?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=900&X-Amz-Signature={sig}"

        headers = {
            "Content-Type": mime_type,
            "x-amz-checksum-sha256": b64_sha256,
        }

        return upload_url, headers, expires_at

    def generate_download_url(
        self,
        object_key: str,
        expires_seconds: int = 60,
    ) -> tuple[str, datetime]:
        """
        Generate a presigned GET URL valid for 60 seconds.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
        bucket = settings.s3_bucket
        region = settings.s3_region
        base_url = (
            settings.s3_endpoint_url
            if settings.s3_endpoint_url
            else f"https://{bucket}.s3.{region}.amazonaws.com"
        )

        sig = hmac.new(
            b"fbos-mock-secret-key",
            object_key.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]

        download_url = f"{base_url}/{object_key}?X-Amz-Expires={expires_seconds}&X-Amz-Signature={sig}"
        return download_url, expires_at


storage_service = StorageService()
