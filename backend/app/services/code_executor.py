"""
Code Executor Client

HTTP client for the containerized code execution service.
All execution logic lives in executor/executor_service.py
"""

from typing import Any, Dict

from backend.app.core.config import Config
from backend.app.utils.logger import create_logger

logger = create_logger(__name__, level=Config.LOG_LEVEL)


class FinalAnswerException(Exception):
    """Exception to signal final answer from executed code."""

    def __init__(self, answer):
        self.answer = answer


class CodeExecutor:
    """
    Code executor that runs code in a separate Docker container.
    Communicates with the executor service via HTTP.
    """

    def __init__(
        self,
        executor_url: str = None,
        additional_functions: Dict[str, Any] = {},
        timeout: float = 30.0,
    ):
        import httpx

        self.executor_url = executor_url or Config.EXECUTOR_URL
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)
        self.async_client = httpx.AsyncClient(timeout=timeout)

        self.defined_functions: Dict[str, str] = {}
        self.defined_imports: set = set()

        # Note: additional_functions (callable tools) can't be serialized to container
        # They would need to be defined as code in the executor service itself
        self._additional_functions = additional_functions

    def execute(self, code: str) -> Any:
        """
        Execute code in containerized environment.
        Synchronous version.
        """
        try:
            response = self.client.post(
                f"{self.executor_url}/execute",
                json={
                    "code": code,
                    "functions": self.defined_functions,
                    "imports": list(self.defined_imports),
                },
            )
            response.raise_for_status()
            result = response.json()

            # Update tracked definitions
            if result.get("new_functions"):
                self.defined_functions.update(result["new_functions"])
            if result.get("new_imports"):
                for imp in result["new_imports"]:
                    self.defined_imports.add(imp)

            # Handle different result types
            if result.get("error"):
                raise Exception(result["error"])

            if result.get("is_final_answer"):
                return FinalAnswerException(result["final_answer"])

            return result.get("result", "Execution successful (no output).")

        except Exception as e:
            if isinstance(e, FinalAnswerException):
                raise
            logger.error(f"Execution Error: {str(e)}")
            raise

    async def aexecute(self, code: str) -> Any:
        """
        Execute code in containerized environment.
        Async version.
        """
        try:
            response = await self.async_client.post(
                f"{self.executor_url}/execute",
                json={
                    "code": code,
                    "functions": self.defined_functions,
                    "imports": list(self.defined_imports),
                },
            )
            response.raise_for_status()
            result = response.json()

            # Update tracked definitions
            if result.get("new_functions"):
                self.defined_functions.update(result["new_functions"])
            if result.get("new_imports"):
                for imp in result["new_imports"]:
                    self.defined_imports.add(imp)

            # Handle different result types
            if result.get("error"):
                raise Exception(result["error"])

            if result.get("is_final_answer"):
                return FinalAnswerException(result["final_answer"])

            return result.get("result", "Execution successful (no output).")

        except Exception as e:
            if isinstance(e, FinalAnswerException):
                raise
            logger.error(f"Execution Error: {str(e)}")
            raise

    def __del__(self):
        """Cleanup HTTP clients."""
        try:
            self.client.close()
        except Exception:
            pass
