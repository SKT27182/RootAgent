import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import Agent
from app.agent.tools import AGENT_TOOLS
from app.core.config import settings
from app.core.dependencies import DbSession, get_current_active_user
from app.db.models import User
from app.db.postgres import async_session_maker
from app.models.agent import AgentStep
from app.models.chat import ChatRequest, ChatResponse, Message
from app.services import artifact_service
from app.services.chat_messages import (
    history_for_agent,
    message_for_assistant,
    message_for_tool,
    message_for_user,
)
from app.services.redis_store import RedisStore
from app.utils.logger import create_logger
from app.utils.utils import format_user_message

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = create_logger(__name__, level=settings.log_level)


@lru_cache()
def get_redis_store() -> RedisStore:
    return RedisStore()


def _ensure_user_id(request_user_id: str, current_user: User) -> str:
    uid = str(current_user.id)
    if request_user_id != uid:
        raise HTTPException(status_code=403, detail="User ID mismatch")
    return uid


async def _build_artifact_context(
    db: AsyncSession,
    user: User,
    session_id: str,
    artifact_ids: Optional[List[str]] = None,
) -> str:
    if not artifact_ids:
        return ""
    lines = ["Attached artifacts:"]
    for aid_str in artifact_ids:
        try:
            aid = uuid.UUID(aid_str)
        except ValueError:
            continue
        artifact = await artifact_service.get_artifact_for_user(
            db, user, session_id, aid
        )
        if artifact:
            lines.append(
                f"- id={artifact.id} file={artifact.filename} "
                f"type={artifact.content_type} path={artifact.storage_path}"
            )
    return "\n".join(lines) if len(lines) > 1 else ""


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: DbSession,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
):
    user_id = _ensure_user_id(request.user_id, current_user)
    session_id = request.session_id or str(uuid.uuid4())
    query = request.query

    if not query:
        raise HTTPException(status_code=400, detail="Query is required")

    formatted_content = format_user_message(query, request.images, request.csv_data)
    user_message = message_for_user(json.dumps(formatted_content))
    await redis_store.save_message(user_id, session_id, user_message)
    await redis_store.add_user_session(user_id, session_id)

    try:
        history = history_for_agent(
            await redis_store.get_session_history(
                user_id, session_id, include_reasoning=True
            )
        )
        artifact_context = await _build_artifact_context(
            db, current_user, session_id, request.artifact_ids
        )

        agent = Agent(additional_functions=AGENT_TOOLS)
        response_text, generated_steps = await agent.run(
            query=None,
            history=history,
            artifact_context=artifact_context or None,
        )

        try:
            await artifact_service.save_generated_images_from_text(
                db, current_user, session_id, response_text
            )
        except Exception as gen_err:
            logger.warning(f"Could not persist generated images: {gen_err}")

        last_assistant: Message | None = None
        for step_msg in generated_steps:
            role = step_msg.get("role", "assistant")
            content_str = step_msg.get("content", "")
            if not isinstance(content_str, str):
                content_str = json.dumps(content_str)

            if role == "assistant":
                step = AgentStep.model_validate_json(content_str)
                stored = message_for_assistant(step)
                await redis_store.save_message(user_id, session_id, stored)
                last_assistant = stored
            elif role == "user":
                await redis_store.save_message(
                    user_id, session_id, message_for_tool(content_str)
                )

        if last_assistant is None:
            raise HTTPException(status_code=500, detail="Agent produced no response")

        return ChatResponse(
            response=response_text,
            session_id=session_id,
            message_id=last_assistant.message_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/history/{user_id}/{session_id}", response_model=List[Message])
async def get_history(
    user_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
    include_reasoning: bool = False,
):
    _ensure_user_id(user_id, current_user)
    return await redis_store.get_session_history(
        user_id, session_id, include_reasoning=include_reasoning, last_n=-1
    )


@router.get("/sessions/{user_id}", response_model=List[str])
async def get_sessions(
    user_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
):
    _ensure_user_id(user_id, current_user)
    return await redis_store.get_user_sessions(user_id)


@router.delete("/sessions/{user_id}/{session_id}")
async def delete_session(
    user_id: str,
    session_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
):
    _ensure_user_id(user_id, current_user)
    deleted = await redis_store.delete_session(user_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": f"Session {session_id} deleted successfully"}


@router.delete("/message/{user_id}/{session_id}/{message_id}")
async def delete_message(
    user_id: str,
    session_id: str,
    message_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
):
    _ensure_user_id(user_id, current_user)
    deleted = await redis_store.delete_message(user_id, session_id, message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": f"Message {message_id} deleted successfully"}


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    redis_store: Annotated[RedisStore, Depends(get_redis_store)],
):
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        request_data = json.loads(data)

        query = request_data.get("query")
        user_id = request_data.get("user_id")
        session_id = request_data.get("session_id")
        include_reasoning = request_data.get("include_reasoning", True)
        images = request_data.get("images")
        csv_data = request_data.get("csv_data")
        artifact_ids = request_data.get("artifact_ids")

        if not query or not user_id:
            await websocket.send_json(
                {"type": "error", "content": "Query and User ID are required"}
            )
            return

        if not session_id:
            session_id = str(uuid.uuid4())
            await websocket.send_json(
                {
                    "type": "info",
                    "content": "New session created",
                    "session_id": session_id,
                }
            )

        formatted_content = format_user_message(query, images, csv_data)
        user_message = message_for_user(json.dumps(formatted_content))
        await redis_store.add_user_session(user_id, session_id)
        await redis_store.save_message(user_id, session_id, user_message)

        history = history_for_agent(
            await redis_store.get_session_history(
                user_id, session_id, include_reasoning=include_reasoning
            )
        )

        artifact_context = ""
        if artifact_ids:
            artifact_context = f"Artifact IDs for this chat: {', '.join(artifact_ids)}"

        agent = Agent(additional_functions=AGENT_TOOLS)
        final_answer = ""

        async for event in agent.run_stream(
            query=None,
            history=history,
            artifact_context=artifact_context or None,
        ):
            await websocket.send_json(event)

            if event["type"] == "step":
                step = AgentStep.model_validate(event["step"])
                await redis_store.save_message(
                    user_id, session_id, message_for_assistant(step)
                )
                if step.is_final_answer:
                    final_answer = step.final_answer or step.thinking
            elif event["type"] == "tool":
                await redis_store.save_message(
                    user_id,
                    session_id,
                    message_for_tool(event.get("content", "")),
                )

        if final_answer:
            try:
                async with async_session_maker() as ws_db:
                    result = await ws_db.execute(
                        select(User).where(User.id == uuid.UUID(user_id))
                    )
                    ws_user = result.scalar_one_or_none()
                    if ws_user:
                        await artifact_service.save_generated_images_from_text(
                            ws_db, ws_user, session_id, final_answer
                        )
                        await ws_db.commit()
            except Exception as gen_err:
                logger.warning(f"WS generated image save failed: {gen_err}")

        await websocket.close()

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
            await websocket.close()
        except Exception:
            pass
