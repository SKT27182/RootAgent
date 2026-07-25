"""Async facade for the synchronous MinIO/S3-compatible client."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.utils.logger import create_logger

logger = create_logger(__name__)

_STORAGE_WORKERS = int(getattr(settings, "storage_threadpool_workers", 4))
_STORAGE_CHUNK_BYTES = int(getattr(settings, "storage_stream_chunk_bytes", 1024 * 1024))
_storage_executor = ThreadPoolExecutor(
    max_workers=max(1, _STORAGE_WORKERS), thread_name_prefix="minio"
)


class StorageService:
    def __init__(self, client: Minio | None = None) -> None:
        self._client = client or Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self._bucket = settings.minio_bucket
        self._bucket_ready = False
        self._bucket_lock = asyncio.Lock()

    async def _run(self, function, /, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _storage_executor, partial(function, *args, **kwargs)
        )

    async def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        async with self._bucket_lock:
            if self._bucket_ready:
                return
            try:
                exists = await self._run(self._client.bucket_exists, self._bucket)
                if not exists:
                    await self._run(self._client.make_bucket, self._bucket)
                    logger.info("Created artifact bucket: %s", self._bucket)
                self._bucket_ready = True
            except S3Error:
                logger.exception("Artifact bucket access failed")
                raise

    async def check_bucket_access(self) -> None:
        """Perform a fresh, non-cached bucket access check for readiness."""

        try:
            exists = await self._run(self._client.bucket_exists, self._bucket)
        except S3Error:
            logger.exception("Artifact bucket readiness check failed")
            raise
        if not exists:
            raise RuntimeError("Artifact bucket is unavailable")

    async def upload_file(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        return await self.upload_stream(path, BytesIO(data), len(data), content_type)

    async def upload_stream(
        self,
        path: str,
        stream: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        await self.ensure_bucket()
        try:
            await self._run(
                self._client.put_object,
                self._bucket,
                path,
                stream,
                length,
                content_type=content_type,
            )
            return path
        except S3Error:
            logger.exception("Artifact upload failed for object %s", path)
            raise

    async def stat_file(self, path: str):
        await self.ensure_bucket()
        return await self._run(self._client.stat_object, self._bucket, path)

    async def open_download(self, path: str) -> AsyncIterator[bytes]:
        """Open an object now and return an async, bounded-chunk response stream."""
        await self.ensure_bucket()
        try:
            response = await self._run(self._client.get_object, self._bucket, path)
        except S3Error:
            logger.exception("Artifact download failed for object %s", path)
            raise

        async def chunks() -> AsyncIterator[bytes]:
            try:
                while True:
                    chunk = await self._run(response.read, _STORAGE_CHUNK_BYTES)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await self._run(response.close)
                await self._run(response.release_conn)

        return chunks()

    async def download_file(self, path: str) -> bytes:
        """Compatibility helper for bounded objects; routes should stream instead."""
        chunks = bytearray()
        stream = await self.open_download(path)
        async for chunk in stream:
            chunks.extend(chunk)
        return bytes(chunks)

    async def delete_file(self, path: str) -> None:
        await self.ensure_bucket()
        try:
            await self._run(self._client.remove_object, self._bucket, path)
        except S3Error:
            logger.exception("Artifact deletion failed for object %s", path)
            raise

    def _delete_prefix_sync(self, prefix: str) -> int:
        """Delete every object under prefix. Returns number of objects removed."""
        normalized = prefix if prefix.endswith("/") else f"{prefix}/"
        removed = 0
        # list_objects is lazy; materialize names before removing.
        names = [
            obj.object_name
            for obj in self._client.list_objects(
                self._bucket, prefix=normalized, recursive=True
            )
            if obj.object_name
        ]
        for name in names:
            self._client.remove_object(self._bucket, name)
            removed += 1
        return removed

    async def delete_prefix(self, prefix: str) -> int:
        """Wipe a chat/user object tree from MinIO before Postgres cascades."""
        await self.ensure_bucket()
        try:
            return await self._run(self._delete_prefix_sync, prefix)
        except S3Error:
            logger.exception("Artifact prefix deletion failed for %s", prefix)
            raise


_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
