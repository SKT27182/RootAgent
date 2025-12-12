from typing import Any, Dict, List
import ast
import textwrap
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


def extract_definitions(code_str: str) -> tuple[Dict[str, str], List[str]]:
    """
    Extracts all top-level function definitions and import statements from a Python code string.
    Returns a tuple: ({function_name: function_source_code}, [import_statements])
    """
    code_str = textwrap.dedent(code_str)
    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        return {}, []

    functions = {}
    imports = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            # AST stores start and end line numbers
            start = node.lineno - 1
            end = node.end_lineno

            # Extract the exact function text
            # splitlines behaves differently if last line has newline or not
            lines = code_str.splitlines(keepends=True)
            func_code = "".join(lines[start:end])

            functions[node.name] = func_code

        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno
            lines = code_str.splitlines(keepends=True)
            import_code = "".join(lines[start:end]).strip()
            imports.append(import_code)

    return functions, imports


class CodeExecutor:
    def __init__(self, additional_functions: Dict[str, Any] = {}):
        self.defined_functions = {}  # Track functions defined across executions
        self.defined_imports = set()  # Track imports defined across executions

        # Standard built-ins to allow
        builtins = {
            "print": print,
            "range": range,
            "len": len,
            "int": int,
            "float": float,
            "bool": bool,
            "str": str,
            "list": list,
            "tuple": tuple,
            "dict": dict,
            "set": set,
            "round": round,
            "sum": sum,
            "max": max,
            "min": min,
            "abs": abs,
            "enumerate": enumerate,
            "zip": zip,
            "final_answer": final_answer,
        }

        # Merge provided functions with builtins (builtins take precedence primarily, but actually we want tools to be available)
        # We'll merge them into builtins so they are available in the global scope of the executor
        builtins.update(additional_functions)

        # LocalPythonExecutor is designed to be safe by default
        self.executor = LocalPythonExecutor(
            additional_authorized_imports=AUTHORIZED_IMPORTS,
            additional_functions=builtins,
        )
        # CRITICAL: Must call send_tools to merge additional_functions into static_tools
        self.executor.send_tools(additional_functions)

    def execute(self, code: str) -> Any:
        """
        Executes unrestricted python code using LocalPythonExecutor.
        Returns the stdout/result or specific FinalAnswer object.
        """
        # Extract new functions from this code block
        new_functions, new_imports = extract_definitions(code)
        if new_functions:
            self.defined_functions.update(new_functions)
            logger.debug(f"Extracted functions: {list(new_functions.keys())}")
        if new_imports:
            for imp in new_imports:
                self.defined_imports.add(imp)
            logger.debug(f"Extracted imports: {new_imports}")

        try:
            logger.debug("Executing code...")
            result = self.executor(code)
            logger.debug("Execution successful.")

            # Format output for Agent consumption
            # smolagents returns (output, logs, error) or object with these fields?
            # Based on logs it returns a named tuple or object str: CodeOutput(output=..., logs=..., ...)
            # We want to return logs + output.

            final_output = ""
            if hasattr(result, "logs") and result.logs:
                final_output += str(result.logs)

            if hasattr(result, "output") and result.output is not None:
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
            if hasattr(e, "__context__") and isinstance(
                e.__context__, FinalAnswerException
            ):
                return e.__context__

            logger.error(f"Execution Error: {str(e)}")
            return f"Execution Error: {str(e)}"
