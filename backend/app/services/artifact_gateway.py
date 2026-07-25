"""Synchronous agent tools backed by one authenticated chat artifact catalog."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO

import pandas as pd
from matplotlib.figure import Figure
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Artifact, ArtifactSource, Chat, User
from app.services.file_validation import (
    CSV_MEDIA_TYPE,
    GENERATED_MEDIA_TYPES,
    XLSX_MEDIA_TYPE,
    sanitize_display_filename,
    validate_and_reencode_raster,
    validate_csv_stream,
    validate_pdf,
    validate_utf8_text,
    validate_xlsx_stream,
)
from app.services.storage import StorageService, get_storage_service

MAX_LIST_LIMIT = 200
DEFAULT_LIST_LIMIT = 100
MAX_HEAD_ROWS = 1_000
MAX_PARSED_CELLS = int(getattr(settings, "max_artifact_parsed_cells", 1_000_000))
SPOOL_BYTES = int(getattr(settings, "upload_spool_bytes", 8 * 1024 * 1024))
CHUNK_BYTES = 1024 * 1024


class ArtifactGatewayError(ValueError):
    """A safe artifact tool error."""


@dataclass(slots=True)
class CatalogEntry:
    ref: str
    filename: str
    source: ArtifactSource
    content_type: str
    size: int
    sha256: str
    created_at: datetime
    storage_path: str | None = None
    local_path: Path | None = None


def _ref(identifier: uuid.UUID) -> str:
    return f"artifact_{identifier.hex}"


def _binary_data(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if hasattr(value, "read"):
        position = value.tell() if hasattr(value, "tell") else None
        raw = value.read()
        if position is not None and hasattr(value, "seek"):
            value.seek(position)
        return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    raise ArtifactGatewayError("Artifact data must be a supported value or binary buffer")


def _write_bytes(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


class ChatArtifactGateway:
    def __init__(
        self,
        entries: list[CatalogEntry],
        output_directory: Path,
        *,
        storage: StorageService | None = None,
        db: AsyncSession | None = None,
        user_id: uuid.UUID | None = None,
        chat_id: uuid.UUID | None = None,
    ) -> None:
        self._entries = entries
        self._output_directory = output_directory.resolve(strict=True)
        self._storage = storage or get_storage_service()
        self._loop = asyncio.get_running_loop()
        self._buffers: list[BinaryIO] = []
        self._lock = threading.RLock()
        self._generated_bytes = 0
        self._db = db
        self._user_id = user_id
        self._chat_id = chat_id

    def uploaded_prompt_entries(self) -> list[dict[str, Any]]:
        """Safe uploaded-file metadata for the system prompt (current chat only)."""
        with self._lock:
            return [
                {
                    "filename": entry.filename,
                    "ref": entry.ref,
                    "content_type": entry.content_type,
                    "size": entry.size,
                }
                for entry in self._entries
                if entry.source == ArtifactSource.UPLOAD
            ]

    def _find_generated_by_filename(self, filename: str) -> CatalogEntry | None:
        matches = [
            entry
            for entry in self._entries
            if entry.source == ArtifactSource.GENERATED and entry.filename == filename
        ]
        if not matches:
            return None
        for entry in matches:
            if entry.local_path is not None:
                return entry
        return matches[0]

    def _drop_other_generated_with_filename(
        self, filename: str, keep: CatalogEntry
    ) -> None:
        self._entries = [
            entry
            for entry in self._entries
            if not (
                entry.source == ArtifactSource.GENERATED
                and entry.filename == filename
                and entry is not keep
            )
        ]

    def list_artifacts(
        self,
        source: str = "all",
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        *,
        detail: bool = False,
    ) -> dict[str, Any]:
        if source not in {"all", "upload", "generated"}:
            raise ArtifactGatewayError("source must be all, upload, or generated")
        if not 1 <= limit <= MAX_LIST_LIMIT:
            raise ArtifactGatewayError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
        try:
            offset = int(cursor or "0")
        except ValueError as exc:
            raise ArtifactGatewayError("cursor is invalid") from exc
        if offset < 0:
            raise ArtifactGatewayError("cursor is invalid")
        with self._lock:
            matching = [
                entry
                for entry in self._entries
                if source == "all" or entry.source.value == source
            ]
            page = matching[offset : offset + limit]
        next_cursor = (
            str(offset + limit) if offset + limit < len(matching) else None
        )
        if not detail:
            return {
                "filenames": [entry.filename for entry in page],
                "next_cursor": next_cursor,
            }
        return {
            "items": [
                {
                    "ref": entry.ref,
                    "filename": entry.filename,
                    "source": entry.source.value,
                    "content_type": entry.content_type,
                    "size": entry.size,
                    "sha256": entry.sha256,
                    "created_at": entry.created_at.isoformat(),
                }
                for entry in page
            ],
            "next_cursor": next_cursor,
        }

    def _resolve(self, ref: str) -> CatalogEntry:
        with self._lock:
            direct = [entry for entry in self._entries if entry.ref == ref]
            if direct:
                return direct[0]
            named = [entry for entry in self._entries if entry.filename == ref]
        if not named:
            raise ArtifactGatewayError("Artifact was not found in the current chat")
        if len(named) > 1:
            raise ArtifactGatewayError("Artifact filename is ambiguous; use its opaque ref")
        return named[0]

    async def _download(self, entry: CatalogEntry) -> BinaryIO:
        spool = SpooledTemporaryFile(max_size=SPOOL_BYTES, mode="w+b")
        digest = hashlib.sha256()
        written = 0
        try:
            if entry.local_path is not None:
                stream = entry.local_path.open("rb")
                try:
                    while chunk := stream.read(CHUNK_BYTES):
                        written += len(chunk)
                        if written > entry.size:
                            raise ArtifactGatewayError("Artifact size does not match metadata")
                        digest.update(chunk)
                        spool.write(chunk)
                finally:
                    stream.close()
            else:
                assert entry.storage_path is not None
                stream = await self._storage.open_download(entry.storage_path)
                async for chunk in stream:
                    written += len(chunk)
                    if written > entry.size:
                        raise ArtifactGatewayError("Artifact size does not match metadata")
                    digest.update(chunk)
                    spool.write(chunk)
            if written != entry.size or digest.hexdigest() != entry.sha256:
                raise ArtifactGatewayError("Artifact hash or size verification failed")
            spool.seek(0)
            return spool
        except Exception:
            spool.close()
            raise

    def _materialize(self, entry: CatalogEntry) -> BinaryIO:
        future = asyncio.run_coroutine_threadsafe(self._download(entry), self._loop)
        return future.result(timeout=120)

    def read_artifact(
        self,
        ref: str,
        mode: str = "auto",
        rows: int = 20,
        sheet_name: str | int = 0,
    ) -> pd.DataFrame | BinaryIO:
        if mode not in {"auto", "head", "full", "buffer"}:
            raise ArtifactGatewayError("mode must be auto, head, full, or buffer")
        if not 1 <= rows <= MAX_HEAD_ROWS:
            raise ArtifactGatewayError(f"rows must be between 1 and {MAX_HEAD_ROWS}")
        entry = self._resolve(ref)
        is_tabular = entry.content_type in {CSV_MEDIA_TYPE, XLSX_MEDIA_TYPE}
        if mode == "head" and not is_tabular:
            raise ArtifactGatewayError("head mode is available only for CSV and XLSX")
        buffer = self._materialize(entry)
        if mode == "buffer" or (mode in {"auto", "full"} and not is_tabular):
            with self._lock:
                self._buffers.append(buffer)
            return buffer
        try:
            nrows = rows if mode in {"auto", "head"} else None
            if entry.content_type == CSV_MEDIA_TYPE:
                frame = pd.read_csv(buffer, nrows=nrows)
            else:
                frame = pd.read_excel(buffer, sheet_name=sheet_name, nrows=nrows)
            if not isinstance(frame, pd.DataFrame):
                raise ArtifactGatewayError("sheet_name must identify exactly one worksheet")
            if frame.size > MAX_PARSED_CELLS:
                raise ArtifactGatewayError(
                    "Spreadsheet is too large to parse fully; use mode='buffer' and chunked processing"
                )
            return frame
        finally:
            buffer.close()

    def _serialize(self, suffix: str, data: Any) -> tuple[bytes, str, int | None, int | None]:
        media_type = GENERATED_MEDIA_TYPES[suffix]
        width: int | None = None
        height: int | None = None
        if suffix == ".csv":
            raw = data.to_csv(index=False).encode("utf-8") if isinstance(data, pd.DataFrame) else (
                data.encode("utf-8") if isinstance(data, str) else _binary_data(data)
            )
            validate_csv_stream(BytesIO(raw))
        elif suffix == ".xlsx":
            if isinstance(data, pd.DataFrame):
                output = BytesIO()
                data.to_excel(output, index=False)
                raw = output.getvalue()
            else:
                raw = _binary_data(data)
            validate_xlsx_stream(BytesIO(raw))
        elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            if isinstance(data, Figure):
                output = BytesIO()
                data.savefig(output, format="jpeg" if suffix in {".jpg", ".jpeg"} else suffix[1:])
                raw = output.getvalue()
            elif isinstance(data, Image.Image):
                output = BytesIO()
                data.save(output, format="JPEG" if suffix in {".jpg", ".jpeg"} else suffix[1:].upper())
                raw = output.getvalue()
            else:
                raw = _binary_data(data)
            image = validate_and_reencode_raster(raw, suffix)
            raw, width, height = image.data, image.width, image.height
        elif suffix == ".json":
            if isinstance(data, (dict, list)):
                raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            else:
                raw = data.encode("utf-8") if isinstance(data, str) else _binary_data(data)
            raw = validate_utf8_text(raw, json_document=True)
        elif suffix == ".txt":
            raw = data.encode("utf-8") if isinstance(data, str) else _binary_data(data)
            raw = validate_utf8_text(raw)
        elif suffix == ".pdf":
            raw = validate_pdf(_binary_data(data))
        else:
            raise ArtifactGatewayError("Generated artifact type is not supported")
        return raw, media_type, width, height

    def save_artifact(
        self, filename: str, data: Any, media_type: str | None = None
    ) -> dict[str, Any]:
        safe_name = sanitize_display_filename(filename, fallback="artifact")
        suffix = Path(safe_name).suffix.lower()
        if suffix not in GENERATED_MEDIA_TYPES:
            raise ArtifactGatewayError("Generated artifact type is not supported")
        raw, detected_type, width, height = self._serialize(suffix, data)
        if media_type is not None and media_type != detected_type:
            raise ArtifactGatewayError("Declared media type does not match file content")
        maximum = int(settings.max_generated_file_bytes)
        if len(raw) > maximum:
            raise ArtifactGatewayError("Generated artifact exceeds the per-file quota")
        digest = hashlib.sha256(raw).hexdigest()
        with self._lock:
            existing = self._find_generated_by_filename(safe_name)
            upload_clash = next(
                (
                    entry
                    for entry in self._entries
                    if entry.source == ArtifactSource.UPLOAD
                    and entry.filename == safe_name
                ),
                None,
            )
            if upload_clash is not None:
                raise ArtifactGatewayError(
                    f"Cannot overwrite uploaded artifact '{safe_name}'. "
                    "Choose a different filename."
                )
            if existing is not None:
                old_size = existing.size if existing.local_path is not None else 0
                byte_delta = len(raw) - old_size
                if self._generated_bytes + byte_delta > int(settings.max_generated_run_bytes):
                    raise ArtifactGatewayError(
                        "Generated artifacts exceed the run byte quota"
                    )
                if existing.local_path is not None:
                    target = existing.local_path
                else:
                    target = self._output_directory / safe_name
                    resolved_parent = target.parent.resolve(strict=True)
                    if resolved_parent != self._output_directory or target.is_symlink():
                        raise ArtifactGatewayError("Unsafe generated artifact path")
                    local_count = len(
                        [item for item in self._entries if item.local_path is not None]
                    )
                    if local_count >= int(settings.max_generated_files_per_run):
                        raise ArtifactGatewayError(
                            "Generated artifact count exceeds the run quota"
                        )
                _write_bytes(target, raw)
                existing.filename = safe_name
                existing.content_type = detected_type
                existing.size = len(raw)
                existing.sha256 = digest
                existing.created_at = datetime.now(timezone.utc)
                existing.local_path = target
                self._generated_bytes += byte_delta
                self._drop_other_generated_with_filename(safe_name, existing)
                if existing in self._entries:
                    self._entries.remove(existing)
                self._entries.insert(0, existing)
                entry = existing
            else:
                if len(
                    [item for item in self._entries if item.local_path is not None]
                ) >= int(settings.max_generated_files_per_run):
                    raise ArtifactGatewayError(
                        "Generated artifact count exceeds the run quota"
                    )
                if self._generated_bytes + len(raw) > int(settings.max_generated_run_bytes):
                    raise ArtifactGatewayError(
                        "Generated artifacts exceed the run byte quota"
                    )
                identifier = uuid.uuid4()
                target = self._output_directory / safe_name
                resolved_parent = target.parent.resolve(strict=True)
                if resolved_parent != self._output_directory or target.is_symlink():
                    raise ArtifactGatewayError("Unsafe generated artifact path")
                if target.exists():
                    raise ArtifactGatewayError(
                        "Generated artifact path already exists without a catalog entry"
                    )
                _write_bytes(target, raw)
                entry = CatalogEntry(
                    ref=_ref(identifier),
                    filename=safe_name,
                    source=ArtifactSource.GENERATED,
                    content_type=detected_type,
                    size=len(raw),
                    sha256=digest,
                    created_at=datetime.now(timezone.utc),
                    local_path=target,
                )
                self._entries.insert(0, entry)
                self._generated_bytes += len(raw)
        result: dict[str, Any] = {
            "kind": "generated_artifact",
            "ref": entry.ref,
            "filename": entry.filename,
            "content_type": entry.content_type,
            "size": entry.size,
            "sha256": entry.sha256,
        }
        if width is not None and height is not None:
            result.update({"width": width, "height": height})
        return result

    async def _durable_delete(self, entry: CatalogEntry) -> None:
        """Wipe MinIO (if any), then the Postgres row for a generated artifact."""
        if entry.storage_path:
            await self._storage.delete_file(entry.storage_path)
        if (
            self._db is None
            or self._user_id is None
            or self._chat_id is None
        ):
            return
        try:
            artifact_id = uuid.UUID(hex=entry.ref.removeprefix("artifact_"))
        except ValueError:
            return
        result = await self._db.execute(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.user_id == self._user_id,
                Artifact.chat_id == self._chat_id,
                Artifact.source == ArtifactSource.GENERATED,
            )
        )
        artifact = result.scalar_one_or_none()
        if artifact is None:
            return
        await self._db.delete(artifact)
        await self._db.flush()

    def delete_artifact(self, ref: str) -> dict[str, Any]:
        """Delete a generated artifact by filename or opaque ref. Uploads are refused."""
        entry = self._resolve(ref)
        if entry.source != ArtifactSource.GENERATED:
            raise ArtifactGatewayError(
                "Only generated artifacts can be deleted; uploads cannot be removed "
                "with delete_artifact"
            )
        future = asyncio.run_coroutine_threadsafe(
            self._durable_delete(entry), self._loop
        )
        future.result(timeout=120)
        with self._lock:
            if entry in self._entries:
                self._entries.remove(entry)
            if entry.local_path is not None:
                path = entry.local_path
                try:
                    resolved = path.resolve(strict=False)
                    if (
                        resolved.parent == self._output_directory
                        and resolved.is_file()
                        and not resolved.is_symlink()
                    ):
                        resolved.unlink(missing_ok=True)
                except OSError:
                    pass
                self._generated_bytes = max(0, self._generated_bytes - entry.size)
        return {
            "deleted": True,
            "ref": entry.ref,
            "filename": entry.filename,
        }

    def close(self) -> None:
        with self._lock:
            buffers, self._buffers = self._buffers, []
        for buffer in buffers:
            buffer.close()


async def create_chat_artifact_gateway(
    db: AsyncSession,
    user: User,
    chat: Chat,
    output_directory: Path,
    *,
    storage: StorageService | None = None,
) -> ChatArtifactGateway:
    result = await db.execute(
        select(Artifact)
        .where(Artifact.user_id == user.id, Artifact.chat_id == chat.id)
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    entries = [
        CatalogEntry(
            ref=_ref(artifact.id),
            filename=artifact.filename,
            source=artifact.source,
            content_type=artifact.content_type,
            size=artifact.file_size,
            sha256=artifact.sha256,
            created_at=artifact.created_at,
            storage_path=artifact.storage_path,
        )
        for artifact in result.scalars().all()
    ]
    return ChatArtifactGateway(
        entries,
        output_directory,
        storage=storage,
        db=db,
        user_id=user.id,
        chat_id=chat.id,
    )


_gateway: contextvars.ContextVar[ChatArtifactGateway | None] = contextvars.ContextVar(
    "chat_artifact_gateway", default=None
)


@contextmanager
def bind_chat_artifact_gateway(gateway: ChatArtifactGateway) -> Iterator[None]:
    token = _gateway.set(gateway)
    try:
        yield
    finally:
        _gateway.reset(token)


def _current() -> ChatArtifactGateway:
    gateway = _gateway.get()
    if gateway is None:
        raise RuntimeError("Artifact tools are not bound to an active chat run")
    return gateway


def list_artifacts(
    source: str = "all",
    limit: int = DEFAULT_LIST_LIMIT,
    cursor: str | None = None,
    detail: bool = False,
) -> dict[str, Any]:
    """
    List artifacts available in the current chat without exposing storage paths.

    By default returns only filenames (enough for read_artifact / save_artifact).
    Pass detail=True when you need refs, sizes, content types, or sources.

    Filenames are unique within a chat, so read_artifact(filename) is sufficient.

    ARGS:
        source (str):
            Filter by origin. One of: 'all' (default), 'upload', or 'generated'.
        limit (int):
            Page size. Defaults to 100. Must be between 1 and 200 inclusive.
        cursor (Optional[str]):
            Pagination token from a previous call's next_cursor.
            Pass None (default) to start from the beginning.
        detail (bool):
            False (default): return filenames only.
            True: return full metadata items including ref, source, size, etc.

    RETURNS:
        When detail=False (default):
            Dict with:
                - filenames (List[str]): Display names in this chat
                - next_cursor (Optional[str]): Continue token, or None
        When detail=True:
            Dict with:
                - items (List[Dict]): Each item contains ref, filename, source,
                  content_type, size, sha256, created_at
                - next_cursor (Optional[str]): Continue token, or None

    CRITICAL RULES:
        - Prefer filenames for read_artifact; refs are optional
        - Do not invent storage paths or URLs
    """
    return _current().list_artifacts(source, limit, cursor, detail=detail)


def read_artifact(
    ref: str,
    mode: str = "auto",
    rows: int = 20,
    sheet_name: str | int = 0,
) -> pd.DataFrame | BinaryIO:
    """
    Read an artifact by exact filename (preferred) or opaque ref.

    Filenames are unique per chat, so passing the filename alone is enough.
    Opaque refs (artifact_<hex>) still work and are used by the HTTP API.

    ARGS:
        ref (str):
            Exact filename from list_artifacts (preferred), or opaque
            artifact_<hex> ref.
        mode (str):
            One of:
                - 'auto' (default): CSV/XLSX → bounded DataFrame (rows);
                  other types → seekable BinaryIO buffer
                - 'head': CSV/XLSX only → DataFrame limited to rows
                - 'full': CSV/XLSX → full DataFrame within the cell limit
                - 'buffer': any type → seekable BinaryIO of verified raw bytes
        rows (int):
            Max rows for auto/head tabular reads. Defaults to 20.
            Must be between 1 and 1000 inclusive.
        sheet_name (str | int):
            Worksheet for XLSX reads. Defaults to 0 (first sheet).
            Must resolve to exactly one sheet.

    RETURNS:
        pandas.DataFrame for successful tabular auto/head/full reads, or a
        seekable BinaryIO buffer for buffer mode and non-tabular auto/full.

    CRITICAL RULES:
        - Prefer filename from list_artifacts(); refs are optional
        - Never put raw bytes, base64, or full file dumps in final_answer
        - For large tables, prefer head/auto or buffer with chunked processing
    """
    return _current().read_artifact(ref, mode, rows, sheet_name)


def save_artifact(
    filename: str, data: Any, media_type: str | None = None
) -> dict[str, Any]:
    """
    Create or overwrite a current-chat generated artifact and return its handle.

    The sanitized filename is kept exactly. If a generated artifact with that
    name already exists in this chat, it is overwritten. If an uploaded file
    already uses that name, the call fails — choose a different name.

    ARGS:
        filename (str):
            Desired display name including extension. Supported extensions:
            .csv, .xlsx, .png, .jpg/.jpeg, .webp, .json, .txt, .pdf.
            Must be unique among uploads in this chat.
        data (Any):
            Content matched to the extension, for example:
                - .csv / .xlsx: pandas.DataFrame (preferred), str, or bytes
                - .png / .jpg / .jpeg / .webp: matplotlib Figure, PIL Image,
                  or raw image bytes
                - .json: dict/list (preferred), str, or bytes
                - .txt: str (preferred) or bytes
                - .pdf: raw PDF bytes or a file-like object
        media_type (Optional[str]):
            Declared MIME type. When supplied, must match the validated format.
            Omit to detect from the filename extension and content.

    RETURNS:
        Dict with:
            - kind (str): Always 'generated_artifact'
            - ref (str): Opaque handle (for APIs; filename is enough in code)
            - filename (str): Exact sanitized filename
            - content_type (str): Validated MIME type
            - size (int): Byte size
            - sha256 (str): Content digest
            - width / height (Optional[int]): Present for raster images

    CRITICAL RULES:
        - Overwrites same-name generated artifacts in this chat
        - Never overwrites uploads; never touches other chats/users
        - Do not put refs or storage paths in final_answer
    """
    return _current().save_artifact(filename, data, media_type)


def delete_artifact(ref: str) -> dict[str, Any]:
    """
    Delete a generated artifact from the current chat by filename or opaque ref.

    Only artifacts created by save_artifact (source=generated) can be deleted.
    Uploaded user files cannot be deleted with this tool.

    ARGS:
        ref (str):
            Exact filename from list_artifacts (preferred), or opaque
            artifact_<hex> ref.

    RETURNS:
        Dict with:
            - deleted (bool): Always True on success
            - ref (str): Opaque handle of the removed artifact
            - filename (str): Display name that was deleted

    CRITICAL RULES:
        - Generated only; never deletes uploads
        - Prefer filename; refs are optional
        - Do not invent storage paths or URLs
    """
    return _current().delete_artifact(ref)
