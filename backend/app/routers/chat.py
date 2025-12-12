from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Any
from backend.app.models.chat import Session, Message, ChatRequest, ChatResponse

# from backend.app.agent.agent import Agent # Removed, used via AgentManager
from backend.app.services.redis_store import RedisStore
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


from backend.app.services.agent_manager import AgentManager


# Dependency for AgentManager
# We can just instantiate it since it's a singleton, or use a dependency.
# Using a simple function to get the singleton.
def get_agent_manager():
    return AgentManager()


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    agent_manager: AgentManager = Depends(get_agent_manager),
):
    """
    Endpoint for chat interaction.
    """
    query = request.query
    user_id = request.user_id
    session_id = request.session_id
    images = request.images

    logger.info(f"Chat request received from user={user_id}, session={session_id}")
    logger.debug(f"Query: {query}")

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
    formatted_content = format_user_message(query, images, request.csv_data)

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
            user_id, session_id, include_reasoning=request.include_reasoning
        )
        logger.debug(f"Retrieved history: {history}")
        logger.info(f"Retrieved {len(history)} messages from session {session_id}")
        # Get persistent functions
        previous_functions = await redis_store.get_functions(user_id, session_id)
        previous_imports = await redis_store.get_imports(user_id, session_id)
        logger.info(
            f"Retrieved {len(previous_functions)} functions and {len(previous_imports)} imports from session {session_id}"
        )
        logger.debug(f"Previous functions: {previous_functions}")
        logger.debug(f"Previous imports: {previous_imports}")

        # Get or create persistent agent
        agent = agent_manager.get_agent(
            session_id,
            previous_functions=previous_functions,
            previous_imports=previous_imports,
        )

        response_text, generated_steps = await agent.run(
            query=None,  # Query is already in history
            images=None,  # Images are already in history
            user_id=user_id,
            session_id=session_id,
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
        user_id, session_id, include_reasoning=include_reasoning
    )


@router.get("/sessions/{user_id}", response_model=List[str])
async def get_sessions(
    user_id: str,
    redis_store: RedisStore = Depends(get_redis_store),
):
    logger.info(f"Fetching sessions for user={user_id}")
    return await redis_store.get_user_sessions(user_id)


from fastapi import WebSocket, WebSocketDisconnect


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    redis_store: RedisStore = Depends(get_redis_store),
    agent_manager: AgentManager = Depends(get_agent_manager),
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
        await redis_store.save_message(user_id, session_id, user_message)
        await redis_store.add_user_session(user_id, session_id)

        # Retrieve Context
        history = await redis_store.get_session_history(
            user_id, session_id, include_reasoning=include_reasoning
        )
        previous_functions = await redis_store.get_functions(user_id, session_id)
        previous_imports = await redis_store.get_imports(user_id, session_id)

        agent = agent_manager.get_agent(
            session_id,
            previous_functions=previous_functions,
            previous_imports=previous_imports,
        )

        # Stream Execution
        final_answer = ""
        generated_steps = (
            []
        )  # We need to reconstruct steps if we want to save them cleanly?
        # Actually run_stream yields tokens and tool outputs.
        # We need to buffer them to save to Redis afterwards.

        current_step_content = ""
        current_step_role = "assistant"  # Start assuming thought/assistant

        async for event in agent.run_stream(
            query=None,
            images=None,
            user_id=user_id,
            session_id=session_id,
            history=history,
        ):
            await websocket.send_json(event)

            # Accumulate for persistence logic (This is a simplified version,
            # ideally the Agent class should handle history internal state updates on stream too,
            # but currently persistence happens OUTSIDE the agent in the router)

            # Complexity: Creating proper 'Message' objects from stream is tricky
            # without duplicating logic from Agent.run.
            # Ideally, `run_stream` should return the final history update or we trust the Agent to return it.
            # But `run_stream` yields events.

            # For this iteration, we will rely on the `final` event to signal completion.
            # And WE WON'T PERSIST intermediate steps in this simple WS handler yet
            # UNLESS we reconstruct them.

            # TODO: Improve persistence for streaming.
            # For now, let's just save the FINAL answer if available.

            if event["type"] == "final":
                final_answer = event["content"]

        # Save Assistant Message (Final)
        if final_answer:
            assistant_message = Message(
                role="assistant",
                content=final_answer,
                timestamp=datetime.now(timezone.utc),
                is_reasoning=False,
            )
            await redis_store.save_message(user_id, session_id, assistant_message)

        # Re-save functions
        try:
            current_imports, current_functions = agent.get_all_defined_functions()
            await redis_store.save_functions(user_id, session_id, current_functions)
            await redis_store.save_imports(user_id, session_id, current_imports)
        except Exception:
            pass

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
