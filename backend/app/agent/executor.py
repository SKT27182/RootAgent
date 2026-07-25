"""Local and remote code executor implementations.

``LocalCodeExecutor`` adds workspace containment and bounded async execution around
the project's AST interpreter.  It is *not* a security boundary: pandas, NumPy and
other native dependencies run in the API process and can invalidate Python-level
restrictions.  Public deployments must use an isolated executor when one becomes
available.
"""

from __future__ import annotations

import asyncio
import ast
import builtins
import hashlib
import mimetypes
import shutil
import stat
import textwrap
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.agent.constants import AUTHORIZED_IMPORTS
from app.agent.executor_interface import (
    CodeExecutorProtocol,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    OutputManifest,
    SandboxUnavailable,
    WorkspaceDescriptor,
    WorkspaceFile,
)
from app.core.config import Settings, settings
from app.utils.local_python_executor import InterpreterError, LocalPythonExecutor
from app.utils.logger import create_logger

logger = create_logger(__name__, level=settings.log_level)


class FinalAnswerException(Exception):
    """Compatibility result used by the current Agent loop."""

    def __init__(self, answer: Any):
        super().__init__(str(answer))
        self.answer = answer


def final_answer(answer: Any) -> Any:
    """Return a final answer; the AST interpreter turns this into a terminal result."""

    return answer


def extract_definitions(code_str: str) -> tuple[dict[str, str], list[str]]:
    """Extract top-level function definitions and imports for legacy diagnostics."""

    code_str = textwrap.dedent(code_str)
    try:
        tree = ast.parse(code_str)
    except SyntaxError:
        return {}, []

    functions: dict[str, str] = {}
    imports: list[str] = []
    lines = code_str.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = "".join(lines[node.lineno - 1 : node.end_lineno])
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(
                "".join(lines[node.lineno - 1 : node.end_lineno]).strip()
            )
    return functions, imports


