import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.executor_interface import SandboxUnavailable, WorkspaceDescriptor
from app.db.models import (
    ArtifactOutputKind,
    ArtifactSource,
    Chat,
    ChatRun,
    ChatRunStatus,
    User,
)
from app.models.chat import (
    ArtifactEvent,
    ChatRequest,
    DoneEvent,
    Message,
    RunStartedEvent,
    StepEvent,
    ToolEvent,
)
from app.services.chat_run_service import (
    ChatRunFailure,
    ChatRunService,
    request_digest,
)
from app.services.history_sanitizer import (
    MAX_HISTORY_CHARS,
    MAX_TOOL_OBSERVATION_CHARS,
    sanitize_history,
)
from app.services.redis_store import RateLimitResult


def test_recursive_history_sanitizer_strips_data_and_preserves_stored_copy() -> None:
    raw = json.dumps(
        {
            "thinking": "inspect",
            "nested": [
                {"image_url": {"url": "data:image/png;base64," + "A" * 1000}},
                {"image_url": {"url": "data:image/svg+xml,<svg onload=alert(1)>"}},
            ],
        }
    )
    stored = Message(role="assistant", content=raw, step_kind="assistant")
    sanitized = sanitize_history([stored])

    assert "data:image" not in sanitized[0].content
    assert "image data removed" in sanitized[0].content
    assert "data:image" in stored.content


def test_history_sanitizer_caps_observations_and_total_history() -> None:
    messages = [
        Message(role="assistant", content="x" * 60_000, step_kind="tool")
        for _ in range(20)
    ]
    sanitized = sanitize_history(messages)

    assert all(len(message.content) <= MAX_TOOL_OBSERVATION_CHARS for message in sanitized)
    assert sum(len(message.content) for message in sanitized) <= MAX_HISTORY_CHARS


@pytest.mark.asyncio
async def test_completed_request_replays_without_execution() -> None:
    request_id = uuid.uuid4()
    chat = Chat(id=uuid.uuid4(), user_id=uuid.uuid4(), session_id=uuid.uuid4())
    body = ChatRequest(query="same", request_id=request_id, session_id=chat.session_id)
    run = ChatRun(
        id=uuid.uuid4(),
        user_id=chat.user_id,
        chat_id=chat.id,
        request_id=request_id,
        query_digest=request_digest(body),
        status=ChatRunStatus.COMPLETED,
        correlation_id=uuid.uuid4(),
        final_answer="done",
        message_id=str(uuid.uuid4()),
    )
    events: list[object] = []

    async def sink(event: object) -> None:
        events.append(event)

    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    response = await ChatRunService()._existing_result(
        db, run, chat, request_digest(body), sink
    )

    assert response.status == ChatRunStatus.COMPLETED
    assert [type(event) for event in events] == [RunStartedEvent, DoneEvent]


@pytest.mark.asyncio
async def test_request_id_conflict_rejected() -> None:
    chat = Chat(id=uuid.uuid4(), user_id=uuid.uuid4(), session_id=uuid.uuid4())
    run = ChatRun(
        id=uuid.uuid4(),
        user_id=chat.user_id,
        chat_id=chat.id,
        request_id=uuid.uuid4(),
        query_digest="a" * 64,
        status=ChatRunStatus.RUNNING,
        correlation_id=uuid.uuid4(),
    )
    with pytest.raises(ChatRunFailure) as exc_info:
        await ChatRunService()._existing_result(
            MagicMock(), run, chat, "b" * 64, None
        )
    assert exc_info.value.code == "request_id_conflict"


def test_request_digest_uses_run_inputs() -> None:
    request_id = uuid.uuid4()
    first = ChatRequest(query="first", request_id=request_id)
    second = ChatRequest(query="second", request_id=request_id)

    assert request_digest(first) != request_digest(second)


class _Result:
    def one_or_none(self):
        return None


class _Db:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    async def execute(self, _statement):
        return _Result()

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.uuid4()

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, value: object) -> None:
        if getattr(value, "id", None) is None:
            value.id = uuid.uuid4()

    async def rollback(self) -> None:
        return None


