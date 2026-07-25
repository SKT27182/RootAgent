"""Typed, asynchronous contracts for code execution backends.

The contracts deliberately describe workspaces and their files without carrying file
contents.  Artifact bytes are staged by the storage layer and verified against this
metadata before an execution request is submitted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID


class ExecutionStatus(StrEnum):
    """Stable outcomes shared by local and remote executor backends."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"


@dataclass(frozen=True, slots=True)
class WorkspaceFile:
    artifact_id: UUID
    safe_name: str
    relative_path: str
    media_type: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class WorkspaceDescriptor:
    workspace_id: UUID
    run_id: UUID
    code_visible_root: str
    input_directory: Path
    output_directory: Path
    input_files: tuple[WorkspaceFile, ...] = ()


@dataclass(frozen=True, slots=True)
class ResourceSettings:
    """Best-effort resource requests; only isolated backends can enforce all fields."""

    memory_bytes: int | None = None
    cpu_time_seconds: float | None = None
    process_limit: int | None = None


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    code: str
    workspace: WorkspaceDescriptor
    working_directory: str = "."
    deadline_seconds: float = 120.0
    stdout_max_bytes: int = 64 * 1024
    stderr_max_bytes: int = 64 * 1024
    resources: ResourceSettings = field(default_factory=ResourceSettings)


@dataclass(frozen=True, slots=True)
class OutputManifest:
    safe_name: str
    relative_path: str
    media_type: str
    size: int
    sha256: str
    creation_source: str = "code_executor"
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionStatus
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_seconds: float
    output_manifests: tuple[OutputManifest, ...] = ()
    final_answer: str | None = None


class SandboxUnavailable(RuntimeError):
    """Stable executor error mapped by the API layer to HTTP 503."""

    code = "sandbox_unavailable"
    retryable = True

    def __init__(self, message: str = "The configured sandbox is unavailable") -> None:
        super().__init__(message)


@runtime_checkable
class CodeExecutorProtocol(Protocol):
    async def prepare_workspace(
        self,
        *,
        run_id: UUID,
        workspace_id: UUID | None = None,
        input_files: Sequence[WorkspaceFile] = (),
    ) -> WorkspaceDescriptor:
        """Create a private workspace for one run."""

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run code in a prepared workspace."""

    async def collect_outputs(
        self, workspace: WorkspaceDescriptor
    ) -> tuple[OutputManifest, ...]:
        """Describe regular files created in the workspace output directory."""

    async def destroy(self, workspace: WorkspaceDescriptor) -> None:
        """Destroy a workspace idempotently."""

    async def close(self) -> None:
        """Release backend-wide resources."""
