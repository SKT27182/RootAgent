"""PR 4 contracts for structured, non-base64 generated outputs."""

from __future__ import annotations

import hashlib
import asyncio
import uuid
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from matplotlib.figure import Figure
from openpyxl import Workbook
from PIL import Image
from pypdf import PdfWriter

from app.agent.executor_interface import OutputManifest
from app.agent.tools import save_artifact
from app.services.artifact_gateway import ChatArtifactGateway, bind_chat_artifact_gateway
from app.db.models import ArtifactOutputKind, ArtifactSource
from app.services.generated_outputs import (
    CollectedGeneratedOutput,
    GeneratedOutputError,
    collect_generated_outputs,
    persist_generated_outputs,
)


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["name", "amount"])
    worksheet.append(["Ada", 42])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _scalar_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


@pytest.mark.asyncio
async def test_image_save_requires_a_bound_chat_and_returns_a_small_handle(
    tmp_path,
) -> None:
    figure = Figure()
    axes = figure.subplots()
    axes.plot([1, 2, 3], [3, 1, 2])

    with pytest.raises(RuntimeError, match="active chat run"):
        save_artifact("chart.png", figure)

    output_directory = tmp_path / "outputs"
    output_directory.mkdir(mode=0o700)
    gateway = ChatArtifactGateway([], output_directory)
    with bind_chat_artifact_gateway(gateway):
        handle = await asyncio.to_thread(
            save_artifact, "../../Quarterly trend.png", figure
        )

    assert handle["kind"] == "generated_artifact"
    assert handle["content_type"] == "image/png"
    assert handle["filename"] == "Quarterly trend.png"
    assert "data:" not in str(handle)
    path = output_directory / handle["filename"]
    assert path.is_file()
    assert path.stat().st_size == handle["size"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == handle["sha256"]
    with Image.open(path) as image:
        assert image.format == "PNG"


@pytest.mark.asyncio
async def test_collects_and_content_validates_png_csv_and_xlsx(tmp_path) -> None:
    output_directory = tmp_path / "outputs"
    nested = output_directory / "tables"
    nested.mkdir(parents=True)
    (nested / "report.csv").write_bytes(b"name,amount\nAda,42\n")
    (nested / "workbook.xlsx").write_bytes(_xlsx_bytes())
    png = BytesIO()
    Image.new("RGB", (4, 3), (20, 30, 40)).save(png, format="PNG")
    (output_directory / "chart.png").write_bytes(png.getvalue())
    workspace = SimpleNamespace(output_directory=output_directory)

    outputs = await collect_generated_outputs(workspace)

    assert [item.output_kind for item in outputs] == [
        ArtifactOutputKind.PNG,
        ArtifactOutputKind.CSV,
        ArtifactOutputKind.XLSX,
    ]
    by_kind = {item.output_kind: item.manifest for item in outputs}
    assert by_kind[ArtifactOutputKind.PNG].media_type == "image/png"
    assert (by_kind[ArtifactOutputKind.PNG].width, by_kind[ArtifactOutputKind.PNG].height) == (
        4,
        3,
    )
    assert by_kind[ArtifactOutputKind.CSV].relative_path == "outputs/tables/report.csv"
    assert len(by_kind[ArtifactOutputKind.XLSX].sha256) == 64


@pytest.mark.asyncio
async def test_collects_general_safe_generated_files(tmp_path) -> None:
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    (output_directory / "result.json").write_text('{"ok": true}', encoding="utf-8")
    (output_directory / "notes.txt").write_text("hello", encoding="utf-8")
    jpeg = BytesIO()
    Image.new("RGB", (3, 2), "red").save(jpeg, format="JPEG")
    (output_directory / "image.jpg").write_bytes(jpeg.getvalue())
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with (output_directory / "document.pdf").open("wb") as handle:
        writer.write(handle)

    outputs = await collect_generated_outputs(
        SimpleNamespace(output_directory=output_directory)
    )

    assert {item.manifest.media_type for item in outputs} == {
        "application/json",
        "text/plain",
        "image/jpeg",
        "application/pdf",
    }
    assert all(item.output_kind is None for item in outputs)


@pytest.mark.asyncio
async def test_rejects_invalid_general_generated_content(tmp_path) -> None:
    output_directory = tmp_path / "outputs"
    output_directory.mkdir()
    (output_directory / "bad.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(GeneratedOutputError) as error:
        await collect_generated_outputs(SimpleNamespace(output_directory=output_directory))
    assert error.value.code == "invalid_json"


@pytest.mark.asyncio
async def test_output_collection_rejects_unsupported_files_symlinks_and_quotas(
    tmp_path,
) -> None:
    unsupported = tmp_path / "unsupported"
    unsupported.mkdir()
    (unsupported / "script.html").write_text("<script>bad()</script>")
    with pytest.raises(GeneratedOutputError) as error:
        await collect_generated_outputs(SimpleNamespace(output_directory=unsupported))
    assert error.value.code == "unsupported_generated_output"

    quota = tmp_path / "quota"
    quota.mkdir()
    (quota / "one.csv").write_text("a\n1\n")
    (quota / "two.csv").write_text("a\n2\n")
    with pytest.raises(GeneratedOutputError) as error:
        await collect_generated_outputs(
            SimpleNamespace(output_directory=quota), max_files=1
        )
    assert error.value.code == "generated_output_quota_exceeded"
    assert error.value.status_code == 413

    symlinks = tmp_path / "symlinks"
    symlinks.mkdir()
    target = tmp_path / "host.csv"
    target.write_text("secret\n")
    (symlinks / "escaped.csv").symlink_to(target)
    with pytest.raises(GeneratedOutputError) as error:
        await collect_generated_outputs(SimpleNamespace(output_directory=symlinks))
    assert error.value.code == "unsafe_generated_output"


@pytest.mark.asyncio
async def test_persistence_is_atomic_and_deduplicates_a_run_digest(tmp_path) -> None:
    path = tmp_path / "report.csv"
    data = b"name,amount\nAda,42\n"
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    manifest = OutputManifest(
        safe_name="report.csv",
        relative_path="outputs/report.csv",
        media_type="text/csv",
        size=len(data),
        sha256=digest,
    )
    output = CollectedGeneratedOutput(
        path=path,
        output_kind=ArtifactOutputKind.CSV,
        manifest=manifest,
    )

    user = MagicMock(id=uuid.uuid4())
    session_id = uuid.uuid4()
    run_id = uuid.uuid4()
    chat = MagicMock(id=uuid.uuid4(), session_id=session_id, user_id=user.id)
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(chat), _scalars_result([])]
    )
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def refresh(artifact) -> None:
        artifact.created_at = datetime.now(timezone.utc)

    db.refresh = AsyncMock(side_effect=refresh)
    db.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_stream = AsyncMock()
    storage.delete_file = AsyncMock()

    persisted = await persist_generated_outputs(
        db,
        user,
        session_id,
        run_id,
        [output, output],
        storage=storage,
    )

    assert len(persisted) == 1
    artifact = persisted[0].artifact
    assert artifact.source is ArtifactSource.GENERATED
    assert artifact.output_kind is ArtifactOutputKind.CSV
    assert artifact.sha256 == digest
    assert "/generated/" in artifact.storage_path
    assert "/runs/" not in artifact.storage_path
    assert artifact.storage_path.endswith(f"/{artifact.id}")
    assert persisted[0].metadata.content_url.endswith(f"/{artifact.id}/content")
    assert persisted[0].metadata.preview_url.endswith(f"/{artifact.id}/preview")
    storage.upload_stream.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_persistence_overwrites_same_chat_generated_filename(tmp_path) -> None:
    path = tmp_path / "trend.csv"
    data = b"name,value\nnew,2\n"
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    output = CollectedGeneratedOutput(
        path=path,
        output_kind=ArtifactOutputKind.CSV,
        manifest=OutputManifest(
            safe_name="trend.csv",
            relative_path="outputs/trend.csv",
            media_type="text/csv",
            size=len(data),
            sha256=digest,
        ),
    )

    user = MagicMock(id=uuid.uuid4())
    session_id = uuid.uuid4()
    run_id = uuid.uuid4()
    chat = MagicMock(id=uuid.uuid4(), session_id=session_id, user_id=user.id)
    prior_id = uuid.uuid4()
    prior = MagicMock(
        id=prior_id,
        user_id=user.id,
        chat_id=chat.id,
        run_id=uuid.uuid4(),
        filename="trend.csv",
        storage_path=f"{user.id}/{chat.id}/generated/{prior_id}",
        sha256="a" * 64,
        source=ArtifactSource.GENERATED,
    )
    stale = MagicMock(
        id=uuid.uuid4(),
        user_id=user.id,
        chat_id=chat.id,
        run_id=uuid.uuid4(),
        filename="trend.csv",
        storage_path=f"{user.id}/{chat.id}/generated/stale",
        sha256="b" * 64,
        source=ArtifactSource.GENERATED,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(chat), _scalars_result([prior, stale])]
    )
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_stream = AsyncMock()
    storage.delete_file = AsyncMock()

    persisted = await persist_generated_outputs(
        db,
        user,
        session_id,
        run_id,
        [output],
        storage=storage,
    )

    assert len(persisted) == 1
    assert persisted[0].artifact is prior
    assert prior.sha256 == digest
    assert prior.run_id == run_id
    assert prior.filename == "trend.csv"
    db.add.assert_not_called()
    db.delete.assert_awaited_once_with(stale)
    db.commit.assert_awaited_once()
    storage.delete_file.assert_awaited_once_with(stale.storage_path)


@pytest.mark.asyncio
async def test_persistence_removes_uploaded_objects_when_db_commit_fails(
    tmp_path,
) -> None:
    path = tmp_path / "report.csv"
    data = b"value\n1\n"
    path.write_bytes(data)
    output = CollectedGeneratedOutput(
        path=path,
        output_kind=ArtifactOutputKind.CSV,
        manifest=OutputManifest(
            safe_name="report.csv",
            relative_path="outputs/report.csv",
            media_type="text/csv",
            size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        ),
    )
    user = MagicMock(id=uuid.uuid4())
    chat = MagicMock(id=uuid.uuid4())
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[_scalar_result(chat), _scalars_result([])]
    )
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
    db.rollback = AsyncMock()
    storage = MagicMock()
    storage.upload_stream = AsyncMock()
    storage.delete_file = AsyncMock()

    with pytest.raises(RuntimeError, match="database unavailable"):
        await persist_generated_outputs(
            db,
            user,
            uuid.uuid4(),
            uuid.uuid4(),
            [output],
            storage=storage,
        )

    db.rollback.assert_awaited_once()
    storage.delete_file.assert_awaited_once()