class _Redis:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.released = False

    async def check_rate_limit(self, *_args, **_kwargs):
        return RateLimitResult(True, 9, 1)

    async def acquire_run_lock(self, *_args):
        return "token"

    async def release_run_lock(self, *_args):
        self.released = True

    async def save_message(self, _user_id, _session_id, message):
        self.messages.append(message)

    async def get_session_history(self, *_args, **_kwargs):
        return list(self.messages)


class _Agent:
    async def run_stream(self, **_kwargs):
        yield {
            "type": "step",
            "step": {
                "thinking": "inspect",
                "code": "print(1)",
                "is_final_answer": False,
            },
        }
        yield {"type": "tool", "content": "Observation: 1"}
        yield {
            "type": "step",
            "step": {
                "thinking": "complete",
                "final_answer": "answer",
                "is_final_answer": True,
            },
        }


class _Gateway:
    def close(self) -> None:
        return None

    def uploaded_prompt_entries(self) -> list[dict]:
        return []


class _Executor:
    def __init__(self, descriptor: WorkspaceDescriptor) -> None:
        self.descriptor = descriptor
        self.destroyed = False
        self.closed = False

    async def prepare_workspace(self, **_kwargs):
        return self.descriptor

    async def execute(self, _request):
        raise AssertionError("The fake agent should not invoke the executor")

    async def collect_outputs(self, _workspace):
        return ()

    async def destroy(self, _workspace):
        self.destroyed = True

    async def close(self):
        self.closed = True


class _UnavailableExecutor(_Executor):
    async def prepare_workspace(self, **_kwargs):
        raise SandboxUnavailable()


