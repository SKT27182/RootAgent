"""Authenticated HTTP and WebSocket chat transports over ChatRunService."""

import json
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.core.dependencies import DbSession, get_current_active_user
from app.core.metrics import WS_AUTH_FAILURES
from app.db.models import ChatRunStatus, User
from app.db.postgres import async_session_maker
from app.models.chat import (
    ChatErrorEvent,
    ChatRequest,
    ChatResponse,
    Message,
    SessionDeleteResponse,
    SessionSummary,
)
from app.services import session_service
from app.services.chat_run_service import ChatRunFailure, chat_run_service
from app.services.redis_store import RedisStore, get_redis_store
from app.utils.logger import create_logger

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = create_logger(__name__, level=settings.log_level)


def _http_failure(exc: ChatRunFailure) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.safe_message,
            "retryable": exc.retryable,
        },
    )


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    body: ChatRequest,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
) -> ChatResponse:
    correlation_id = uuid.UUID(str(request.state.correlation_id))
    try:
        result = await chat_run_service.execute(
            body, current_user, db, redis_store, correlation_id
        )
    except ChatRunFailure as exc:
        raise _http_failure(exc) from exc
    if result.status == ChatRunStatus.RUNNING:
        response.status_code = 202
    return result


@router.get("/runs/{request_id}", response_model=ChatResponse)
async def get_run(
    request_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
) -> ChatResponse:
    result = await chat_run_service.get_run(db, current_user.id, request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Chat run not found")
    return result


@router.get("/history/{session_id}", response_model=list[Message])
async def get_history(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
) -> list[Message]:
    if await session_service.get_owned_session(db, current_user.id, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return await redis_store.get_session_history(
        str(current_user.id),
        str(session_id),
        last_n=-1,
    )


@router.get("/sessions", response_model=list[SessionSummary])
async def get_sessions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
) -> list[SessionSummary]:
    sessions = await session_service.list_sessions(db, current_user.id)
    return [
        SessionSummary(
            session_id=session.session_id,
            deletion_pending=session.deletion_requested_at is not None,
        )
        for session in sessions
    ]


@router.post("/sessions", response_model=SessionSummary, status_code=201)
async def create_session(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
) -> SessionSummary:
    """Create an empty owned chat so uploads can happen before the first message."""
    chat = await session_service.resolve_run_session(db, current_user.id, None)
    if chat is None:
        raise HTTPException(status_code=500, detail="Could not create session")
    return SessionSummary(session_id=chat.session_id, deletion_pending=False)


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
    response: Response,
) -> SessionDeleteResponse:
    chat = await session_service.get_owned_session(db, current_user.id, session_id)
    if chat is None:
        return SessionDeleteResponse(status="deleted")
    token = await redis_store.acquire_run_lock(
        str(current_user.id), str(session_id)
    )
    if token is None:
        await session_service.request_session_deletion(db, chat)
        response.status_code = 202
        return SessionDeleteResponse(status="pending")
    try:
        await session_service.delete_session(db, current_user.id, session_id)
    finally:
        await redis_store.release_run_lock(
            str(current_user.id), str(session_id), token
        )
    return SessionDeleteResponse(status="deleted")


@router.delete("/message/{session_id}/{message_id}")
async def delete_message(
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
) -> dict[str, str]:
    if await session_service.get_owned_session(db, current_user.id, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    deleted = await redis_store.delete_message(
        str(current_user.id), str(session_id), str(message_id)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": f"Message {message_id} deleted successfully"}


async def _send_ws_error(
    websocket: WebSocket,
    *,
    code: str,
    message: str,
    correlation_id: uuid.UUID,
    retryable: bool = False,
    run_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
) -> None:
    event = ChatErrorEvent(
        run_id=run_id,
        session_id=session_id,
        code=code,
        message=message,
        correlation_id=correlation_id,
        retryable=retryable,
    )
    await websocket.send_json(event.model_dump(mode="json"))


def _origin_is_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    allowed = {value.rstrip("/") for value in settings.cors_origins_list}
    return origin.rstrip("/") in allowed


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
    ticket: str | None = None,
) -> None:
    correlation_id = uuid.uuid4()
    accepted = False
    try:
        origin = websocket.headers.get("origin")
        if not _origin_is_allowed(origin):
            WS_AUTH_FAILURES.labels("origin").inc()
            logger.warning(
                "WebSocket rejected: invalid origin correlation_id=%s origin=%r",
                correlation_id,
                origin,
            )
            await websocket.close(code=1008, reason="WebSocket origin rejected")
            return

        user_id = await redis_store.consume_ws_ticket(ticket or "")
        if user_id is None:
            WS_AUTH_FAILURES.labels("ticket").inc()
            logger.warning(
                "WebSocket rejected: invalid ticket correlation_id=%s", correlation_id
            )
            await websocket.close(code=1008, reason="WebSocket authentication failed")
            return
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            WS_AUTH_FAILURES.labels("identity").inc()
            await websocket.close(code=1008, reason="WebSocket authentication failed")
            return

        async with async_session_maker() as db:
            result = await db.execute(select(User).where(User.id == user_uuid))
            user = result.scalar_one_or_none()
            if user is None:
                WS_AUTH_FAILURES.labels("user_not_found").inc()
                await websocket.close(
                    code=1008, reason="WebSocket authentication failed"
                )
                return

            await websocket.accept()
            accepted = True
            try:
                body = ChatRequest.model_validate_json(await websocket.receive_text())
            except (ValidationError, ValueError, json.JSONDecodeError):
                await _send_ws_error(
                    websocket,
                    code="invalid_request",
                    message="The chat request is malformed or invalid",
                    correlation_id=correlation_id,
                )
                return

            async def send_event(event: object) -> None:
                await websocket.send_json(event.model_dump(mode="json"))  # type: ignore[attr-defined]

            try:
                run = await chat_run_service.execute(
                    body,
                    user,
                    db,
                    redis_store,
                    correlation_id,
                    event_sink=send_event,
                )
            except ChatRunFailure as exc:
                await _send_ws_error(
                    websocket,
                    code=exc.code,
                    message=exc.safe_message,
                    correlation_id=correlation_id,
                    retryable=exc.retryable,
                    run_id=exc.run_id,
                    session_id=exc.session_id,
                )
                return
            if run.status == ChatRunStatus.RUNNING:
                await _send_ws_error(
                    websocket,
                    code="run_in_progress",
                    message="The request is already in progress",
                    correlation_id=correlation_id,
                    retryable=True,
                    run_id=run.run_id,
                    session_id=run.session_id,
                )
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected correlation_id=%s", correlation_id)
    except Exception:
        logger.exception("WebSocket failure correlation_id=%s", correlation_id)
        if accepted:
            try:
                await _send_ws_error(
                    websocket,
                    code="internal_error",
                    message="The chat run could not be completed",
                    correlation_id=correlation_id,
                    retryable=True,
                )
            except Exception:
                pass
        else:
            try:
                await websocket.close(code=1011, reason="WebSocket unavailable")
            except Exception:
                pass
    finally:
        if accepted:
            try:
                await websocket.close()
            except Exception:
                pass
