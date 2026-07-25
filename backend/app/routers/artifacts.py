"""Artifact upload, list, preview, download, delete."""

import uuid
import asyncio
import hashlib
import json
from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
import pandas as pd
from pypdf import PdfReader

from app.core.config import settings
from app.core.dependencies import DbSession, get_current_active_user
from app.db.models import User
from app.schemas.artifact import ArtifactResponse
from app.services import artifact_service
from app.services import session_service
from app.services.file_validation import FileValidationError, validate_upload
from app.services.file_validation import (
    CSV_MEDIA_TYPE,
    JPEG_MEDIA_TYPE,
    JSON_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    PNG_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    WEBP_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
)
from app.services.storage import get_storage_service
from app.services.redis_store import RedisStore, get_redis_store
from app.utils.logger import create_logger
from app.core.metrics import RATE_LIMIT_REJECTIONS, UPLOAD_REJECTIONS

logger = create_logger(__name__, level=settings.log_level)

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])

CurrentUser = Annotated[User, Depends(get_current_active_user)]


def _to_response(artifact, session_id: uuid.UUID) -> ArtifactResponse:
    return artifact_service.to_artifact_response(artifact, session_id)


def _content_disposition(filename: str, *, attachment: bool) -> str:
    disposition = "attachment" if attachment else "inline"
    ascii_name = filename.encode("ascii", "ignore").decode().strip() or "artifact"
    ascii_name = ascii_name.replace('"', "_").replace("\\", "_")
    encoded = quote(filename, safe="")
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


@router.post("/{session_id}", response_model=ArtifactResponse)
async def upload_artifact(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
    file: UploadFile = File(...),
) -> ArtifactResponse:
    if (
        await session_service.get_owned_session(db, current_user.id, session_id)
        is None
    ):
        raise HTTPException(status_code=404, detail="Session not found")
    rate = await redis_store.check_rate_limit(
        "upload",
        str(current_user.id),
        limit=settings.upload_rate_limit,
        window_seconds=settings.upload_rate_window_seconds,
    )
    if not rate.allowed:
        RATE_LIMIT_REJECTIONS.labels("upload").inc()
        raise HTTPException(
            status_code=429,
            detail="Too many uploads",
            headers={"Retry-After": str(rate.retry_after_seconds)},
        )
    try:
        validated = await validate_upload(file)
    except FileValidationError as exc:
        UPLOAD_REJECTIONS.labels(exc.code).inc()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    try:
        artifact = await artifact_service.create_artifact_from_stream(
            db=db,
            user=current_user,
            session_id=session_id,
            filename=validated.filename,
            content_type=validated.content_type,
            stream=validated.stream,
            file_size=validated.size,
            sha256=validated.sha256,
        )
    except artifact_service.DuplicateArtifactFilenameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        validated.close()
    logger.info(
        "Artifact uploaded: session=%s file=%s user=%s",
        session_id,
        file.filename,
        current_user.email,
    )
    return _to_response(artifact, session_id)


