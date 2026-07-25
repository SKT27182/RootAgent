from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

import pandas as pd
import pytest

from app.db.models import ArtifactSource
from app.services.artifact_gateway import (
    ArtifactGatewayError,
    CatalogEntry,
    ChatArtifactGateway,
)


class Storage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.deleted: list[str] = []

    async def open_download(self, path: str):
        data = self.objects[path]

        async def chunks():
            for offset in range(0, len(data), 3):
                yield data[offset : offset + 3]

        return chunks()

    async def delete_file(self, path: str) -> None:
        self.deleted.append(path)
        self.objects.pop(path, None)


def entry(
    filename: str,
    data: bytes,
    content_type: str,
    source: ArtifactSource,
    key: str,
) -> CatalogEntry:
    return CatalogEntry(
        ref=f"artifact_{uuid.uuid4().hex}",
        filename=filename,
        source=source,
        content_type=content_type,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_at=datetime.now(timezone.utc),
        storage_path=key,
    )


@pytest.mark.asyncio
async def test_list_and_read_both_sources_as_dataframe_or_buffer(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    csv = b"name,value\nAda,42\nGrace,7\n"
    image = b"not-decoded-by-the-gateway"
    upload = entry("input.csv", csv, "text/csv", ArtifactSource.UPLOAD, "upload")
    generated = entry(
        "result.bin", image, "application/octet-stream", ArtifactSource.GENERATED, "generated"
    )
    gateway = ChatArtifactGateway(
        [upload, generated], output, storage=Storage({"upload": csv, "generated": image})
    )

    listing = gateway.list_artifacts()
    assert listing["filenames"] == ["input.csv", "result.bin"] or set(listing["filenames"]) == {
        "input.csv",
        "result.bin",
    }
    assert "storage_path" not in str(listing)
    assert "ref" not in str(listing)
    detailed = gateway.list_artifacts(detail=True)
    assert {item["source"] for item in detailed["items"]} == {"upload", "generated"}
    assert len(gateway.list_artifacts("generated")["filenames"]) == 1

    frame = await asyncio.to_thread(gateway.read_artifact, upload.ref)
    assert isinstance(frame, pd.DataFrame)
    assert frame.to_dict("records") == [
        {"name": "Ada", "value": 42},
        {"name": "Grace", "value": 7},
    ]
    buffer = await asyncio.to_thread(gateway.read_artifact, generated.ref)
    assert buffer.read() == image
    gateway.close()
    assert buffer.closed


@pytest.mark.asyncio
async def test_gateway_rejects_unknown_names_and_blocks_upload_name_overwrite(
    tmp_path: Path,
) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    data = b"a\n1\n"
    upload = entry("same.csv", data, "text/csv", ArtifactSource.UPLOAD, "one")
    gateway = ChatArtifactGateway(
        [upload], output, storage=Storage({"one": data})
    )

    with pytest.raises(ArtifactGatewayError, match="uploaded artifact"):
        await asyncio.to_thread(gateway.save_artifact, "same.csv", "a\n2\n")
    with pytest.raises(ArtifactGatewayError, match="current chat"):
        await asyncio.to_thread(gateway.read_artifact, f"artifact_{uuid.uuid4().hex}")


@pytest.mark.asyncio
async def test_saved_artifacts_keep_exact_name_and_overwrite_same_chat_generated(
    tmp_path: Path,
) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    gateway = ChatArtifactGateway([], output, storage=Storage({}))

    first = await asyncio.to_thread(
        gateway.save_artifact, "report.json", {"status": "ok"}
    )
    second = await asyncio.to_thread(
        gateway.save_artifact, "report.json", {"status": "new"}
    )
    csv_handle = await asyncio.to_thread(
        gateway.save_artifact, "rows.csv", "name,value\nAda,42\n"
    )
    xlsx_handle = await asyncio.to_thread(
        gateway.save_artifact, "rows.xlsx", pd.DataFrame([{"value": 42}])
    )
    text_buffer = BytesIO(b"buffered text")
    text_handle = await asyncio.to_thread(
        gateway.save_artifact, "notes.txt", text_buffer
    )

    assert first["filename"] == "report.json"
    assert second["filename"] == "report.json"
    assert first["ref"] == second["ref"]
    assert first["sha256"] != second["sha256"]
    assert len(gateway.list_artifacts("generated")["filenames"]) == 4
    assert {csv_handle["content_type"], xlsx_handle["content_type"], text_handle["content_type"]} == {
        "text/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
    }
    assert text_buffer.tell() == 0
    buffer = await asyncio.to_thread(
        gateway.read_artifact, first["ref"], "buffer"
    )
    assert b'"status": "new"' in buffer.read()
    assert (output / "report.json").is_file()
    gateway.close()


@pytest.mark.asyncio
async def test_save_overwrites_prior_generated_not_upload_in_same_chat(
    tmp_path: Path,
) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    prior = entry(
        "trend.csv",
        b"name,value\nold,1\n",
        "text/csv",
        ArtifactSource.GENERATED,
        "prior-generated",
    )
    upload = entry(
        "input.csv",
        b"name,value\nup,1\n",
        "text/csv",
        ArtifactSource.UPLOAD,
        "upload",
    )
    gateway = ChatArtifactGateway(
        [prior, upload],
        output,
        storage=Storage(
            {
                "prior-generated": b"name,value\nold,1\n",
                "upload": b"name,value\nup,1\n",
            }
        ),
    )

    saved = await asyncio.to_thread(
        gateway.save_artifact, "trend.csv", "name,value\nnew,2\n"
    )
    assert saved["ref"] == prior.ref
    assert saved["filename"] == "trend.csv"
    assert len(gateway.list_artifacts("generated")["filenames"]) == 1
    assert len(gateway.list_artifacts("upload")["filenames"]) == 1
    frame = await asyncio.to_thread(gateway.read_artifact, "trend.csv")
    assert list(frame.columns) == ["name", "value"]
    assert frame.iloc[0]["name"] == "new"
    assert int(frame.iloc[0]["value"]) == 2
    gateway.close()


def test_uploaded_prompt_entries_exclude_generated(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    upload = entry("sales.csv", b"a\n1\n", "text/csv", ArtifactSource.UPLOAD, "u")
    generated = entry(
        "plot.png", b"x", "image/png", ArtifactSource.GENERATED, "g"
    )

    async def construct() -> ChatArtifactGateway:
        return ChatArtifactGateway(
            [upload, generated], output, storage=Storage({"u": b"a\n1\n", "g": b"x"})
        )

    gateway = asyncio.run(construct())
    assert gateway.uploaded_prompt_entries() == [
        {
            "filename": "sales.csv",
            "ref": upload.ref,
            "content_type": "text/csv",
            "size": len(b"a\n1\n"),
        }
    ]


def test_list_limits_and_filters_are_validated(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()

    async def construct() -> ChatArtifactGateway:
        return ChatArtifactGateway([], output, storage=Storage({}))

    gateway = asyncio.run(construct())
    with pytest.raises(ArtifactGatewayError):
        gateway.list_artifacts("other")
    with pytest.raises(ArtifactGatewayError):
        gateway.list_artifacts(limit=201)
    with pytest.raises(ArtifactGatewayError):
        gateway.list_artifacts(cursor="invalid")


@pytest.mark.asyncio
async def test_delete_artifact_removes_generated_only(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    upload_data = b"name,value\nup,1\n"
    generated_data = b"name,value\ngen,1\n"
    upload = entry(
        "input.csv", upload_data, "text/csv", ArtifactSource.UPLOAD, "upload"
    )
    generated = entry(
        "out.csv",
        generated_data,
        "text/csv",
        ArtifactSource.GENERATED,
        "generated-key",
    )
    storage = Storage({"upload": upload_data, "generated-key": generated_data})
    gateway = ChatArtifactGateway([upload, generated], output, storage=storage)

    with pytest.raises(ArtifactGatewayError, match="Only generated"):
        await asyncio.to_thread(gateway.delete_artifact, "input.csv")
    assert "upload" in storage.objects

    result = await asyncio.to_thread(gateway.delete_artifact, "out.csv")
    assert result == {
        "deleted": True,
        "ref": generated.ref,
        "filename": "out.csv",
    }
    assert storage.deleted == ["generated-key"]
    assert "generated-key" not in storage.objects
    assert gateway.list_artifacts("generated")["filenames"] == []
    assert gateway.list_artifacts("upload")["filenames"] == ["input.csv"]


@pytest.mark.asyncio
async def test_delete_artifact_removes_local_saved_file(tmp_path: Path) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    gateway = ChatArtifactGateway([], output, storage=Storage({}))
    saved = await asyncio.to_thread(
        gateway.save_artifact, "scratch.json", {"ok": True}
    )
    local = output / "scratch.json"
    assert local.exists()

    deleted = await asyncio.to_thread(gateway.delete_artifact, saved["filename"])
    assert deleted["deleted"] is True
    assert not local.exists()
    assert gateway.list_artifacts("generated")["filenames"] == []
    with pytest.raises(ArtifactGatewayError, match="current chat"):
        await asyncio.to_thread(gateway.delete_artifact, "scratch.json")
