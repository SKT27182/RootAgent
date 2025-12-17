"""
Containerized Code Executor Service

A minimal FastAPI service that executes Python code in an isolated container.
This service is called by the main backend to safely execute LLM-generated code.
"""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import traceback
import logging
import sys
from smolagents import LocalPythonExecutor

# Configure logging - using standard library since this is an isolated container
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("executor")

# Authorized imports for sandboxed execution
AUTHORIZED_IMPORTS = [
    "math.*",
    "datetime.*",
    "re.*",
    "json.*",
    "csv.*",
    "pandas.*",
    "os.*",
    "matplotlib.*",
    "seaborn.*",
    "scipy.*",
]

app = FastAPI(title="Code Executor Service", version="1.0.0")


class ExecuteRequest(BaseModel):
    """Request model for code execution."""

    code: str
    functions: Dict[str, str] = {}  # Previously defined functions {name: source}
    imports: List[str] = []  # Previously defined imports


class ExecuteResponse(BaseModel):
    """Response model for code execution."""

    result: Optional[str] = None
    error: Optional[str] = None
    is_final_answer: bool = False
    final_answer: Optional[str] = None
    new_functions: Dict[str, str] = {}  # Functions defined in this code block
    new_imports: List[str] = []  # Imports defined in this code block


class FinalAnswerException(Exception):
    """Exception to signal final answer from executed code."""

    def __init__(self, answer):
        self.answer = answer


def final_answer(answer):
    """Function available to executed code to signal completion."""
    raise FinalAnswerException(answer)


def create_executor() -> LocalPythonExecutor:
    """Create a fresh executor instance with builtins."""
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
        "open": open,
        "final_answer": final_answer,
    }

    executor = LocalPythonExecutor(
        additional_authorized_imports=AUTHORIZED_IMPORTS,
        additional_functions=builtins,
    )
    executor.send_tools({})
    return executor


def extract_definitions(code_str: str) -> tuple[Dict[str, str], List[str]]:
    """Extract function definitions and imports from code string."""
    import ast
    import textwrap

    code_str = textwrap.dedent(code_str)
    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        return {}, []

    functions = {}
    imports = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            start = node.lineno - 1
            end = node.end_lineno
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


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/execute", response_model=ExecuteResponse)
async def execute_code(request: ExecuteRequest) -> ExecuteResponse:
    """
    Execute Python code in a sandboxed environment.

    The code is executed with:
    - Previously defined functions/imports injected first
    - Standard builtins available
    - Authorized imports only
    """
    logger.info("=" * 50)
    logger.info("Received code execution request")
    logger.debug(f"Code to execute:\n{request.code}")
    logger.debug(f"Injected functions: {list(request.functions.keys())}")
    logger.debug(f"Injected imports: {request.imports}")

    try:
        executor = create_executor()
        logger.debug("Executor created successfully")

        # Inject previous imports and functions
        injected_code = ""
        if request.imports:
            injected_code += "\n".join(request.imports) + "\n\n"

        for func_name, func_source in request.functions.items():
            injected_code += func_source + "\n\n"

        # Execute injected code first (to define functions/imports)
        if injected_code.strip():
            logger.debug(f"Executing injected code:\n{injected_code}")
            executor(injected_code)
            logger.debug("Injected code executed successfully")

        # Extract new definitions from the submitted code
        new_functions, new_imports = extract_definitions(request.code)
        if new_functions:
            logger.debug(f"Extracted new functions: {list(new_functions.keys())}")
        if new_imports:
            logger.debug(f"Extracted new imports: {new_imports}")

        # Execute the actual code
        logger.info("Executing user code...")
        result = executor(request.code)
        logger.debug(f"Raw execution result: {result}")

        # Format output
        final_output = ""
        if hasattr(result, "logs") and result.logs:
            logger.debug(f"Execution logs: {result.logs}")
            final_output += str(result.logs)
        if hasattr(result, "output") and result.output is not None:
            logger.debug(f"Execution output: {result.output}")
            final_output += str(result.output)

        if not final_output and not result:
            final_output = "Execution successful (no output)."

        logger.info(
            f"Execution completed. Result: {final_output.strip() if final_output else str(result)}"
        )

        return ExecuteResponse(
            result=final_output.strip() if final_output else str(result),
            new_functions=new_functions,
            new_imports=new_imports,
        )

    except FinalAnswerException as fa:
        logger.info(f"FinalAnswerException caught: {fa.answer}")
        new_functions, new_imports = extract_definitions(request.code)
        return ExecuteResponse(
            is_final_answer=True,
            final_answer=str(fa.answer),
            new_functions=new_functions,
            new_imports=new_imports,
        )

    except Exception as e:
        # Check if wrapped FinalAnswerException
        if hasattr(e, "__context__") and isinstance(
            e.__context__, FinalAnswerException
        ):
            logger.info(f"Wrapped FinalAnswerException caught: {e.__context__.answer}")
            new_functions, new_imports = extract_definitions(request.code)
            return ExecuteResponse(
                is_final_answer=True,
                final_answer=str(e.__context__.answer),
                new_functions=new_functions,
                new_imports=new_imports,
            )

        logger.error(f"Execution error: {type(e).__name__}: {str(e)}")
        logger.debug(f"Traceback:\n{traceback.format_exc()}")
        return ExecuteResponse(
            error=f"{type(e).__name__}: {str(e)}",
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