@pytest.mark.asyncio
async def test_terminal_done_is_after_run_persistence_and_workspace_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = _Db()
    redis = _Redis()
    workspace_root = tmp_path / "rootagent_test"
    workspace_root.mkdir(mode=0o700)
    (workspace_root / "inputs").mkdir(mode=0o700)
    (workspace_root / "outputs").mkdir(mode=0o700)
    descriptor = WorkspaceDescriptor(
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        code_visible_root=str(workspace_root),
        input_directory=workspace_root / "inputs",
        output_directory=workspace_root / "outputs",
    )
    executor = _Executor(descriptor)
    monkeypatch.setattr(
        "app.services.chat_run_service.create_chat_artifact_gateway",
        AsyncMock(return_value=_Gateway()),
    )
    monkeypatch.setattr(
        "app.services.chat_run_service.collect_generated_outputs",
        AsyncMock(return_value=()),
    )
    generated_id = uuid.uuid4()
    generated = MagicMock()
    generated.artifact.id = generated_id
    generated.metadata.model_dump.return_value = {
        "id": generated_id,
        "chat_id": uuid.uuid4(),
        "filename": "chart.png",
        "content_type": "image/png",
        "file_size": 100,
        "sha256": "a" * 64,
        "source": ArtifactSource.GENERATED,
        "output_kind": ArtifactOutputKind.PNG,
        "width": 10,
        "height": 10,
        "created_at": datetime.now(timezone.utc),
        "content_url": f"/artifacts/session/{generated_id}/content",
        "download_url": f"/artifacts/session/{generated_id}/download",
        "preview_url": f"/artifacts/session/{generated_id}/content",
    }
    monkeypatch.setattr(
        "app.services.chat_run_service.persist_generated_outputs",
        AsyncMock(return_value=[generated]),
    )
    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        name="User",
        hashed_password="hash",
    )
    body = ChatRequest(query="analyze", request_id=uuid.uuid4())
    commits_at_done: list[int] = []
    events: list[object] = []

    async def sink(event: object) -> None:
        events.append(event)
        if isinstance(event, DoneEvent):
            commits_at_done.append(db.commits)

    response = await ChatRunService(
        agent_factory=_Agent, executor_factory=lambda: executor
    ).execute(
        body,
        user,
        db,  # type: ignore[arg-type]
        redis,  # type: ignore[arg-type]
        uuid.uuid4(),
        event_sink=sink,
    )

    assert response.status == ChatRunStatus.COMPLETED
    assert commits_at_done == [2]
    assert [message.step_kind for message in redis.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert redis.messages[-1].artifact_ids == [generated_id]
    assert redis.messages[1].step_index == 0
    assert redis.messages[2].step_index == 0
    assert response.generated_artifact_ids == [generated_id]
    assert [type(event) for event in events] == [
        RunStartedEvent,
        StepEvent,
        ToolEvent,
        StepEvent,
        ArtifactEvent,
        DoneEvent,
    ]
    step_events = [event for event in events if isinstance(event, StepEvent)]
    assert len(step_events) == 2
    assert step_events[0].step.is_final_answer is False
    assert step_events[1].step.is_final_answer is True
    assert step_events[1].step.thinking == "complete"
    assert step_events[1].step.final_answer == "answer"
    tool_event = next(event for event in events if isinstance(event, ToolEvent))
    assert step_events[0].step_index == tool_event.step_index == 0
    assert redis.released is True
    assert all(str(workspace_root) not in message.content for message in redis.messages)
    assert executor.destroyed is True
    assert executor.closed is True


@pytest.mark.asyncio
async def test_transport_failure_after_commit_does_not_fail_durable_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = _Db()
    redis = _Redis()
    root = tmp_path / "transport_failure"
    (root / "inputs").mkdir(parents=True)
    (root / "outputs").mkdir()
    descriptor = WorkspaceDescriptor(
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        code_visible_root=str(root),
        input_directory=root / "inputs",
        output_directory=root / "outputs",
    )
    executor = _Executor(descriptor)
    monkeypatch.setattr(
        "app.services.chat_run_service.create_chat_artifact_gateway",
        AsyncMock(return_value=_Gateway()),
    )
    monkeypatch.setattr(
        "app.services.chat_run_service.collect_generated_outputs",
        AsyncMock(return_value=()),
    )
    monkeypatch.setattr(
        "app.services.chat_run_service.persist_generated_outputs",
        AsyncMock(return_value=[]),
    )
    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        name="User",
        hashed_password="hash",
    )

    async def disconnected_sink(event: object) -> None:
        if isinstance(event, DoneEvent):
            raise ConnectionError("client disconnected")

    response = await ChatRunService(
        agent_factory=_Agent, executor_factory=lambda: executor
    ).execute(
        ChatRequest(query="analyze", request_id=uuid.uuid4()),
        user,
        db,  # type: ignore[arg-type]
        redis,  # type: ignore[arg-type]
        uuid.uuid4(),
        event_sink=disconnected_sink,
    )

    assert response.status == ChatRunStatus.COMPLETED
    assert db.added[-1].status == ChatRunStatus.COMPLETED
    assert db.commits == 2


@pytest.mark.asyncio
async def test_sandbox_unavailable_is_stable_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = _Db()
    redis = _Redis()
    descriptor = WorkspaceDescriptor(
        workspace_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        code_visible_root=str(tmp_path),
        input_directory=tmp_path,
        output_directory=tmp_path,
    )
    executor = _UnavailableExecutor(descriptor)
    monkeypatch.setattr(
        "app.services.chat_run_service.create_chat_artifact_gateway",
        AsyncMock(return_value=_Gateway()),
    )
    user = User(
        id=uuid.uuid4(),
        email="user@example.com",
        name="User",
        hashed_password="hash",
    )
    body = ChatRequest(query="analyze", request_id=uuid.uuid4())

    with pytest.raises(ChatRunFailure) as exc_info:
        await ChatRunService(executor_factory=lambda: executor).execute(
            body,
            user,
            db,  # type: ignore[arg-type]
            redis,  # type: ignore[arg-type]
            uuid.uuid4(),
        )

    assert exc_info.value.code == "sandbox_unavailable"
    assert exc_info.value.status_code == 503
    assert redis.released is True
    assert executor.closed is True
