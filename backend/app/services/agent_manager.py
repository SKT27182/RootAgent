from typing import Dict
from backend.app.agent.agent import Agent
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger

logger = create_logger(__name__, level=Config.LOG_LEVEL)

class AgentManager:
    _instance = None
    _agents: Dict[str, Agent] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentManager, cls).__new__(cls)
            cls._instance._agents = {}
        return cls._instance

    def get_agent(self, session_id: str, previous_definitions: Dict[str, str] = None) -> Agent:
        """
        Retrieve an existing agent for the session or create a new one.
        """
        if session_id not in self._agents:
            logger.info(f"Creating new Agent for session: {session_id}")
            self._agents[session_id] = Agent(previous_definitions=previous_definitions)
        else:
            logger.info(f"Reusing existing Agent for session: {session_id}")
            # Optional: if we wanted to enforce syncing, we could update the existing agent here,
            # but usually the in-memory agent is more up to date than redis if consistent.
            
        return self._agents[session_id]

    def clear_agent(self, session_id: str):
        """
        Remove an agent from memory (e.g. on session close/expiry).
        """
        if session_id in self._agents:
            del self._agents[session_id]
            logger.info(f"Cleared Agent for session: {session_id}")
