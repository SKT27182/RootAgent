"""Execution backend abstraction for local or remote sandboxes."""

from typing import Any, Protocol

from app.models.agent import AgentObservation


class CodeExecutorProtocol(Protocol):
    def execute(self, code: str) -> Any:
        """Run code and return observation or FinalAnswerException."""

    def reset(self) -> None:
        """Reset executor state between sessions if needed."""
