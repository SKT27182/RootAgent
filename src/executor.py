from typing import Any, Dict, List
from smolagents import LocalPythonExecutor

class CodeExecutor:
    def __init__(self):
        # LocalPythonExecutor is designed to be safe by default
        self.executor = LocalPythonExecutor(
            additional_authorized_imports=["math", "datetime", "re", "json", "numpy"],
            additional_functions={"print": print, "range": range, "len": len}
        )

    def execute(self, code: str) -> str:
        """
        Executes unrestricted python code using LocalPythonExecutor.
        Returns the stdout and the final result as a string.
        """
        try:
            # LocalPythonExecutor returns valid python objects (or CodeOutput tuple/object depending on version)
            # Checking signature (code_action: str)
            
            result = self.executor(code)
            return str(result)
        except Exception as e:
            return f"Execution Error: {str(e)}"
