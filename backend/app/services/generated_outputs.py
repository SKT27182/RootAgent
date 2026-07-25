"""Collection, validation, and durable persistence of executor-generated files."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor_interface import OutputManifest
from app.core.config import settings
from app.db.models import Artifact, ArtifactOutputKind, ArtifactSource, User
from app.models.chat import ArtifactEventMetadata
from app.schemas.artifact import ArtifactResponse
from app.services import artifact_service
from app.services.file_validation import (
    CSV_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    JPEG_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    PNG_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    WEBP_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    FileValidationError,
    sanitize_display_filename,
    validate_and_reencode_raster,
    validate_csv_stream,
    validate_pdf,
    validate_utf8_text,
    validate_xlsx_stream,
)
from app.services.storage import StorageService, get_storage_service
from app.utils.logger import create_logger
from app.core.metrics import GENERATED_OUTPUT_BYTES

logger = create_logger(__name__)

MIB = 1024 * 1024
MAX_GENERATED_FILES = int(
    getattr(settings, "max_generated_files_per_run", 20)
)
MAX_GENERATED_FILE_BYTES = int(
    getattr(settings, "max_generated_file_bytes", 50 * MIB)
)
MAX_GENERATED_RUN_BYTES = int(
    getattr(settings, "max_generated_run_bytes", 100 * MIB)
)
_CHUNK_BYTES = 1024 * 1024

_OUTPUT_TYPES = {
    ".png": (PNG_MEDIA_TYPE, ArtifactOutputKind.PNG),
    ".csv": (CSV_MEDIA_TYPE, ArtifactOutputKind.CSV),
    ".xlsx": (XLSX_MEDIA_TYPE, ArtifactOutputKind.XLSX),
    ".jpg": (JPEG_MEDIA_TYPE, None),
    ".jpeg": (JPEG_MEDIA_TYPE, None),
    ".webp": (WEBP_MEDIA_TYPE, None),
    ".json": (JSON_MEDIA_TYPE, None),
    ".txt": (TEXT_MEDIA_TYPE, None),
    ".pdf": (PDF_MEDIA_TYPE, None),
}


class OutputWorkspace(Protocol):
    output_directory: Path


class GeneratedOutputError(ValueError):
    """A stable, client-safe generated-output rejection."""

    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class CollectedGeneratedOutput:
    path: Path
    output_kind: ArtifactOutputKind | None
    manifest: OutputManifest


@dataclass(frozen=True, slots=True)
class PersistedGeneratedOutput:
    artifact: Artifact
    metadata: ArtifactResponse
    event_metadata: ArtifactEventMetadata


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_with_validated_data(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _contained_regular_files(output_directory: Path) -> tuple[Path, list[Path]]:
    if output_directory.is_symlink():
        raise GeneratedOutputError(
            "unsafe_generated_output", "Executor output directory cannot be a symlink"
        )
    try:
        root = output_directory.resolve(strict=True)
    except FileNotFoundError as exc:
        raise GeneratedOutputError(
            "invalid_generated_output", "Executor output directory does not exist"
        ) from exc
    if not root.is_dir():
        raise GeneratedOutputError(
            "invalid_generated_output", "Executor output path is not a directory"
        )

    files: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise GeneratedOutputError(
                "unsafe_generated_output", "Generated output symlinks are rejected"
            )
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise GeneratedOutputError(
                "unsafe_generated_output", "Generated outputs must be regular files"
            )
        try:
            candidate.resolve(strict=True).relative_to(root)
        except ValueError as exc:
            raise GeneratedOutputError(
                "unsafe_generated_output", "Generated output escaped the workspace"
            ) from exc
        files.append(candidate)
    return root, files


def _collect_generated_outputs_sync(
    output_directory: Path,
    *,
    max_files: int,
    max_file_bytes: int,
    max_run_bytes: int,
) -> tuple[CollectedGeneratedOutput, ...]:
    root, files = _contained_regular_files(output_directory)
    if len(files) > max_files:
        raise GeneratedOutputError(
            "generated_output_quota_exceeded",
            f"Executor produced more than {max_files} output files",
            status_code=413,
        )

    original_total = sum(path.stat().st_size for path in files)
    if original_total > max_run_bytes:
        raise GeneratedOutputError(
            "generated_output_quota_exceeded",
            "Executor outputs exceed the per-run byte limit",
            status_code=413,
        )

    collected: list[CollectedGeneratedOutput] = []
    persisted_total = 0
    used_names: set[str] = set()
    for path in files:
        size = path.stat().st_size
        if size > max_file_bytes:
            raise GeneratedOutputError(
                "generated_output_too_large",
                "An executor output exceeds the per-file byte limit",
                status_code=413,
            )
        suffix = path.suffix.lower()
        output_type = _OUTPUT_TYPES.get(suffix)
        if output_type is None:
            raise GeneratedOutputError(
                "unsupported_generated_output",
                "Generated output type is not supported",
            )
        media_type, output_kind = output_type

        width: int | None = None
        height: int | None = None
        try:
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                with path.open("rb") as handle:
                    source = handle.read(max_file_bytes + 1)
                validated_image = validate_and_reencode_raster(source, suffix)
                _replace_with_validated_data(path, validated_image.data)
                size = validated_image.size
                digest = validated_image.sha256
                width, height = validated_image.width, validated_image.height
            elif suffix in {".csv", ".xlsx"}:
                with path.open("rb") as handle:
                    if output_kind is ArtifactOutputKind.CSV:
                        validate_csv_stream(handle)
                    else:
                        validate_xlsx_stream(handle)
                size = path.stat().st_size
                digest = _digest_file(path)
            else:
                source = path.read_bytes()
                if suffix == ".json":
                    normalized = validate_utf8_text(source, json_document=True)
                elif suffix == ".txt":
                    normalized = validate_utf8_text(source)
                elif suffix == ".pdf":
                    normalized = validate_pdf(source)
                else:  # guarded by _OUTPUT_TYPES
                    raise FileValidationError(
                        "unsupported_generated_output", "Unsupported generated output"
                    )
                if normalized != source:
                    _replace_with_validated_data(path, normalized)
                size = len(normalized)
                digest = hashlib.sha256(normalized).hexdigest()
        except FileValidationError as exc:
            raise GeneratedOutputError(exc.code, exc.message) from exc

        persisted_total += size
        if persisted_total > max_run_bytes:
            raise GeneratedOutputError(
                "generated_output_quota_exceeded",
                "Validated executor outputs exceed the per-run byte limit",
                status_code=413,
            )

        display_name = sanitize_display_filename(path.name, fallback=f"output{suffix}")
        if display_name in used_names:
            display_name = f"{Path(display_name).stem}_{digest[:12]}{suffix}"
        used_names.add(display_name)
        relative = path.resolve(strict=True).relative_to(root)
        collected.append(
            CollectedGeneratedOutput(
                path=path,
                output_kind=output_kind,
                manifest=OutputManifest(
                    safe_name=display_name,
                    relative_path=(Path("outputs") / relative).as_posix(),
                    media_type=media_type,
                    size=size,
                    sha256=digest,
                    creation_source="code_executor",
                    width=width,
                    height=height,
                ),
            )
        )
    return tuple(collected)


async def collect_generated_outputs(
    workspace: OutputWorkspace,
    *,
    max_files: int = MAX_GENERATED_FILES,
    max_file_bytes: int = MAX_GENERATED_FILE_BYTES,
    max_run_bytes: int = MAX_GENERATED_RUN_BYTES,
) -> tuple[CollectedGeneratedOutput, ...]:
    """Collect and content-validate all regular files in a run output directory."""
    return await asyncio.to_thread(
        _collect_generated_outputs_sync,
        Path(workspace.output_directory),
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_run_bytes=max_run_bytes,
    )


def _generated_object_key(
    user_id: uuid.UUID, chat_id: uuid.UUID, artifact_id: uuid.UUID
) -> str:
    """MinIO key for generated artifacts: {user}/{chat}/generated/{artifact}."""
    return artifact_service.storage_path(
        user_id, chat_id, artifact_id, source=ArtifactSource.GENERATED
    )


def _verify_unchanged(output: CollectedGeneratedOutput) -> None:
    path = output.path
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
        raise GeneratedOutputError(
            "unsafe_generated_output", "Generated output changed before persistence"
        )
    if path.stat().st_size != output.manifest.size:
        raise GeneratedOutputError(
            "invalid_generated_output", "Generated output size changed before persistence"
        )
    if _digest_file(path) != output.manifest.sha256:
        raise GeneratedOutputError(
            "invalid_generated_output", "Generated output hash changed before persistence"
        )


async def persist_generated_outputs(
    db: AsyncSession,
    user: User,
    session_id: uuid.UUID | str,
    run_id: uuid.UUID,
    outputs: tuple[CollectedGeneratedOutput, ...] | list[CollectedGeneratedOutput],
    *,
    storage: StorageService | None = None,
) -> list[PersistedGeneratedOutput]:
    """Persist a validated run batch before its terminal event is emitted.

    Object keys use {user_id}/{chat_id}/generated/{artifact_id}. Same-chat
    generated artifacts that share a filename are overwritten in place
    (uploads and other chats are never touched). Retry-time digest dedupe is
    scoped by run_id in Postgres, not by the object-key prefix.
    """
    storage = storage or get_storage_service()
    chat = await artifact_service.get_owned_chat(db, user.id, session_id)
    result = await db.execute(
        select(Artifact)
        .where(
            Artifact.user_id == user.id,
            Artifact.chat_id == chat.id,
            Artifact.source == ArtifactSource.GENERATED,
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    all_generated = list(result.scalars().all())
    same_run = [artifact for artifact in all_generated if artifact.run_id == run_id]
    by_digest = {artifact.sha256: artifact for artifact in same_run}
    by_filename: dict[str, list[Artifact]] = {}
    for artifact in all_generated:
        by_filename.setdefault(artifact.filename, []).append(artifact)

    ordered: list[Artifact] = []
    uploaded_keys: list[str] = []
    touched: list[Artifact] = []
    seen: set[str] = set()
    try:
        for output in outputs:
            digest = output.manifest.sha256
            if digest in seen:
                continue
            seen.add(digest)
            if digest in by_digest:
                ordered.append(by_digest[digest])
                continue

            _verify_unchanged(output)
            prior = by_filename.get(output.manifest.safe_name, [])
            if prior:
                artifact = prior[0]
                object_key = _generated_object_key(user.id, chat.id, artifact.id)
                with output.path.open("rb") as stream:
                    await storage.upload_stream(
                        object_key,
                        stream,
                        output.manifest.size,
                        output.manifest.media_type,
                    )
                uploaded_keys.append(object_key)
                obsolete_now: list[str] = []
                if artifact.storage_path and artifact.storage_path != object_key:
                    obsolete_now.append(artifact.storage_path)
                for extra in prior[1:]:
                    if extra.storage_path:
                        obsolete_now.append(extra.storage_path)
                # MinIO first for replaced/duplicate objects, then drop Postgres rows.
                for object_key_obsolete in obsolete_now:
                    await storage.delete_file(object_key_obsolete)
                for extra in prior[1:]:
                    await db.delete(extra)
                artifact.run_id = run_id
                artifact.filename = output.manifest.safe_name
                artifact.content_type = output.manifest.media_type
                artifact.storage_path = object_key
                artifact.file_size = output.manifest.size
                artifact.sha256 = digest
                artifact.output_kind = output.output_kind
                artifact.width = output.manifest.width
                artifact.height = output.manifest.height
                by_filename[output.manifest.safe_name] = [artifact]
                by_digest[digest] = artifact
                touched.append(artifact)
                ordered.append(artifact)
            else:
                artifact_id = uuid.uuid4()
                object_key = _generated_object_key(user.id, chat.id, artifact_id)
                with output.path.open("rb") as stream:
                    await storage.upload_stream(
                        object_key,
                        stream,
                        output.manifest.size,
                        output.manifest.media_type,
                    )
                uploaded_keys.append(object_key)
                artifact = Artifact(
                    id=artifact_id,
                    user_id=user.id,
                    chat_id=chat.id,
                    run_id=run_id,
                    filename=output.manifest.safe_name,
                    content_type=output.manifest.media_type,
                    storage_path=object_key,
                    file_size=output.manifest.size,
                    sha256=digest,
                    source=ArtifactSource.GENERATED,
                    output_kind=output.output_kind,
                    width=output.manifest.width,
                    height=output.manifest.height,
                )
                db.add(artifact)
                by_filename[output.manifest.safe_name] = [artifact]
                by_digest[digest] = artifact
                touched.append(artifact)
                ordered.append(artifact)

            GENERATED_OUTPUT_BYTES.labels(
                output.output_kind.value
                if output.output_kind is not None
                else Path(output.manifest.safe_name).suffix.lower().lstrip(".")
            ).observe(output.manifest.size)

        if touched:
            await db.commit()
            for artifact in touched:
                await db.refresh(artifact)
    except Exception:
        await db.rollback()
        for object_key in uploaded_keys:
            try:
                await storage.delete_file(object_key)
            except Exception:
                logger.warning(
                    "Failed to remove generated object after persistence rollback: %s",
                    object_key,
                    exc_info=True,
                )
        raise

    session_uuid = (
        session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(session_id)
    )
    return [
        PersistedGeneratedOutput(
            artifact=artifact,
            metadata=artifact_service.to_artifact_response(artifact, session_uuid),
            event_metadata=artifact_service.to_artifact_event_metadata(
                artifact, session_uuid
            ),
        )
        for artifact in ordered
    ]
