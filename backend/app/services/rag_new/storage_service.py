import io
from uuid import uuid4

import cloudinary
from cloudinary import uploader
import httpx

from app.core.config import settings


class StorageError(Exception):
    """Raised when an operation against the object storage backend fails."""


_cloudinary_configured = False


def _ensure_cloudinary_config() -> None:
    global _cloudinary_configured
    if _cloudinary_configured:
        return
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    _cloudinary_configured = True


class StorageService:

    def _supabase_headers(self) -> dict[str, str]:
        key = settings.supabase_secret_key or settings.supabase_publishable_key
        headers = {"apikey": key}
        if not key.startswith(("sb_publishable_", "sb_secret_")):
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _upload_supabase(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: int,
        public_id: str | None = None,
    ) -> tuple[str, str]:
        """Upload a file to Supabase Storage bucket."""
        bucket = settings.supabase_bucket or "documents"
        storage_path = public_id or f"users/{user_id}/{uuid4().hex}_{filename}"
        base_url = settings.supabase_url.rstrip("/")
        upload_url = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"

        headers = self._supabase_headers()
        headers["x-upsert"] = "true"

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    upload_url,
                    headers=headers,
                    content=file_bytes,
                )
                if resp.status_code not in (200, 201):
                    raise StorageError(
                        f"Supabase Storage error ({resp.status_code}): {resp.text}"
                    )
        except Exception as exc:
            raise StorageError(
                f"Failed to upload file '{filename}' to Supabase Storage"
            ) from exc

        public_url = f"{base_url}/storage/v1/object/public/{bucket}/{storage_path}"
        return storage_path, public_url

    def _delete_supabase(self, storage_path: str) -> None:
        """Delete a file from Supabase Storage bucket."""
        bucket = settings.supabase_bucket or "documents"
        base_url = settings.supabase_url.rstrip("/")
        delete_url = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.delete(delete_url, headers=self._supabase_headers())
                if resp.status_code not in (200, 204):
                    # Attempt bulk delete format if single delete returned error
                    client.post(
                        f"{base_url}/storage/v1/object/{bucket}",
                        headers=self._supabase_headers(),
                        json={"prefixes": [storage_path]},
                    )
        except Exception as exc:
            raise StorageError(
                f"Failed to delete file '{storage_path}' from Supabase Storage"
            ) from exc

    def upload_file_from_path(
        self,
        file_path,
        filename: str,
        user_id: int,
        public_id: str | None = None,
    ) -> tuple[str, str]:
        """Upload a file from disk to the first available storage provider.

        Reads the file from ``file_path`` (a staged temp file) so the caller
        does not need to hold the full payload in RAM. Tries Supabase Storage
        first, then Cloudinary.
        """
        from pathlib import Path

        path = Path(file_path)
        errors: list[str] = []

        # 1. Try Supabase Storage if credentials are configured
        if settings.supabase_url and (
            settings.supabase_secret_key or settings.supabase_publishable_key
        ):
            try:
                return self._upload_supabase_from_path(path, filename, user_id, public_id)
            except StorageError as exc:
                errors.append(f"Supabase Storage: {exc}")

        # 2. Fallback to Cloudinary if configured
        if settings.cloudinary_cloud_name:
            _ensure_cloudinary_config()
            cloudinary_public_id = public_id or f"docsense/users/{user_id}/{uuid4().hex}"
            try:
                result = uploader.upload(
                    str(path),
                    public_id=cloudinary_public_id,
                    resource_type="raw",
                )
            except Exception as exc:
                errors.append(f"Cloudinary: {exc}")
            else:
                return result["public_id"], result["secure_url"]

        if errors:
            raise StorageError(
                f"All storage providers failed: {'; '.join(errors)}"
            )
        raise StorageError("No storage provider configured (Supabase Storage or Cloudinary required).")

    @staticmethod
    def _upload_supabase_from_path(
        file_path,
        filename: str,
        user_id: int,
        public_id: str | None = None,
    ) -> tuple[str, str]:
        """Upload a file from disk to Supabase Storage bucket."""
        import httpx

        bucket = settings.supabase_bucket or "documents"
        storage_path = public_id or f"users/{user_id}/{uuid4().hex}_{filename}"
        base_url = settings.supabase_url.rstrip("/")
        upload_url = f"{base_url}/storage/v1/object/{bucket}/{storage_path}"

        headers = {"apikey": settings.supabase_secret_key or settings.supabase_publishable_key}
        key = settings.supabase_secret_key or settings.supabase_publishable_key
        if not key.startswith(("sb_publishable_", "sb_secret_")):
            headers["Authorization"] = f"Bearer {key}"
        headers["x-upsert"] = "true"

        try:
            with open(file_path, "rb") as fh:
                file_bytes = fh.read()
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    upload_url,
                    headers=headers,
                    content=file_bytes,
                )
                if resp.status_code not in (200, 201):
                    raise StorageError(
                        f"Supabase Storage error ({resp.status_code}): {resp.text}"
                    )
        except Exception as exc:
            raise StorageError(
                f"Failed to upload file '{filename}' to Supabase Storage"
            ) from exc

        public_url = f"{base_url}/storage/v1/object/public/{bucket}/{storage_path}"
        return storage_path, public_url

    def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: int,
        public_id: str | None = None,
    ) -> tuple[str, str]:
        """Upload any file to the first available storage provider (Supabase Storage or Cloudinary).

        Tries Supabase Storage first when credentials are configured. If Supabase
        fails, falls back to Cloudinary. Returns the (storage_key, public_url) from
        whichever provider succeeds. Raises StorageError only if every configured
        provider fails (or none is configured).
        """
        errors: list[str] = []

        # 1. Try Supabase Storage if credentials are configured
        if settings.supabase_url and (
            settings.supabase_secret_key or settings.supabase_publishable_key
        ):
            try:
                return self._upload_supabase(file_bytes, filename, user_id, public_id)
            except StorageError as exc:
                errors.append(f"Supabase Storage: {exc}")

        # 2. Fallback to Cloudinary if configured
        if settings.cloudinary_cloud_name:
            _ensure_cloudinary_config()
            cloudinary_public_id = public_id or f"docsense/users/{user_id}/{uuid4().hex}"
            try:
                result = uploader.upload(
                    io.BytesIO(file_bytes),
                    public_id=cloudinary_public_id,
                    resource_type="raw",
                )
            except Exception as exc:
                errors.append(f"Cloudinary: {exc}")
            else:
                return result["public_id"], result["secure_url"]

        if errors:
            raise StorageError(
                f"All storage providers failed: {'; '.join(errors)}"
            )
        raise StorageError("No storage provider configured (Supabase Storage or Cloudinary required).")

    def upload_pdf(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: int,
        public_id: str | None = None,
    ) -> tuple[str, str]:
        """Upload a PDF (backward compatible alias)."""
        return self.upload_file(file_bytes, filename, user_id, public_id)

    def delete_file(self, public_id: str) -> None:
        """Delete a file from whichever storage provider holds it.

        Tries Supabase Storage first when configured, then Cloudinary. A provider
        that reports the object as missing is skipped; StorageError is raised only
        if every configured provider fails (or none is configured).
        """
        errors: list[str] = []

        if settings.supabase_url and (
            settings.supabase_secret_key or settings.supabase_publishable_key
        ):
            try:
                self._delete_supabase(public_id)
                return
            except StorageError as exc:
                errors.append(f"Supabase Storage: {exc}")

        if settings.cloudinary_cloud_name:
            _ensure_cloudinary_config()
            try:
                uploader.destroy(public_id, resource_type="raw")
                return
            except Exception as exc:
                errors.append(f"Cloudinary: {exc}")

        if errors:
            raise StorageError(
                f"All storage providers failed to delete: {'; '.join(errors)}"
            )
        raise StorageError("No storage provider configured.")