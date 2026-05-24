"""Artifact API schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models import ArtifactSource


class ArtifactResponse(BaseModel):
    id: uuid.UUID
    chat_id: uuid.UUID
    filename: str
    content_type: str
    file_size: int
    source: ArtifactSource
    created_at: datetime
    preview_url: str | None = None

    model_config = {"from_attributes": True}