@router.get("/{session_id}", response_model=list[ArtifactResponse])
async def list_artifacts(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[ArtifactResponse]:
    artifacts = await artifact_service.list_artifacts_for_chat(
        db, current_user, session_id
    )
    return [_to_response(artifact, session_id) for artifact in artifacts]


@router.get("/{session_id}/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ArtifactResponse:
    artifact = await artifact_service.get_artifact_for_user(
        db, current_user, session_id, artifact_id
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _to_response(artifact, session_id)


async def _stream_artifact(
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    *,
    attachment: bool,
) -> StreamingResponse:
    artifact = await artifact_service.get_artifact_for_user(
        db, current_user, session_id, artifact_id
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    stream = await get_storage_service().open_download(artifact.storage_path)
    return StreamingResponse(
        stream,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": _content_disposition(
                artifact.filename, attachment=attachment
            ),
            "Content-Length": str(artifact.file_size),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{session_id}/{artifact_id}/content")
async def content_artifact(
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    artifact = await artifact_service.get_artifact_for_user(
        db, current_user, session_id, artifact_id
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.content_type not in {PNG_MEDIA_TYPE, JPEG_MEDIA_TYPE, WEBP_MEDIA_TYPE}:
        raise HTTPException(status_code=415, detail="Only validated images can be rendered inline")
    return await _stream_artifact(
        session_id, artifact_id, current_user, db, attachment=False
    )


async def _verified_bytes(artifact) -> bytes:
    maximum = int(settings.max_generated_file_bytes)
    output = bytearray()
    digest = hashlib.sha256()
    stream = await get_storage_service().open_download(artifact.storage_path)
    async for chunk in stream:
        output.extend(chunk)
        digest.update(chunk)
        if len(output) > maximum or len(output) > artifact.file_size:
            raise HTTPException(status_code=422, detail="Artifact size is invalid")
    if len(output) != artifact.file_size or digest.hexdigest() != artifact.sha256:
        raise HTTPException(status_code=422, detail="Artifact integrity check failed")
    return bytes(output)


def _table_preview(data: bytes, content_type: str) -> dict:
    if content_type == CSV_MEDIA_TYPE:
        frame = pd.read_csv(BytesIO(data), nrows=101)
        sheets = None
    else:
        workbook = pd.ExcelFile(BytesIO(data))
        sheets = workbook.sheet_names
        frame = pd.read_excel(workbook, sheet_name=0, nrows=101)
    truncated = len(frame.index) > 100
    frame = frame.head(100)
    serialized = json.loads(frame.to_json(orient="split", date_format="iso"))
    return {
        "kind": "table",
        "columns": [str(column) for column in serialized["columns"]],
        "rows": serialized["data"],
        "sheet_names": sheets,
        "selected_sheet": sheets[0] if sheets else None,
        "truncated": truncated,
    }


def _text_preview(data: bytes, content_type: str) -> dict:
    limit = 200 * 1024
    if content_type == PDF_MEDIA_TYPE:
        reader = PdfReader(BytesIO(data), strict=True)
        parts: list[str] = []
        length = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            parts.append(text)
            length += len(text.encode("utf-8"))
            if length > limit:
                break
        content = "\n".join(parts)
        encoded = content.encode("utf-8")
        return {
            "kind": "text",
            "text": encoded[:limit].decode("utf-8", errors="ignore"),
            "truncated": len(encoded) > limit,
            "metadata": {
                "pages": len(reader.pages),
                "title": str(reader.metadata.title) if reader.metadata and reader.metadata.title else None,
            },
        }
    text = data.decode("utf-8")
    encoded = text.encode("utf-8")
    return {
        "kind": "text",
        "text": encoded[:limit].decode("utf-8", errors="ignore"),
        "truncated": len(encoded) > limit,
        "metadata": {"format": "json" if content_type == JSON_MEDIA_TYPE else "text"},
    }


@router.get("/{session_id}/{artifact_id}/preview")
async def preview_artifact(
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
):
    artifact = await artifact_service.get_artifact_for_user(
        db, current_user, session_id, artifact_id
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if artifact.content_type in {PNG_MEDIA_TYPE, JPEG_MEDIA_TYPE, WEBP_MEDIA_TYPE}:
        return await _stream_artifact(
            session_id, artifact_id, current_user, db, attachment=False
        )
    data = await _verified_bytes(artifact)
    try:
        if artifact.content_type in {CSV_MEDIA_TYPE, XLSX_MEDIA_TYPE}:
            payload = await asyncio.to_thread(_table_preview, data, artifact.content_type)
        elif artifact.content_type in {JSON_MEDIA_TYPE, TEXT_MEDIA_TYPE, PDF_MEDIA_TYPE}:
            payload = await asyncio.to_thread(_text_preview, data, artifact.content_type)
        else:
            raise HTTPException(status_code=415, detail="Preview is not supported")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Artifact preview failed artifact=%s", artifact.id)
        raise HTTPException(status_code=422, detail="Artifact preview failed") from exc
    return JSONResponse(payload)


@router.get("/{session_id}/{artifact_id}/download")
async def download_artifact(
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
 ) -> StreamingResponse:
    return await _stream_artifact(
        session_id, artifact_id, current_user, db, attachment=True
    )


@router.delete("/{session_id}/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact_route(
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> None:
    await artifact_service.delete_artifact(db, current_user, session_id, artifact_id)
    logger.info(
        "Artifact deleted: session=%s artifact=%s user=%s",
        session_id,
        artifact_id,
        current_user.email,
    )
