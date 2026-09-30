from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import posixpath
import uuid

import httpx

from config import settings
from exceptions import ChecksumMismatchError

IMAGEKIT_UPLOAD_URL = "https://upload.imagekit.io/api/v1/files/upload"
# ImageKit rejects client-upload tokens that expire more than one hour ahead.
MAX_UPLOAD_TOKEN_SECONDS = 3600


@dataclass(frozen=True)
class UploadTarget:
    """Everything a client needs to send the file straight to the storage provider."""

    url: str
    method: str
    headers: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StorageService:
    """
    Private file storage on ImageKit.io.

    Uploads go directly from the client to ImageKit with server-signed credentials;
    downloads use short-lived signed URLs. When IMAGEKIT_PRIVATE_KEY is empty (local
    dev / tests) the service runs in a stub mode that returns deterministic fake URLs
    and skips remote verification.
    """

    @property
    def provider_name(self) -> str:
        return "imagekit"

    @property
    def is_configured(self) -> bool:
        return bool(settings.imagekit_private_key)

    @staticmethod
    def _split_key(object_key: str) -> tuple[str, str]:
        """object_key 'org/ab12/file' -> ('/org/ab12', 'file')."""
        folder, name = posixpath.split(object_key.strip("/"))
        return f"/{folder}" if folder else "/", name

    def _sign_upload(self, token: str, expire: int) -> str:
        # ImageKit client-upload signature: HMAC-SHA1(private_key, token + expire), hex.
        return hmac.new(
            settings.imagekit_private_key.encode("utf-8"),
            f"{token}{expire}".encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()

    def generate_upload_target(
        self,
        org_id: uuid.UUID,
        object_key: str,
        mime_type: str,
        expires_minutes: int = 15,
    ) -> UploadTarget:
        """Signed multipart-POST parameters for a direct, private client upload."""
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
        expire = int(expires_at.timestamp())
        expire = min(expire, int(datetime.now(timezone.utc).timestamp()) + MAX_UPLOAD_TOKEN_SECONDS)
        token = uuid.uuid4().hex
        folder, file_name = self._split_key(object_key)

        fields = {
            "publicKey": settings.imagekit_public_key,
            "token": token,
            "expire": str(expire),
            "signature": self._sign_upload(token, expire) if self.is_configured else "dev-stub-signature",
            "fileName": file_name,
            "folder": folder,
            "isPrivateFile": "true",
            "useUniqueFileName": "false",
        }
        return UploadTarget(url=IMAGEKIT_UPLOAD_URL, method="POST", fields=fields, expires_at=expires_at)

    def generate_download_url(
        self,
        object_key: str,
        expires_seconds: int = 60,
    ) -> tuple[str, datetime]:
        """Signed URL for a private file, valid for `expires_seconds`."""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
        src = f"/{object_key.lstrip('/')}"

        if not self.is_configured:
            base = settings.imagekit_url_endpoint.rstrip("/") or "https://ik.imagekit.io/dev-stub"
            return f"{base}{src}?ik-stub-expires={expires_seconds}", expires_at

        # Imported lazily so the service still boots (stub mode) without the SDK installed.
        from imagekitio import ImageKit

        client = ImageKit(private_key=settings.imagekit_private_key)
        url = client.helper.build_url(
            url_endpoint=settings.imagekit_url_endpoint,
            src=src,
            signed=True,
            expires_in=expires_seconds,
        )
        return url, expires_at

    async def verify_object(self, object_key: str, size_bytes: int) -> None:
        """
        Confirm the uploaded file exists in ImageKit with the declared size.

        ImageKit has no SHA-256 upload header, so existence + size is the integrity check.
        Raises ChecksumMismatchError when the file is missing or its size differs.
        """
        if not self.is_configured:
            return

        # A HEAD on a short-lived signed URL is read-after-write consistent, unlike the
        # search-backed list API.
        url, _ = self.generate_download_url(object_key, expires_seconds=60)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.head(url)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ChecksumMismatchError()
        response.raise_for_status()
        if int(response.headers.get("content-length", -1)) != size_bytes:
            raise ChecksumMismatchError()


storage_service = StorageService()
