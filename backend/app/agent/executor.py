from typing import Any, Dict, List
from smolagents import LocalPythonExecutor

from backend.app.agent.constants import AUTHORIZED_IMPORTS
from backend.app.core.config import Config
from backend.app.utils.logger import create_logger

logger = create_logger(__name__, level=Config.LOG_LEVEL)

class FinalAnswerException(Exception):
    def __init__(self, answer):
        self.answer = answer

def final_answer(answer):
    raise FinalAnswerException(answer)

class CodeExecutor:
    def __init__(self):
        # Standard built-ins to allow
        builtins = {
            "print": print, "range": range, "len": len,
            "int": int, "float": float, "bool": bool, "str": str,
            "list": list, "tuple": tuple, "dict": dict, "set": set,
            "round": round, "sum": sum, "max": max, "min": min, "abs": abs,
            "enumerate": enumerate, "zip": zip,
            "final_answer": final_answer
        }
        
        # LocalPythonExecutor is designed to be safe by default
        self.executor = LocalPythonExecutor(
            additional_authorized_imports=AUTHORIZED_IMPORTS,
            additional_functions=builtins
        )
        # CRITICAL: Must call send_tools to merge additional_functions into static_tools
        self.executor.send_tools({})

    def execute(self, code: str) -> Any:
        """
        Executes unrestricted python code using LocalPythonExecutor.
        Returns the stdout/result or specific FinalAnswer object.
        """
        try:
            logger.debug("Executing code...")
            result = self.executor(code)
            logger.debug("Execution successful.")
            
            # Format output for Agent consumption
            # smolagents returns (output, logs, error) or object with these fields?
            # Based on logs it returns a named tuple or object str: CodeOutput(output=..., logs=..., ...)
            # We want to return logs + output.
            
            final_output = ""
            if hasattr(result, 'logs') and result.logs:
                final_output += str(result.logs)
            
            if hasattr(result, 'output') and result.output is not None:
                # If output exists (last expression value), append it if not None
                final_output += str(result.output)
            
            # If everything empty (e.g. valid code but no print/return), returns empty string?
            if not final_output and not result:
                 return "Execution successful (no output)."
            
            return final_output.strip() if final_output else str(result)
        except FinalAnswerException as fa:
            return fa
        except Exception as e:
            # Unwrap InterpreterError if it wraps FinalAnswerException
            # smolagents raises InterpreterError(... from None) or implicit context?
            # Based on code reading, it's just raise InterpreterError(...)
            # So we check __context__
            if hasattr(e, "__context__") and isinstance(e.__context__, FinalAnswerException):
                return e.__context__
            
            logger.error(f"Execution Error: {str(e)}")
            return f"Execution Error: {str(e)}"
