import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from app.db.models import ArtifactOutputKind, ArtifactSource, ChatRunStatus
from app.models.agent import AgentStep


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    step_kind: Optional[str] = None  # user, assistant, tool
    step_index: int | None = Field(default=None, ge=0)
    artifact_ids: list[uuid.UUID] = Field(default_factory=list)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    request_id: uuid.UUID
    session_id: Optional[uuid.UUID] = None

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class ArtifactEventMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    request_id: uuid.UUID
    session_id: uuid.UUID
    status: ChatRunStatus
    response: str | None = None
    message_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    generated_artifact_ids: list[uuid.UUID] = Field(default_factory=list)
    artifacts: list[ArtifactEventMetadata] = Field(default_factory=list)


class RunStartedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["run_started"] = "run_started"
    run_id: uuid.UUID
    session_id: uuid.UUID
    request_id: uuid.UUID


class StepEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["step"] = "step"
    run_id: uuid.UUID
    session_id: uuid.UUID
    step_index: int = Field(ge=0)
    step: AgentStep


class ToolEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tool"] = "tool"
    run_id: uuid.UUID
    session_id: uuid.UUID
    step_index: int = Field(ge=0)
    content: str = Field(max_length=20_000)


class SessionSummary(BaseModel):
    session_id: uuid.UUID
    deletion_pending: bool = False


class SessionDeleteResponse(BaseModel):
    status: Literal["deleted", "pending"]


class ArtifactEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["artifact"] = "artifact"
    run_id: uuid.UUID
    session_id: uuid.UUID
    artifact: ArtifactEventMetadata


class DoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["done"] = "done"
    run_id: uuid.UUID
    session_id: uuid.UUID
    request_id: uuid.UUID
    final_answer: str
    message_id: str
    generated_artifact_ids: list[uuid.UUID] = Field(default_factory=list)


class ChatErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["error"] = "error"
    run_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    code: str
    message: str
    correlation_id: uuid.UUID
    retryable: bool = False


ChatRunEvent = Annotated[
    Union[
        RunStartedEvent,
        StepEvent,
        ToolEvent,
        ArtifactEvent,
        DoneEvent,
        ChatErrorEvent,
    ],
    Field(discriminator="type"),
]
chat_run_event_adapter = TypeAdapter(ChatRunEvent)
