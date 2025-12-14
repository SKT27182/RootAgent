from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from typing import List, Optional, Any
from backend.app.models.chat import Session, Message, ChatRequest, ChatResponse
from backend.app.services.redis_store import RedisStore
from backend.app.agent.agent import Agent
from backend.app.agent.tools import AGENT_TOOLS
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger
from backend.app.utils.utils import format_user_message
import uuid
from datetime import datetime, timezone
import json
from functools import lru_cache

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = create_logger(__name__, level=Config.LOG_LEVEL)


# Dependency for Redis Store
@lru_cache()
def get_redis_store():
    return RedisStore()


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    redis_store: RedisStore = Depends(get_redis_store),
):
    """
    Endpoint for chat interaction.
    """
    query = request.query
    user_id = request.user_id
    session_id = request.session_id
    include_reasoning = request.include_reasoning
    images = request.images
    csv_data = request.csv_data

    logger.info(
        f"Chat request received from user={user_id}, session={session_id} with reasoning={include_reasoning} for query={query}"
    )

    if not query:
        logger.error("Query missing in request.")
        raise HTTPException(status_code=400, detail="Query is required")
    if not user_id:
        logger.error("User ID missing in request.")
        raise HTTPException(status_code=400, detail="User ID is required")

    # Generate session_id if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
        logger.info(f"Generated new session_id: {session_id}")

    # Create User Message
    # Format message content using helper
    formatted_content = format_user_message(query, images, csv_data)

    user_message = Message(
        role="user",
        content=json.dumps(formatted_content),
        timestamp=datetime.now(timezone.utc),
    )

    # Save User Message to Redis
    await redis_store.save_message(user_id, session_id, user_message)

    # Track session for user
    await redis_store.add_user_session(user_id, session_id)

    try:
        # Run Agent
        logger.debug(f"Running agent for session {session_id}")

        # Get history to pass to agent
        history = await redis_store.get_session_history(
            user_id, session_id, include_reasoning=include_reasoning
        )
        logger.debug(f"Retrieved history: {history}")
        logger.info(f"Retrieved {len(history)} messages from session {session_id}")
        # Get persistent functions
        previous_functions = await redis_store.get_functions(user_id, session_id)
        previous_imports = await redis_store.get_imports(user_id, session_id)
        logger.debug(
            f"Retrieved {len(previous_functions)} functions and {len(previous_imports)} imports from session {session_id}"
        )
        logger.debug(f"Previous functions: {previous_functions}")
        logger.debug(f"Previous imports: {previous_imports}")

        # Create ephemeral agent (state restored from Redis)
        agent = Agent(
            additional_functions=AGENT_TOOLS,
            previous_functions=previous_functions,
            previous_imports=previous_imports,
        )

        response_text, generated_steps = await agent.run(
            query=None,  # Query is already in history
            images=None,  # Images are already in history
            history=history,
        )

        # Save defined functions
        try:
            current_imports, current_functions = agent.get_all_defined_functions()
            await redis_store.save_functions(user_id, session_id, current_functions)
            await redis_store.save_imports(user_id, session_id, current_imports)
            logger.debug(f"Current functions: {current_functions}")
        except Exception as ex:
            logger.warning(f"Failed to save functions: {ex}")

        # Save Reasoning Steps
        for step_msg in generated_steps:
            # Ensure content is string
            content_str = step_msg.get("content", "")
            if not isinstance(content_str, str):
                content_str = json.dumps(content_str)

            reasoning_message = Message(
                role=step_msg.get("role", "assistant"),
                content=content_str,
                timestamp=datetime.now(timezone.utc),
                is_reasoning=True,
            )
            await redis_store.save_message(user_id, session_id, reasoning_message)

        # Create Assistant Message (Final Answer)
        assistant_message = Message(
            role="assistant",
            content=response_text,
            timestamp=datetime.now(timezone.utc),
            is_reasoning=False,
        )

        # Save Assistant Message to Redis
        await redis_store.save_message(user_id, session_id, assistant_message)

        logger.info(f"Chat response sent for session {session_id}")
        return ChatResponse(
            response=response_text,
            session_id=session_id,
            message_id=assistant_message.message_id,
        )

    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{user_id}/{session_id}", response_model=List[Message])
async def get_history(
    user_id: str,
    session_id: str,
    include_reasoning: bool = False,
    redis_store: RedisStore = Depends(get_redis_store),
):
    logger.info(
        f"Fetching history for user={user_id}, session={session_id}, include_reasoning={include_reasoning}"
    )
    return await redis_store.get_session_history(
        user_id, session_id, include_reasoning=include_reasoning, last_n=-1
    )


@router.get("/sessions/{user_id}", response_model=List[str])
async def get_sessions(
    user_id: str,
    redis_store: RedisStore = Depends(get_redis_store),
):
    logger.info(f"Fetching sessions for user={user_id}")
    return await redis_store.get_user_sessions(user_id)


