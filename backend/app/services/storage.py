"""MinIO/S3-compatible object storage."""

from datetime import timedelta
from io import BytesIO
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.utils.logger import create_logger

logger = create_logger(__name__)


class StorageService:
    def __init__(self) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info(f"Created bucket: {self._bucket}")
        except S3Error as e:
            logger.error(f"Failed to create bucket: {e}")
            raise

    def upload_file(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        try:
            self._client.put_object(
                self._bucket,
                path,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return path
        except S3Error as e:
            logger.error(f"Failed to upload file: {e}")
            raise

    def upload_stream(
        self,
        path: str,
        stream: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        try:
            self._client.put_object(
                self._bucket,
                path,
                stream,
                length=length,
                content_type=content_type,
            )
            return path
        except S3Error as e:
            logger.error(f"Failed to upload stream: {e}")
            raise

    def download_file(self, path: str) -> bytes:
        try:
            response = self._client.get_object(self._bucket, path)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"Failed to download file: {e}")
            raise

    def delete_file(self, path: str) -> None:
        try:
            self._client.remove_object(self._bucket, path)
        except S3Error as e:
            logger.error(f"Failed to delete file: {e}")
            raise

    def get_presigned_url(self, path: str, expires_hours: int = 1) -> str:
        try:
            return self._client.presigned_get_object(
                self._bucket,
                path,
                expires=timedelta(hours=expires_hours),
            )
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise


_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
