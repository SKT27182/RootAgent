"""Artifact upload, list, preview, download, delete."""

import uuid
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.core.dependencies import DbSession, get_current_active_user
from app.db.models import User
from app.schemas.artifact import ArtifactResponse
from app.services import artifact_service
from app.core.config import settings
from app.services.storage import get_storage_service
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])

CurrentUser = Annotated[User, Depends(get_current_active_user)]


def _to_response(artifact, preview_url: str | None = None) -> ArtifactResponse:
    return ArtifactResponse(
        id=artifact.id,
        chat_id=artifact.chat_id,
        filename=artifact.filename,
        content_type=artifact.content_type,
        file_size=artifact.file_size,
        source=artifact.source,
        created_at=artifact.created_at,
        preview_url=preview_url,
    )


@router.post("/{session_id}", response_model=ArtifactResponse)
async def upload_artifact(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
) -> ArtifactResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    content_type = file.content_type or "application/octet-stream"
    artifact = await artifact_service.create_artifact(
        db=db,
        user=current_user,
        session_id=session_id,
        filename=file.filename or "upload",
        content_type=content_type,
        data=data,
    )
    storage = get_storage_service()
    preview_url = storage.get_presigned_url(artifact.storage_path)
    logger.info(
        "Artifact uploaded: session=%s file=%s user=%s",
        session_id,
        file.filename,
        current_user.email,
    )
    return _to_response(artifact, preview_url)


@router.get("/{session_id}", response_model=list[ArtifactResponse])
async def list_artifacts(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> list[ArtifactResponse]:
    artifacts = await artifact_service.list_artifacts_for_chat(
        db, current_user, session_id
    )
    storage = get_storage_service()
    return [
        _to_response(a, storage.get_presigned_url(a.storage_path)) for a in artifacts
    ]


@router.get("/{session_id}/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    session_id: str,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> ArtifactResponse:
    artifact = await artifact_service.get_artifact_for_user(
        db, current_user, session_id, artifact_id
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    preview_url = get_storage_service().get_presigned_url(artifact.storage_path)
    return _to_response(artifact, preview_url)


@router.get("/{session_id}/{artifact_id}/download")
async def download_artifact(
    session_id: str,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
):
    artifact = await artifact_service.get_artifact_for_user(
        db, current_user, session_id, artifact_id
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    data = get_storage_service().download_file(artifact.storage_path)
    return StreamingResponse(
        BytesIO(data),
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"'
        },
    )


@router.delete("/{session_id}/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact_route(
    session_id: str,
    artifact_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> None:
    deleted = await artifact_service.delete_artifact(
        db, current_user, session_id, artifact_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact not found")
    logger.info(
        "Artifact deleted: session=%s artifact=%s user=%s",
        session_id,
        artifact_id,
        current_user.email,
    )
