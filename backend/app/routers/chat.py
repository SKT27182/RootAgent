from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Any
from backend.app.models.chat import Session, Message, ChatRequest, ChatResponse
# from backend.app.agent.agent import Agent # Removed, used via AgentManager
from backend.app.services.redis_store import RedisStore
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger
import uuid
import datetime
from functools import lru_cache

router = APIRouter()
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

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    agent_manager: AgentManager = Depends(get_agent_manager)
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
        logger.warning("Query missing in request.")
        raise HTTPException(status_code=400, detail="Query is required")
    if not user_id:
        logger.warning("User ID missing in request.")
        raise HTTPException(status_code=400, detail="User ID is required")

    # Generate session_id if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
        logger.info(f"Generated new session_id: {session_id}")

    # Create User Message
    user_message = Message(
        role="user",
        content=query,
        timestamp=datetime.datetime.utcnow()
    )
    
    # Save User Message to Redis
    redis_store.save_message(user_id, session_id, user_message)

    try:
        # Run Agent
        logger.info(f"Running agent for session {session_id}")
        
        # Get history to pass to agent
        history = redis_store.get_session_history(user_id, session_id)
        
        # Get persistent functions
        previous_data = redis_store.get_functions(user_id, session_id)
        logger.debug(f"Previous functions: {previous_data}")
        
        # Get or create persistent agent
        agent = agent_manager.get_agent(session_id, previous_definitions=previous_data)
        
        response_text = agent.run(
            query=query, 
            images=images, 
            user_id=user_id, 
            session_id=session_id,
            history=history
        )
        
        # Save defined functions
        try:
            current_functions = agent.get_all_defined_functions()
            redis_store.save_functions(user_id, session_id, current_functions)
            logger.debug(f"Current functions: {current_functions}")
        except Exception as ex:
             logger.warning(f"Failed to save functions: {ex}")
        
        # Create Assistant Message
        assistant_message = Message(
            role="assistant",
            content=response_text,
            timestamp=datetime.datetime.utcnow()
        )
        
        # Save Assistant Message to Redis
        redis_store.save_message(user_id, session_id, assistant_message)
        
        logger.info(f"Chat response sent for session {session_id}")
        return ChatResponse(
            response=response_text,
            session_id=session_id,
            message_id=assistant_message.message_id
        )

    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat/history/{user_id}/{session_id}", response_model=List[Message])
async def get_history(
    user_id: str,
    session_id: str,
    redis_store: RedisStore = Depends(get_redis_store)
):
    logger.info(f"Fetching history for user={user_id}, session={session_id}")
    return redis_store.get_session_history(user_id, session_id)