def _truncate_utf8(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value, False
    if limit <= 0:
        return "", True
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def _contained_path(root: Path, value: str | Path) -> Path:
    """Resolve a caller path beneath root and reject symlink traversal."""

    root = root.resolve(strict=True)
    raw = Path(value)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError("Path is outside the execution workspace") from exc

    current = candidate
    while current != root:
        if current.is_symlink():
            raise PermissionError("Symlinks are not allowed in execution paths")
        current = current.parent
    return resolved


def _safe_open_for(workspace_root: Path, working_directory: Path) -> Callable[..., Any]:
    def safe_open(
        file: str | bytes | Path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable[[str, int], int] | None = None,
    ) -> Any:
        if isinstance(file, int) or opener is not None:
            raise PermissionError("File descriptors and custom openers are not allowed")
        if isinstance(file, bytes):
            file = file.decode("utf-8")
        candidate = _contained_path(
            workspace_root,
            Path(file) if Path(file).is_absolute() else working_directory / Path(file),
        )
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            candidate.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return builtins.open(
            candidate,
            mode,
            buffering=buffering,
            encoding=encoding,
            errors=errors,
            newline=newline,
            closefd=closefd,
        )

    return safe_open


def _validate_workspace_file(item: WorkspaceFile) -> None:
    relative = Path(item.relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Workspace file paths must be relative and contained")
    if item.safe_name != Path(item.safe_name).name or not item.safe_name:
        raise ValueError("Workspace file safe_name must be a basename")
    if item.size < 0:
        raise ValueError("Workspace file size cannot be negative")
    if len(item.sha256) != 64 or any(c not in "0123456789abcdef" for c in item.sha256):
        raise ValueError("Workspace file SHA-256 must be lowercase hexadecimal")


@dataclass(slots=True)
class _PreparedWorkspace:
    descriptor: WorkspaceDescriptor
    interpreter: LocalPythonExecutor
    lock: asyncio.Lock


class LocalCodeExecutor(CodeExecutorProtocol):
    """Awaitable in-process executor with a fresh interpreter per workspace/run.

    The timeout and resource settings are best effort.  In particular, Python cannot
    stop a running worker thread after a deadline.  This backend acknowledges risk; it
    does not provide process, filesystem, network, memory, or CPU isolation.
    """

    def __init__(
        self,
        additional_functions: dict[str, Callable[..., Any]] | None = None,
        *,
        workspace_root: str | Path | None = None,
        max_generated_file_bytes: int | None = None,
        max_generated_run_bytes: int | None = None,
        max_generated_files: int | None = None,
    ) -> None:
        self._additional_functions = dict(additional_functions or {})
        self._workspace_root = Path(
            workspace_root or settings.executor_workspace_root
        ).resolve()
        self._max_generated_file_bytes = (
            max_generated_file_bytes or settings.max_generated_file_bytes
        )
        self._max_generated_run_bytes = (
            max_generated_run_bytes or settings.max_generated_run_bytes
        )
        self._max_generated_files = (
            max_generated_files or settings.max_generated_files_per_run
        )
        self._workspaces: dict[UUID, _PreparedWorkspace] = {}
        self._closed = False

    def _new_interpreter(self) -> LocalPythonExecutor:
        authorized_imports = [
            item
            for item in AUTHORIZED_IMPORTS
            if item.split(".", 1)[0] not in {"os", "pathlib", "subprocess", "sys"}
        ]
        functions = {**self._additional_functions, "final_answer": final_answer}
        interpreter = LocalPythonExecutor(
            additional_authorized_imports=authorized_imports,
            max_print_outputs_length=settings.executor_stdout_max_bytes,
            additional_functions=functions,
        )
        interpreter.send_tools(functions)
        return interpreter

    async def prepare_workspace(
        self,
        *,
        run_id: UUID,
        workspace_id: UUID | None = None,
        input_files: Sequence[WorkspaceFile] = (),
    ) -> WorkspaceDescriptor:
        if self._closed:
            raise RuntimeError("Executor is closed")
        for item in input_files:
            _validate_workspace_file(item)

        identifier = workspace_id or uuid4()
        if identifier in self._workspaces:
            raise ValueError("Workspace already exists")

        root = self._workspace_root / str(identifier)

        def create_directories() -> None:
            self._workspace_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root.mkdir(mode=0o700, exist_ok=False)
            (root / "inputs").mkdir(mode=0o700)
            (root / "outputs").mkdir(mode=0o700)
            root.chmod(0o700)

        await asyncio.to_thread(create_directories)
        descriptor = WorkspaceDescriptor(
            workspace_id=identifier,
            run_id=run_id,
            code_visible_root=str(root),
            input_directory=root / "inputs",
            output_directory=root / "outputs",
            input_files=tuple(input_files),
        )
        try:
            interpreter = await asyncio.to_thread(self._new_interpreter)
        except Exception:
            await asyncio.to_thread(shutil.rmtree, root, True)
            raise
        self._workspaces[identifier] = _PreparedWorkspace(
            descriptor=descriptor,
            interpreter=interpreter,
            lock=asyncio.Lock(),
        )
        return descriptor

    def _get_workspace(self, descriptor: WorkspaceDescriptor) -> _PreparedWorkspace:
        prepared = self._workspaces.get(descriptor.workspace_id)
        if prepared is None or prepared.descriptor != descriptor:
            raise ValueError("Workspace was not prepared by this executor")
        return prepared

    @staticmethod
    def _execute_sync(
        prepared: _PreparedWorkspace,
        request: ExecutionRequest,
        workspace_root: Path,
        working_directory: Path,
    ) -> tuple[str, str | None]:
        functions = {
            **prepared.interpreter.additional_functions,
            "open": _safe_open_for(workspace_root, working_directory),
            "final_answer": final_answer,
        }
        prepared.interpreter.send_tools(functions)
        result = prepared.interpreter(request.code)
        stdout = result.logs
        if result.output is not None:
            stdout += str(result.output)
        return stdout, str(result.output) if result.is_final_answer else None

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        prepared = self._get_workspace(request.workspace)
        if request.deadline_seconds <= 0:
            raise ValueError("Execution deadline must be positive")
        if request.stdout_max_bytes < 0 or request.stderr_max_bytes < 0:
            raise ValueError("Output caps cannot be negative")

        workspace_root = Path(prepared.descriptor.code_visible_root).resolve(strict=True)
        working_directory = _contained_path(workspace_root, request.working_directory)
        if not working_directory.is_dir():
            raise ValueError("Execution working directory does not exist")

        started = time.monotonic()
        async with prepared.lock:
            task = asyncio.create_task(
                asyncio.to_thread(
                    self._execute_sync,
                    prepared,
                    request,
                    workspace_root,
                    working_directory,
                )
            )
            try:
                stdout, final_result = await asyncio.wait_for(
                    asyncio.shield(task), timeout=request.deadline_seconds
                )
            except TimeoutError:
                # The thread may still be running.  This is one reason local mode is
                # explicitly not an isolation boundary.
                task.add_done_callback(
                    lambda completed: completed.exception()
                    if not completed.cancelled()
                    else None
                )
                stderr, stderr_truncated = _truncate_utf8(
                    "Execution exceeded its deadline", request.stderr_max_bytes
                )
                return ExecutionResult(
                    status=ExecutionStatus.TIMED_OUT,
                    exit_code=None,
                    stdout="",
                    stderr=stderr,
                    stdout_truncated=False,
                    stderr_truncated=stderr_truncated,
                    duration_seconds=time.monotonic() - started,
                )
            except asyncio.CancelledError:
                task.cancel()
                raise
            except Exception as exc:
                logger.info("Local code execution failed: %s", type(exc).__name__)
                stderr, stderr_truncated = _truncate_utf8(
                    str(exc), request.stderr_max_bytes
                )
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    exit_code=1,
                    stdout="",
                    stderr=stderr,
                    stdout_truncated=False,
                    stderr_truncated=stderr_truncated,
                    duration_seconds=time.monotonic() - started,
                )

        stdout, stdout_truncated = _truncate_utf8(stdout, request.stdout_max_bytes)
        manifests = await self.collect_outputs(prepared.descriptor)
        return ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            exit_code=0,
            stdout=stdout,
            stderr="",
            stdout_truncated=stdout_truncated,
            stderr_truncated=False,
            duration_seconds=time.monotonic() - started,
            output_manifests=manifests,
            final_answer=final_result,
        )

    def _collect_outputs_sync(
        self, descriptor: WorkspaceDescriptor
    ) -> tuple[OutputManifest, ...]:
        output_root = descriptor.output_directory.resolve(strict=True)
        manifests: list[OutputManifest] = []
        total_size = 0
        for path in sorted(output_root.rglob("*")):
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("Executor outputs cannot contain symlinks")
            if not stat.S_ISREG(mode):
                continue
            resolved = path.resolve(strict=True)
            try:
                relative = resolved.relative_to(output_root)
            except ValueError as exc:
                raise ValueError("Executor output escaped the workspace") from exc
            size = resolved.stat().st_size
            if size > self._max_generated_file_bytes:
                raise ValueError("Executor output exceeds the per-file quota")
            total_size += size
            if total_size > self._max_generated_run_bytes:
                raise ValueError("Executor outputs exceed the per-run quota")
            if len(manifests) >= self._max_generated_files:
                raise ValueError("Executor produced too many output files")

            digest = hashlib.sha256()
            with builtins.open(resolved, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
            manifests.append(
                OutputManifest(
                    safe_name=resolved.name,
                    relative_path=(Path("outputs") / relative).as_posix(),
                    media_type=media_type,
                    size=size,
                    sha256=digest.hexdigest(),
                )
            )
        return tuple(manifests)

    async def collect_outputs(
        self, workspace: WorkspaceDescriptor
    ) -> tuple[OutputManifest, ...]:
        prepared = self._get_workspace(workspace)
        return await asyncio.to_thread(
            self._collect_outputs_sync, prepared.descriptor
        )

    async def destroy(self, workspace: WorkspaceDescriptor) -> None:
        prepared = self._workspaces.pop(workspace.workspace_id, None)
        if prepared is None:
            return
        root = Path(prepared.descriptor.code_visible_root)
        await asyncio.to_thread(shutil.rmtree, root, True)

    async def close(self) -> None:
        workspaces = [item.descriptor for item in self._workspaces.values()]
        for workspace in workspaces:
            await self.destroy(workspace)
        self._closed = True


class GrpcCodeExecutor(CodeExecutorProtocol):
    """Lifecycle-compatible placeholder for the future remote runtime."""

    def __init__(self, app_settings: Settings = settings) -> None:
        if not app_settings.grpc_executor_target.strip():
            raise ValueError("GRPC_EXECUTOR_TARGET is required for the gRPC backend")
        cert_fields = (
            app_settings.grpc_executor_client_cert,
            app_settings.grpc_executor_client_key,
        )
        if bool(cert_fields[0]) != bool(cert_fields[1]):
            raise ValueError(
                "GRPC_EXECUTOR_CLIENT_CERT and GRPC_EXECUTOR_CLIENT_KEY must be set together"
            )
        self.target = app_settings.grpc_executor_target
        self.tls_enabled = app_settings.grpc_executor_tls

    @staticmethod
    def _unavailable() -> SandboxUnavailable:
        return SandboxUnavailable(
            "The gRPC sandbox backend is configured but is not implemented"
        )

    async def prepare_workspace(
        self,
        *,
        run_id: UUID,
        workspace_id: UUID | None = None,
        input_files: Sequence[WorkspaceFile] = (),
    ) -> WorkspaceDescriptor:
        raise self._unavailable()

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raise self._unavailable()

    async def collect_outputs(
        self, workspace: WorkspaceDescriptor
    ) -> tuple[OutputManifest, ...]:
        raise self._unavailable()

    async def destroy(self, workspace: WorkspaceDescriptor) -> None:
        raise self._unavailable()

    async def close(self) -> None:
        return None


def create_code_executor(
    additional_functions: dict[str, Callable[..., Any]] | None = None,
    *,
    app_settings: Settings = settings,
) -> CodeExecutorProtocol:
    """Build the selected executor without pretending the gRPC stub is ready."""

    if app_settings.executor_backend == "grpc":
        return GrpcCodeExecutor(app_settings)
    return LocalCodeExecutor(
        additional_functions=additional_functions,
        workspace_root=app_settings.executor_workspace_root,
        max_generated_file_bytes=app_settings.max_generated_file_bytes,
        max_generated_run_bytes=app_settings.max_generated_run_bytes,
        max_generated_files=app_settings.max_generated_files_per_run,
    )


class CodeExecutor:
    """Compatibility adapter for ``Agent`` while chat orchestration is migrated.

    It preserves the old constructor and string observation while executing through
    the async lifecycle.  Every adapter instance owns one fresh run workspace.
    """

    def __init__(self, additional_functions: dict[str, Any] | None = None):
        self.defined_functions: dict[str, str] = {}
        self.defined_imports: set[str] = set()
        self._backend = create_code_executor(additional_functions or {})
        self._workspace: WorkspaceDescriptor | None = None
        self._run_id = uuid4()
        self._reset_requested = False

    async def execute(self, code: str) -> Any:
        new_functions, new_imports = extract_definitions(code)
        self.defined_functions.update(new_functions)
        self.defined_imports.update(new_imports)

        if self._reset_requested and self._workspace is not None:
            await self._backend.destroy(self._workspace)
            self._workspace = None
            self._run_id = uuid4()
            self._reset_requested = False
        if self._workspace is None:
            self._workspace = await self._backend.prepare_workspace(run_id=self._run_id)

        result = await self._backend.execute(
            ExecutionRequest(
                code=code,
                workspace=self._workspace,
                deadline_seconds=settings.executor_default_deadline_seconds,
                stdout_max_bytes=settings.executor_stdout_max_bytes,
                stderr_max_bytes=settings.executor_stderr_max_bytes,
            )
        )
        if result.status is ExecutionStatus.SANDBOX_UNAVAILABLE:
            raise SandboxUnavailable()
        if result.status is not ExecutionStatus.SUCCEEDED:
            raise InterpreterError(result.stderr or f"Execution {result.status.value}")
        if result.final_answer is not None:
            return FinalAnswerException(result.final_answer)
        return result.stdout.strip() or "Execution successful (no output)."

    def reset(self) -> None:
        self.defined_functions = {}
        self.defined_imports = set()
        self._reset_requested = True

    async def close(self) -> None:
        await self._backend.close()
        self._workspace = None


__all__ = [
    "CodeExecutor",
    "FinalAnswerException",
    "GrpcCodeExecutor",
    "LocalCodeExecutor",
    "create_code_executor",
    "extract_definitions",
]
