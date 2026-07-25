"""PR 2 contracts for bounded CSV, XLSX, and PNG validation."""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest
from openpyxl import Workbook
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from starlette.datastructures import UploadFile

from app.services import file_validation
from app.services.file_validation import FileValidationError


def _upload(filename: str, data: bytes, content_type: str | None = None) -> UploadFile:
    return UploadFile(
        file=BytesIO(data),
        filename=filename,
        headers={"content-type": content_type} if content_type else None,
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


def _xlsx_with_entry(name: str, data: bytes) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(_xlsx_bytes())) as source:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for entry in source.infolist():
                target.writestr(entry, source.read(entry.filename))
            target.writestr(name, data)
    return output.getvalue()


class _RecordingUpload:
    """UploadFile-shaped stream that deliberately returns partial chunks."""

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._stream = BytesIO(data)
        self.requested_sizes: list[int] = []
        self.returned_sizes: list[int] = []
        self.closed = False

    async def read(self, size: int) -> bytes:
        self.requested_sizes.append(size)
        chunk = self._stream.read(min(size, 3))
        self.returned_sizes.append(len(chunk))
        return chunk

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_upload_stops_after_reading_limit_plus_one_byte(monkeypatch) -> None:
    monkeypatch.setattr(file_validation, "MAX_UPLOAD_BYTES", 8)
    monkeypatch.setattr(file_validation, "UPLOAD_CHUNK_BYTES", 4)
    upload = _RecordingUpload("oversize.csv", b"123456789more-data")

    with pytest.raises(FileValidationError) as error:
        await file_validation.validate_upload(upload)  # type: ignore[arg-type]

    assert error.value.code == "upload_too_large"
    assert error.value.status_code == 413
    assert upload.requested_sizes == [4, 4, 3]
    assert all(0 < size <= 4 for size in upload.requested_sizes)
    assert sum(upload.returned_sizes) == file_validation.MAX_UPLOAD_BYTES + 1
    assert upload.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [b"name,amount\nAda,42\n", b"\xef\xbb\xbfname,amount\nAda,42\n"],
)
async def test_csv_accepts_utf8_and_utf8_bom(data: bytes) -> None:
    validated = await file_validation.validate_upload(
        _upload("report.csv", data, "application/octet-stream")
    )
    try:
        assert validated.content_type == file_validation.CSV_MEDIA_TYPE
        assert validated.size == len(data)
        assert validated.sha256 == hashlib.sha256(data).hexdigest()
        assert validated.stream.read() == data
    finally:
        validated.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        b"name,value\nAda,\x00binary\n",
        b"name,value\nAda,\x01\n",
        b"name,value\nAda,\xff\n",
    ],
)
async def test_csv_rejects_nul_and_non_utf8_bytes(data: bytes) -> None:
    with pytest.raises(FileValidationError) as error:
        await file_validation.validate_upload(_upload("report.csv", data))

    assert error.value.code == "invalid_csv"
    assert error.value.status_code == 415


@pytest.mark.asyncio
async def test_xlsx_accepts_a_valid_read_only_workbook() -> None:
    data = _xlsx_bytes()

    validated = await file_validation.validate_upload(
        _upload("report.xlsx", data, "text/plain")
    )
    try:
        assert validated.content_type == file_validation.XLSX_MEDIA_TYPE
        assert validated.size == len(data)
        assert validated.sha256 == hashlib.sha256(data).hexdigest()
    finally:
        validated.close()


@pytest.mark.asyncio
async def test_xlsx_rejects_traversal_entry() -> None:
    data = _xlsx_with_entry("../escaped.txt", b"host data")

    with pytest.raises(FileValidationError) as error:
        await file_validation.validate_upload(_upload("report.xlsx", data))

    assert error.value.code == "unsafe_xlsx"
    assert "path" in error.value.message.lower()


@pytest.mark.asyncio
async def test_xlsx_rejects_windows_drive_entry() -> None:
    data = _xlsx_with_entry("C:/escaped.txt", b"host data")

    with pytest.raises(FileValidationError) as error:
        await file_validation.validate_upload(_upload("report.xlsx", data))

    assert error.value.code == "unsafe_xlsx"


@pytest.mark.asyncio
async def test_xlsx_rejects_embedded_vba_project() -> None:
    data = _xlsx_with_entry("xl/vbaProject.bin", b"macro")

    with pytest.raises(FileValidationError) as error:
        await file_validation.validate_upload(_upload("report.xlsx", data))

    assert error.value.code == "unsafe_xlsx"
    assert "macro" in error.value.message.lower()


@pytest.mark.asyncio
async def test_xlsx_rejects_high_compression_ratio() -> None:
    data = _xlsx_with_entry("xl/repeated.bin", b"A" * 100_000)

    with pytest.raises(FileValidationError) as error:
        await file_validation.validate_upload(_upload("report.xlsx", data))

    assert error.value.code == "unsafe_xlsx"
    assert "compression" in error.value.message.lower()


def test_png_is_verified_reencoded_and_metadata_is_removed() -> None:
    source = BytesIO()
    metadata = PngInfo()
    metadata.add_text("unsafe-note", "not retained")
    Image.new("RGBA", (3, 2), (10, 20, 30, 255)).save(
        source, format="PNG", pnginfo=metadata
    )

    validated = file_validation.validate_and_reencode_png(source.getvalue())

    assert (validated.width, validated.height) == (3, 2)
    assert validated.size == len(validated.data)
    assert validated.sha256 == hashlib.sha256(validated.data).hexdigest()
    with Image.open(BytesIO(validated.data)) as normalized:
        assert normalized.format == "PNG"
        assert "unsafe-note" not in normalized.info


@pytest.mark.parametrize("data", [b"<svg></svg>", b"\x89PNG\r\n\x1a\ncorrupt"])
def test_png_rejects_active_or_corrupt_content(data: bytes) -> None:
    with pytest.raises(FileValidationError) as error:
        file_validation.validate_and_reencode_png(data)

    assert error.value.code == "invalid_png"


def test_png_rejects_dimensions_above_pixel_limit(monkeypatch) -> None:
    source = BytesIO()
    Image.new("RGB", (2, 2)).save(source, format="PNG")
    monkeypatch.setattr(file_validation, "MAX_PNG_PIXELS", 3)

    with pytest.raises(FileValidationError) as error:
        file_validation.validate_and_reencode_png(source.getvalue())

    assert error.value.code == "unsafe_png"
