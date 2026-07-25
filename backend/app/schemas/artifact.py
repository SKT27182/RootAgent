"""Artifact API schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models import ArtifactOutputKind, ArtifactSource


class ArtifactResponse(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID
    filename: str
    content_type: str
    file_size: int
    sha256: str
    source: ArtifactSource
    output_kind: ArtifactOutputKind | None = None
    width: int | None = None
    height: int | None = None
    created_at: datetime
    content_url: str
    download_url: str
    preview_url: str | None = None

    model_config = {"from_attributes": True}
