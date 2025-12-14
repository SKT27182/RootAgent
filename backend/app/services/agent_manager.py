from typing import Dict, Set
from backend.app.agent.agent import Agent
from backend.app.agent.tools import AGENT_TOOLS
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

    def get_agent(
        self,
        session_id: str,
        previous_functions: Dict[str, str] = {},
        previous_imports: Set[str] = set(),
    ) -> Agent:
        """
        Retrieve an existing agent for the session or create a new one.
        """
        if session_id not in self._agents:
            logger.info(f"Creating new Agent for session: {session_id}")
            self._agents[session_id] = Agent(
                additional_functions=AGENT_TOOLS,
                previous_functions=previous_functions,
                previous_imports=previous_imports,
            )
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
