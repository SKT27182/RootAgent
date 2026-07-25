"""Transport-neutral orchestration for durable, idempotent chat runs."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import Agent
from app.agent.executor import FinalAnswerException, create_code_executor
from app.agent.executor_interface import (
    CodeExecutorProtocol,
    ExecutionRequest,
    ExecutionStatus,
    SandboxUnavailable,
    WorkspaceDescriptor,
)
from app.agent.tools import AGENT_TOOLS
from app.core.config import settings
from app.core.metrics import CHAT_RUN_DURATION, CHAT_RUNS, RATE_LIMIT_REJECTIONS
from app.db.models import Artifact, Chat, ChatRun, ChatRunStatus, User
from app.models.agent import AgentStep
from app.models.chat import (
    ChatRequest,
    ChatResponse,
    ArtifactEvent,
    ArtifactEventMetadata,
    DoneEvent,
    RunStartedEvent,
    StepEvent,
    ToolEvent,
)
from app.services import artifact_service, session_service
from app.services.chat_messages import (
    history_for_agent,
    message_for_assistant,
    message_for_tool,
    message_for_user,
)
from app.services.history_sanitizer import MAX_TOOL_OBSERVATION_CHARS, sanitize_history
from app.services.artifact_gateway import (
    ChatArtifactGateway,
    bind_chat_artifact_gateway,
    create_chat_artifact_gateway,
)
from app.services.redis_store import RedisStore
from app.services.generated_outputs import (
    GeneratedOutputError,
    collect_generated_outputs,
    persist_generated_outputs,
)
from app.utils.logger import create_logger
from app.utils.utils import format_user_message

logger = create_logger(__name__, level=settings.log_level)
EventSink = Callable[[object], Awaitable[None]]
AgentFactory = Callable[[], Agent]
ExecutorFactory = Callable[[], CodeExecutorProtocol]


async def _deliver_event(event_sink: EventSink | None, event: object) -> bool:
    """Best-effort transport delivery; transport loss never changes durable outcome."""

    if event_sink is None:
        return False
    try:
        await event_sink(event)
    except Exception:
        logger.info("Run event delivery stopped after transport failure", exc_info=True)
        return False
    return True


async def _maintain_run_lock(
    redis_store: RedisStore,
    user_id: str,
    session_id: str,
    token: str,
    stop: asyncio.Event,
) -> None:
    interval = max(5.0, settings.run_lock_ttl_seconds / 3)
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            try:
                renewed = await redis_store.renew_run_lock(user_id, session_id, token)
            except Exception:
                logger.exception("Run lock renewal failed session_id=%s", session_id)
                return
            if not renewed:
                logger.error("Run lock ownership was lost session_id=%s", session_id)
                return


class _RunBoundExecutor:
    """Adapt the typed executor result to the current Agent observation contract."""

    def __init__(
        self, backend: CodeExecutorProtocol, workspace: WorkspaceDescriptor
    ) -> None:
        self._backend = backend
        self._workspace = workspace
        self.output_manifests = ()

    async def execute(self, code: str):
        result = await self._backend.execute(
            ExecutionRequest(
                code=code,
                workspace=self._workspace,
                deadline_seconds=settings.executor_default_deadline_seconds,
                stdout_max_bytes=settings.executor_stdout_max_bytes,
                stderr_max_bytes=settings.executor_stderr_max_bytes,
            )
        )
        self.output_manifests = result.output_manifests
        if result.status == ExecutionStatus.SANDBOX_UNAVAILABLE:
            raise SandboxUnavailable()
        if result.status != ExecutionStatus.SUCCEEDED:
            raise RuntimeError(result.stderr or f"Execution {result.status.value}")
        if result.final_answer is not None:
            return FinalAnswerException(result.final_answer)
        return result.stdout.strip() or "Execution successful (no output)."


class ChatRunFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        run_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.status_code = status_code
        self.retryable = retryable
        self.run_id = run_id
        self.session_id = session_id


def request_digest(body: ChatRequest) -> str:
    canonical = json.dumps(
        {
            "query": body.query,
            "session_id": str(body.session_id) if body.session_id else None,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ChatRunService:
    def __init__(
        self,
        agent_factory: AgentFactory | None = None,
        executor_factory: ExecutorFactory | None = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._executor_factory = executor_factory or (
            lambda: create_code_executor(AGENT_TOOLS)
        )

    async def _find_run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> tuple[ChatRun, Chat] | None:
        result = await db.execute(
            select(ChatRun, Chat)
            .join(Chat, ChatRun.chat_id == Chat.id)
            .where(ChatRun.user_id == user_id, ChatRun.request_id == request_id)
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row else None

    @staticmethod
    async def _artifact_metadata(
        db: AsyncSession, run: ChatRun, chat: Chat
    ) -> list[ArtifactEventMetadata]:
        result = await db.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id)
            .order_by(Artifact.created_at, Artifact.id)
        )
        return [
            ArtifactEventMetadata.model_validate(
                artifact_service.to_artifact_response(
                    artifact, chat.session_id
                ).model_dump()
            )
            for artifact in result.scalars().all()
        ]

    async def _response(
        self, db: AsyncSession, run: ChatRun, chat: Chat
    ) -> ChatResponse:
        artifacts = await self._artifact_metadata(db, run, chat)
        return ChatResponse(
            run_id=run.id,
            request_id=run.request_id,
            session_id=chat.session_id,
            status=run.status,
            response=run.final_answer,
            message_id=run.message_id,
            error_code=run.error_code,
            error_message=run.error_message,
            retryable=run.status == ChatRunStatus.FAILED,
            generated_artifact_ids=[artifact.id for artifact in artifacts],
            artifacts=artifacts,
        )

    async def get_run(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        request_id: uuid.UUID,
    ) -> ChatResponse | None:
        record = await self._find_run(db, user_id, request_id)
        return await self._response(db, *record) if record else None

    async def _existing_result(
        self,
        db: AsyncSession,
        run: ChatRun,
        chat: Chat,
        digest: str,
        event_sink: EventSink | None,
    ) -> ChatResponse:
        if run.query_digest != digest:
            raise ChatRunFailure(
                "request_id_conflict",
                "The request ID was already used for different input",
                status_code=409,
                run_id=run.id,
                session_id=chat.session_id,
            )
        if run.status == ChatRunStatus.FAILED:
            raise ChatRunFailure(
                run.error_code or "execution_failed",
                run.error_message or "The chat run could not be completed",
                status_code=500,
                retryable=True,
                run_id=run.id,
                session_id=chat.session_id,
            )
        response = await self._response(db, run, chat)
        if run.status == ChatRunStatus.COMPLETED and event_sink:
            delivered = await _deliver_event(
                event_sink,
                RunStartedEvent(
                    run_id=run.id,
                    session_id=chat.session_id,
                    request_id=run.request_id,
                )
            )
            for metadata in response.artifacts:
                if not delivered:
                    break
                delivered = await _deliver_event(
                    event_sink,
                    ArtifactEvent(
                        run_id=run.id,
                        session_id=chat.session_id,
                        artifact=metadata,
                    )
                )
            if delivered:
                await _deliver_event(
                    event_sink,
                    DoneEvent(
                        run_id=run.id,
                        session_id=chat.session_id,
                        request_id=run.request_id,
                        final_answer=run.final_answer or "",
                        message_id=run.message_id or "",
                        generated_artifact_ids=response.generated_artifact_ids,
                    ),
                )
        return response

    async def execute(
        self,
        body: ChatRequest,
        user: User,
        db: AsyncSession,
        redis_store: RedisStore,
        correlation_id: uuid.UUID,
        *,
        event_sink: EventSink | None = None,
    ) -> ChatResponse:
        digest = request_digest(body)
        existing = await self._find_run(db, user.id, body.request_id)
        if existing:
            return await self._existing_result(db, *existing, digest, event_sink)

        rate = await redis_store.check_rate_limit(
            "chat",
            str(user.id),
            limit=settings.chat_rate_limit,
            window_seconds=settings.chat_rate_window_seconds,
        )
        if not rate.allowed:
            RATE_LIMIT_REJECTIONS.labels("chat").inc()
            raise ChatRunFailure(
                "rate_limited",
                "Too many chat requests",
                status_code=429,
                retryable=True,
            )

        if body.session_id is None:
            chat = Chat(user_id=user.id, session_id=uuid.uuid4())
            db.add(chat)
            await db.flush()
        else:
            chat = await session_service.get_owned_session(db, user.id, body.session_id)
            if chat is None:
                raise ChatRunFailure(
                    "session_not_found",
                    "The session does not exist",
                    status_code=404,
                )
            if chat.deletion_requested_at is not None:
                raise ChatRunFailure(
                    "session_deleting",
                    "The session is pending deletion",
                    status_code=409,
                    session_id=chat.session_id,
                )

        user_id = str(user.id)
        session_id = str(chat.session_id)
        lock_token = await redis_store.acquire_run_lock(user_id, session_id)
        if lock_token is None:
            await db.rollback()
            raise ChatRunFailure(
                "run_in_progress",
                "A chat run is already active for this session",
                status_code=409,
                retryable=True,
                session_id=chat.session_id,
            )

        run = ChatRun(
            user_id=user.id,
            chat_id=chat.id,
            request_id=body.request_id,
            query_digest=digest,
            status=ChatRunStatus.RUNNING,
            correlation_id=correlation_id,
        )
        db.add(run)
        run_started_at = time.monotonic()
        lock_stop = asyncio.Event()
        lock_task: asyncio.Task[None] | None = None
        try:
            await db.commit()
            await db.refresh(run)
        except IntegrityError:
            await db.rollback()
            await redis_store.release_run_lock(user_id, session_id, lock_token)
            existing = await self._find_run(db, user.id, body.request_id)
            if existing is not None:
                return await self._existing_result(db, *existing, digest, event_sink)
            active_result = await db.execute(
                select(ChatRun).where(
                    ChatRun.chat_id == chat.id,
                    ChatRun.status == ChatRunStatus.RUNNING,
                )
            )
            active = active_result.scalar_one_or_none()
            if active is not None:
                raise ChatRunFailure(
                    "run_in_progress",
                    "A chat run is already active for this session",
                    status_code=409,
                    retryable=True,
                    run_id=active.id,
                    session_id=chat.session_id,
                )
            raise
        except Exception:
            await db.rollback()
            await redis_store.release_run_lock(user_id, session_id, lock_token)
            raise

        lock_task = asyncio.create_task(
            _maintain_run_lock(
                redis_store, user_id, session_id, lock_token, lock_stop
            )
        )

        artifact_gateway: ChatArtifactGateway | None = None
        executor: CodeExecutorProtocol | None = None
        executor_workspace: WorkspaceDescriptor | None = None
        try:
            if event_sink:
                if not await _deliver_event(
                    event_sink,
                    RunStartedEvent(
                        run_id=run.id,
                        session_id=chat.session_id,
                        request_id=body.request_id,
                    ),
                ):
                    event_sink = None
            executor = self._executor_factory()
            executor_workspace = await executor.prepare_workspace(
                run_id=run.id,
                workspace_id=run.id,
            )
            artifact_gateway = await create_chat_artifact_gateway(
                db, user, chat, executor_workspace.output_directory
            )
            formatted = format_user_message(body.query)
            await redis_store.save_message(
                user_id,
                session_id,
                message_for_user(json.dumps(formatted, ensure_ascii=False)),
            )
            stored_history = await redis_store.get_session_history(user_id, session_id)
            agent_history = history_for_agent(stored_history)
            agent_history = sanitize_history(agent_history)

            final_answer = ""
            final_message_id: str | None = None
            final_message = None
            final_step: AgentStep | None = None
            assert executor is not None
            bound_executor = _RunBoundExecutor(executor, executor_workspace)
            agent = (
                self._agent_factory()
                if self._agent_factory
                else Agent(additional_functions=AGENT_TOOLS, executor=bound_executor)
            )
            gateway_binding = bind_chat_artifact_gateway(artifact_gateway)
            gateway_binding.__enter__()
            try:
                async for raw_event in agent.run_stream(
                query=None,
                history=agent_history,
                uploaded_artifacts=artifact_gateway.uploaded_prompt_entries(),
            ):
                    if raw_event.get("type") == "step":
                        step = AgentStep.model_validate(raw_event.get("step"))
                        step_index = int(raw_event.get("step_index", 0))
                        message = message_for_assistant(step, step_index=step_index)
                        if step.is_final_answer:
                            final_answer = step.final_answer or step.thinking
                            final_message_id = message.message_id
                            final_message = message
                            final_step = step
                            # Stream the final step so the client can show thinking/code
                            # via a trace card; DoneEvent remains the final-answer source.
                            if event_sink:
                                if not await _deliver_event(
                                    event_sink,
                                    StepEvent(
                                        run_id=run.id,
                                        session_id=chat.session_id,
                                        step_index=step_index,
                                        step=step,
                                    ),
                                ):
                                    event_sink = None
                        else:
                            await redis_store.save_message(user_id, session_id, message)
                            if event_sink:
                                if not await _deliver_event(
                                    event_sink,
                                    StepEvent(
                                        run_id=run.id,
                                        session_id=chat.session_id,
                                        step_index=step_index,
                                        step=step,
                                    ),
                                ):
                                    event_sink = None
                    elif raw_event.get("type") == "tool":
                        step_index = int(raw_event.get("step_index", 0))
                        observation = str(raw_event.get("content", ""))[
                            :MAX_TOOL_OBSERVATION_CHARS
                        ]
                        await redis_store.save_message(
                            user_id,
                            session_id,
                            message_for_tool(observation, step_index=step_index),
                        )
                        if event_sink:
                            if not await _deliver_event(
                                event_sink,
                                ToolEvent(
                                    run_id=run.id,
                                    session_id=chat.session_id,
                                    step_index=step_index,
                                    content=observation,
                                ),
                            ):
                                event_sink = None
            finally:
                gateway_binding.__exit__(None, None, None)

            if not final_message_id or final_message is None or final_step is None:
                raise RuntimeError("Agent produced no final answer")

            collected_outputs = await collect_generated_outputs(executor_workspace)
            generated = await persist_generated_outputs(
                db,
                user,
                chat.session_id,
                run.id,
                collected_outputs,
            )
            generated_ids = [item.artifact.id for item in generated]
            final_message = final_message.model_copy(
                update={"artifact_ids": generated_ids}
            )
            artifact_metadata = [
                ArtifactEventMetadata.model_validate(item.metadata.model_dump())
                for item in generated
            ]
            run.status = ChatRunStatus.COMPLETED
            run.final_answer = final_answer
            run.message_id = final_message_id
            run.completed_at = datetime.now(timezone.utc)
            run.error_code = None
            run.error_message = None
            await redis_store.save_message(user_id, session_id, final_message)
            try:
                await db.commit()
            except Exception:
                try:
                    await redis_store.delete_message(
                        user_id, session_id, final_message_id
                    )
                except Exception:
                    logger.exception(
                        "Could not compensate final Redis message run_id=%s", run.id
                    )
                raise

            response = ChatResponse(
                run_id=run.id,
                request_id=body.request_id,
                session_id=chat.session_id,
                status=ChatRunStatus.COMPLETED,
                response=final_answer,
                message_id=final_message_id,
                generated_artifact_ids=generated_ids,
                artifacts=artifact_metadata,
            )
            if event_sink:
                for metadata in artifact_metadata:
                    if event_sink is None:
                        break
                    if not await _deliver_event(
                        event_sink,
                        ArtifactEvent(
                            run_id=run.id,
                            session_id=chat.session_id,
                            artifact=metadata,
                        ),
                    ):
                        event_sink = None
                        break
                if event_sink:
                    await _deliver_event(
                        event_sink,
                        DoneEvent(
                            run_id=run.id,
                            session_id=chat.session_id,
                            request_id=body.request_id,
                            final_answer=final_answer,
                            message_id=final_message_id,
                            generated_artifact_ids=generated_ids,
                        ),
                    )
            CHAT_RUNS.labels("completed", settings.executor_backend).inc()
            CHAT_RUN_DURATION.labels(
                "completed", settings.executor_backend
            ).observe(time.monotonic() - run_started_at)
            return response
        except GeneratedOutputError as exc:
            CHAT_RUNS.labels(exc.code, settings.executor_backend).inc()
            CHAT_RUN_DURATION.labels(exc.code, settings.executor_backend).observe(
                time.monotonic() - run_started_at
            )
            await self._mark_failed(db, run, exc.code, exc.message)
            raise ChatRunFailure(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                run_id=run.id,
                session_id=chat.session_id,
            ) from exc
        except SandboxUnavailable as exc:
            CHAT_RUNS.labels("sandbox_unavailable", settings.executor_backend).inc()
            CHAT_RUN_DURATION.labels(
                "sandbox_unavailable", settings.executor_backend
            ).observe(time.monotonic() - run_started_at)
            await self._mark_failed(
                db, run, "sandbox_unavailable", "The configured sandbox is unavailable"
            )
            raise ChatRunFailure(
                "sandbox_unavailable",
                "The configured sandbox is unavailable",
                status_code=503,
                retryable=True,
                run_id=run.id,
                session_id=chat.session_id,
            ) from exc
        except ChatRunFailure:
            raise
        except Exception as exc:
            CHAT_RUNS.labels("execution_failed", settings.executor_backend).inc()
            CHAT_RUN_DURATION.labels(
                "execution_failed", settings.executor_backend
            ).observe(time.monotonic() - run_started_at)
            logger.exception(
                "Chat run failed run_id=%s correlation_id=%s",
                run.id,
                correlation_id,
            )
            await self._mark_failed(
                db, run, "execution_failed", "The chat run could not be completed"
            )
            raise ChatRunFailure(
                "execution_failed",
                "The chat run could not be completed",
                status_code=500,
                retryable=True,
                run_id=run.id,
                session_id=chat.session_id,
            ) from exc
        finally:
            lock_stop.set()
            if lock_task is not None:
                await lock_task
            if executor is not None and executor_workspace is not None:
                try:
                    await executor.destroy(executor_workspace)
                except Exception:
                    logger.exception(
                        "Failed to destroy executor workspace %s",
                        executor_workspace.workspace_id,
                    )
            if artifact_gateway is not None:
                artifact_gateway.close()
            if executor is not None:
                try:
                    await executor.close()
                except Exception:
                    logger.exception("Failed to close executor for run %s", run.id)
            try:
                await redis_store.release_run_lock(user_id, session_id, lock_token)
            except Exception:
                logger.exception("Failed to release run lock run_id=%s", run.id)
            try:
                pending = await session_service.get_owned_session(
                    db, user.id, chat.session_id
                )
                if pending is not None and pending.deletion_requested_at is not None:
                    cleanup_token = await redis_store.acquire_run_lock(
                        user_id, session_id
                    )
                    if cleanup_token is not None:
                        try:
                            await session_service.delete_session(
                                db, user.id, chat.session_id
                            )
                        finally:
                            await redis_store.release_run_lock(
                                user_id, session_id, cleanup_token
                            )
            except Exception:
                logger.exception(
                    "Could not finalize pending session deletion session_id=%s",
                    chat.session_id,
                )

    @staticmethod
    async def _mark_failed(
        db: AsyncSession, run: ChatRun, code: str, message: str
    ) -> None:
        try:
            run.status = ChatRunStatus.FAILED
            run.error_code = code
            run.error_message = message[:512]
            run.completed_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Could not persist failed chat run %s", run.id)


chat_run_service = ChatRunService()
