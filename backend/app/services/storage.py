import os
import uuid
from typing import Optional, BinaryIO
from app.db.s3_client import get_s3_client
from app.core.config import settings


class SupabaseStorageService:
    def __init__(self):
        self.bucket_name = "uniflow-files"
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        try:
            s3 = get_s3_client()
            s3.head_bucket(Bucket=self.bucket_name)
        except Exception:
            try:
                s3 = get_s3_client()
                s3.create_bucket(Bucket=self.bucket_name)
            except Exception:
                pass

    def upload_file(
        self,
        file_content: BinaryIO,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = "uploads"
    ) -> dict:
        s3 = get_s3_client()
        file_ext = os.path.splitext(filename)[1]
        unique_filename = f"{folder}/{uuid.uuid4()}{file_ext}"

        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        s3.upload_fileobj(
            file_content,
            self.bucket_name,
            unique_filename,
            ExtraArgs=extra_args
        )

        file_url = f"{settings.s3_bucket_url}/{self.bucket_name}/{unique_filename}"
        return {
            "filename": unique_filename,
            "original_filename": filename,
            "url": file_url,
            "size": file_content.tell() if hasattr(file_content, 'tell') else 0,
            "content_type": content_type
        }

    def upload_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: Optional[str] = None,
        folder: str = "uploads"
    ) -> dict:
        import io
        file_obj = io.BytesIO(file_bytes)
        return self.upload_file(file_obj, filename, content_type, folder)

    def delete_file(self, filename: str) -> bool:
        try:
            s3 = get_s3_client()
            s3.delete_object(Bucket=self.bucket_name, Key=filename)
            return True
        except Exception:
            return False

    def get_file_url(self, filename: str, expires_in: int = 3600) -> str:
        s3 = get_s3_client()
        return s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket_name, 'Key': filename},
            ExpiresIn=expires_in
        )

    def list_files(self, folder: str = "uploads", max_keys: int = 100) -> list:
        s3 = get_s3_client()
        response = s3.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=folder,
            MaxKeys=max_keys
        )
        return response.get('Contents', [])


storage_service = SupabaseStorageService()


def get_storage_service() -> SupabaseStorageService:
    return storage_service