@router.delete("/sessions/{user_id}/{session_id}")
async def delete_session(
    user_id: str,
    session_id: str,
    redis_store: RedisStore = Depends(get_redis_store),
):
    """Delete a session and all its messages, functions, and imports."""
    logger.info(f"Deleting session={session_id} for user={user_id}")
    deleted = await redis_store.delete_session(user_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": f"Session {session_id} deleted successfully"}


@router.delete("/message/{user_id}/{session_id}/{message_id}")
async def delete_message(
    user_id: str,
    session_id: str,
    message_id: str,
    redis_store: RedisStore = Depends(get_redis_store),
):
    """Delete a specific message from a session."""
    logger.info(
        f"Deleting message={message_id} from session={session_id} for user={user_id}"
    )
    deleted = await redis_store.delete_message(user_id, session_id, message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": f"Message {message_id} deleted successfully"}


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    redis_store: RedisStore = Depends(get_redis_store),
):
    await websocket.accept()
    try:
        data = await websocket.receive_text()
        request_data = json.loads(data)

        # Parse ChatRequest manually since it comes as dict
        query = request_data.get("query")
        user_id = request_data.get("user_id")
        session_id = request_data.get("session_id")
        include_reasoning = request_data.get("include_reasoning", True)
        images = request_data.get("images")
        csv_data = request_data.get("csv_data")

        logger.info(
            f"Chat request received from user={user_id}, session={session_id} with reasoning={include_reasoning} for query={query}"
        )

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

        # Save User Message
        formatted_content = format_user_message(query, images, csv_data)
        user_message = Message(
            role="user",
            content=json.dumps(formatted_content),
            timestamp=datetime.now(timezone.utc),
        )
        await redis_store.add_user_session(user_id, session_id)
        await redis_store.save_message(user_id, session_id, user_message)

        # Retrieve Context
        history = await redis_store.get_session_history(
            user_id, session_id, include_reasoning=include_reasoning
        )
        logger.debug(f"Retrieved history: {history}")
        logger.info(f"Retrieved {len(history)-1} messages from session {session_id}")
        previous_functions = await redis_store.get_functions(user_id, session_id)
        previous_imports = await redis_store.get_imports(user_id, session_id)

        # Create ephemeral agent (state restored from Redis)
        agent = Agent(
            additional_functions=AGENT_TOOLS,
            previous_functions=previous_functions,
            previous_imports=previous_imports,
        )

        # Stream Execution
        final_answer = ""
        current_step_content = ""

        async for event in agent.run_stream(
            query=None,
            images=None,
            history=history,
        ):
            await websocket.send_json(event)

            # Accumulate tokens to reconstruct messages for persistence
            if event["type"] == "token":
                current_step_content += event["content"]
            elif event["type"] == "observation":
                # An observation came - save the accumulated LLM reasoning first as assistant
                if current_step_content.strip():
                    reasoning_message = Message(
                        role="assistant",
                        content=current_step_content,
                        timestamp=datetime.now(timezone.utc),
                        is_reasoning=True,
                    )
                    await redis_store.save_message(
                        user_id, session_id, reasoning_message
                    )
                    logger.debug(
                        f"Saved reasoning step: {current_step_content[:100]}..."
                    )
                    current_step_content = ""  # Reset

                # Save observation as user message (code output)
                observation_message = Message(
                    role="user",
                    content=event["content"],
                    timestamp=datetime.now(timezone.utc),
                    is_reasoning=True,
                )
                await redis_store.save_message(user_id, session_id, observation_message)
                logger.debug(f"Saved observation: {event['content'][:100]}...")
            elif event["type"] == "step_separator":
                # A step ended - save any remaining accumulated content as reasoning
                if current_step_content.strip():
                    reasoning_message = Message(
                        role="assistant",
                        content=current_step_content,
                        timestamp=datetime.now(timezone.utc),
                        is_reasoning=True,
                    )
                    await redis_store.save_message(
                        user_id, session_id, reasoning_message
                    )
                    logger.debug(
                        f"Saved reasoning step at separator: {current_step_content[:100]}..."
                    )
                current_step_content = ""  # Reset for next step
            elif event["type"] == "error":
                # An error occurred - save accumulated reasoning first as assistant
                if current_step_content.strip():
                    reasoning_message = Message(
                        role="assistant",
                        content=current_step_content,
                        timestamp=datetime.now(timezone.utc),
                        is_reasoning=True,
                    )
                    await redis_store.save_message(
                        user_id, session_id, reasoning_message
                    )
                    logger.debug(
                        f"Saved reasoning before error: {current_step_content[:100]}..."
                    )
                    current_step_content = ""  # Reset

                # Save error as user message (like observation)
                error_message = Message(
                    role="user",
                    content=event["content"],
                    timestamp=datetime.now(timezone.utc),
                    is_reasoning=True,
                )
                await redis_store.save_message(user_id, session_id, error_message)
                logger.debug(f"Saved error as observation: {event['content'][:100]}...")
            elif event["type"] == "final":
                # Save any remaining accumulated content before final
                if current_step_content.strip():
                    reasoning_message = Message(
                        role="assistant",
                        content=current_step_content,
                        timestamp=datetime.now(timezone.utc),
                        is_reasoning=True,
                    )
                    logger.debug(
                        f"Saving Remaining Reasoning messages: {current_step_content[:100]}..."
                    )
                    await redis_store.save_message(
                        user_id, session_id, reasoning_message
                    )
                final_answer = event["content"]

        # Save Assistant Message (Final)
        if final_answer:
            assistant_message = Message(
                role="assistant",
                content=final_answer,
                timestamp=datetime.now(timezone.utc),
                is_reasoning=False,
            )
            logger.debug(
                f"Saving Assistant Message: {final_answer} for session {session_id}"
            )
            await redis_store.save_message(user_id, session_id, assistant_message)

        # Save functions/imports to Redis
        try:
            current_imports, current_functions = agent.get_all_defined_functions()
            await redis_store.save_functions(user_id, session_id, current_functions)
            await redis_store.save_imports(user_id, session_id, current_imports)
            logger.debug(
                f"Saved {len(current_functions)} functions and {len(current_imports)} imports for session {session_id}"
            )
        except Exception as e:
            logger.error(
                f"Failed to save functions/imports for session {session_id}: {e}"
            )

        await websocket.close()

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
            await websocket.close()
        except:
            pass
