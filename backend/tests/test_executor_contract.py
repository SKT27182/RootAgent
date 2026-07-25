from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.executor import GrpcCodeExecutor, LocalCodeExecutor, create_code_executor
from app.agent.executor_interface import (
    CodeExecutorProtocol,
    ExecutionRequest,
    ExecutionStatus,
    SandboxUnavailable,
    WorkspaceFile,
)


@pytest.mark.asyncio
async def test_local_executor_has_fresh_state_per_run(tmp_path: Path) -> None:
    executor = LocalCodeExecutor(workspace_root=tmp_path)
    first = await executor.prepare_workspace(run_id=uuid4())
    second = await executor.prepare_workspace(run_id=uuid4())
    try:
        result = await executor.execute(
            ExecutionRequest(code="value = 41\nprint(value + 1)", workspace=first)
        )
        assert result.status is ExecutionStatus.SUCCEEDED
        assert result.stdout == "42\n"

        persisted = await executor.execute(
            ExecutionRequest(code="print(value)", workspace=first)
        )
        assert persisted.status is ExecutionStatus.SUCCEEDED
        assert persisted.stdout == "41\n"

        fresh = await executor.execute(
            ExecutionRequest(code="print(value)", workspace=second)
        )
        assert fresh.status is ExecutionStatus.FAILED
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_local_executor_contains_paths_and_removes_os_import(tmp_path: Path) -> None:
    executor = LocalCodeExecutor(workspace_root=tmp_path)
    workspace = await executor.prepare_workspace(run_id=uuid4())
    try:
        host_read = await executor.execute(
            ExecutionRequest(code="open('/etc/passwd').read()", workspace=workspace)
        )
        assert host_read.status is ExecutionStatus.FAILED
        assert "outside the execution workspace" in host_read.stderr

        os_import = await executor.execute(
            ExecutionRequest(code="import os", workspace=workspace)
        )
        assert os_import.status is ExecutionStatus.FAILED
        assert "Import of os is not allowed" in os_import.stderr
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_local_executor_collects_hashed_outputs_and_cleans_up(
    tmp_path: Path,
) -> None:
    executor = LocalCodeExecutor(workspace_root=tmp_path)
    workspace = await executor.prepare_workspace(run_id=uuid4())
    root = Path(workspace.code_visible_root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700

    result = await executor.execute(
        ExecutionRequest(
            code=(
                "handle = open('outputs/result.csv', 'w')\n"
                "handle.write('name,value\\na,1\\n')\n"
                "handle.close()"
            ),
            workspace=workspace,
        )
    )
    assert result.status is ExecutionStatus.SUCCEEDED
    assert len(result.output_manifests) == 1
    manifest = result.output_manifests[0]
    payload = b"name,value\na,1\n"
    assert manifest.relative_path == "outputs/result.csv"
    assert manifest.media_type == "text/csv"
    assert manifest.sha256 == hashlib.sha256(payload).hexdigest()
    assert manifest.size == len(payload)

    await executor.destroy(workspace)
    await executor.destroy(workspace)
    assert not root.exists()
    await executor.close()


@pytest.mark.asyncio
async def test_local_executor_enforces_output_and_deadline_caps(tmp_path: Path) -> None:
    executor = LocalCodeExecutor(workspace_root=tmp_path)
    workspace = await executor.prepare_workspace(run_id=uuid4())
    try:
        capped = await executor.execute(
            ExecutionRequest(
                code="print('abcdefghij')",
                workspace=workspace,
                stdout_max_bytes=5,
            )
        )
        assert capped.status is ExecutionStatus.SUCCEEDED
        assert capped.stdout == "abcde"
        assert capped.stdout_truncated is True

        timed_out = await executor.execute(
            ExecutionRequest(
                code="while True:\n    pass",
                workspace=workspace,
                deadline_seconds=0.001,
            )
        )
        assert timed_out.status is ExecutionStatus.TIMED_OUT
        assert timed_out.exit_code is None
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_workspace_file_rejects_traversal(tmp_path: Path) -> None:
    executor = LocalCodeExecutor(workspace_root=tmp_path)
    item = WorkspaceFile(
        artifact_id=uuid4(),
        safe_name="data.csv",
        relative_path="../data.csv",
        media_type="text/csv",
        size=0,
        sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="relative and contained"):
        await executor.prepare_workspace(run_id=uuid4(), input_files=(item,))


@pytest.mark.asyncio
async def test_grpc_stub_validates_settings_and_is_stably_unavailable() -> None:
    missing = SimpleNamespace(
        grpc_executor_target="",
        grpc_executor_client_cert=None,
        grpc_executor_client_key=None,
        grpc_executor_tls=True,
    )
    with pytest.raises(ValueError, match="GRPC_EXECUTOR_TARGET"):
        GrpcCodeExecutor(missing)  # type: ignore[arg-type]

    configured = SimpleNamespace(
        executor_backend="grpc",
        grpc_executor_target="sandbox.internal:443",
        grpc_executor_client_cert=None,
        grpc_executor_client_key=None,
        grpc_executor_tls=True,
    )
    executor = create_code_executor(app_settings=configured)  # type: ignore[arg-type]
    assert isinstance(executor, CodeExecutorProtocol)
    with pytest.raises(SandboxUnavailable) as exc_info:
        await executor.prepare_workspace(run_id=uuid4())
    assert exc_info.value.code == "sandbox_unavailable"
    assert exc_info.value.retryable is True
