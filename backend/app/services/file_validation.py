"""Bounded, content-based validation for uploaded and generated artifacts."""

from __future__ import annotations

import codecs
import hashlib
import json
import re
import stat
import unicodedata
import warnings
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath, PureWindowsPath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO

from fastapi import UploadFile
from openpyxl import load_workbook
from PIL import Image
from pypdf import PdfReader

from app.core.config import settings

MIB = 1024 * 1024
MAX_UPLOAD_BYTES = int(getattr(settings, "max_upload_bytes", 50 * MIB))
UPLOAD_SPOOL_BYTES = int(getattr(settings, "upload_spool_bytes", 8 * MIB))
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_XLSX_ENTRIES = int(getattr(settings, "max_xlsx_entries", 10_000))
MAX_XLSX_EXPANDED_BYTES = int(
    getattr(settings, "max_xlsx_expanded_bytes", 500 * MIB)
)
MAX_XLSX_COMPRESSION_RATIO = int(
    getattr(settings, "max_xlsx_compression_ratio", 100)
)
MAX_PNG_PIXELS = int(getattr(settings, "max_png_pixels", 40_000_000))
MAX_GENERATED_FILE_BYTES = int(
    getattr(settings, "max_generated_file_bytes", 50 * MIB)
)

CSV_MEDIA_TYPE = "text/csv"
XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
PNG_MEDIA_TYPE = "image/png"
JPEG_MEDIA_TYPE = "image/jpeg"
WEBP_MEDIA_TYPE = "image/webp"
JSON_MEDIA_TYPE = "application/json"
TEXT_MEDIA_TYPE = "text/plain"
PDF_MEDIA_TYPE = "application/pdf"

GENERATED_MEDIA_TYPES = {
    ".csv": CSV_MEDIA_TYPE,
    ".xlsx": XLSX_MEDIA_TYPE,
    ".png": PNG_MEDIA_TYPE,
    ".jpg": JPEG_MEDIA_TYPE,
    ".jpeg": JPEG_MEDIA_TYPE,
    ".webp": WEBP_MEDIA_TYPE,
    ".json": JSON_MEDIA_TYPE,
    ".txt": TEXT_MEDIA_TYPE,
    ".pdf": PDF_MEDIA_TYPE,
}


class FileValidationError(ValueError):
    """A safe validation failure suitable for returning to a client."""

    def __init__(self, code: str, message: str, status_code: int = 415) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class ValidatedUpload:
    filename: str
    content_type: str
    stream: BinaryIO
    size: int
    sha256: str

    def close(self) -> None:
        self.stream.close()


@dataclass(frozen=True, slots=True)
class ValidatedPng:
    data: bytes
    size: int
    sha256: str
    width: int
    height: int


ValidatedRaster = ValidatedPng


_UNSAFE_FILENAME = re.compile(r"[^\w .()\-]+", flags=re.UNICODE)


def sanitize_display_filename(filename: str | None, *, fallback: str = "upload") -> str:
    """Return a display-only name; object and filesystem paths must use UUIDs."""
    normalized = unicodedata.normalize("NFKC", filename or "")
    normalized = normalized.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    normalized = "".join(char for char in normalized if char.isprintable())
    normalized = _UNSAFE_FILENAME.sub("_", normalized).strip(" .")
    if not normalized or normalized in {".", ".."}:
        normalized = fallback
    if len(normalized) > 255:
        suffix = PurePosixPath(normalized).suffix[:20]
        normalized = normalized[: 255 - len(suffix)].rstrip(" .") + suffix
    return normalized


async def validate_upload(upload: UploadFile) -> ValidatedUpload:
    """Stream an UploadFile into a bounded spool and validate CSV/XLSX contents."""
    filename = sanitize_display_filename(upload.filename)
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise FileValidationError(
            "unsupported_upload_type", "Only CSV and XLSX files are accepted"
        )

    spool = SpooledTemporaryFile(max_size=UPLOAD_SPOOL_BYTES, mode="w+b")
    total = 0
    digest = hashlib.sha256()
    try:
        while total <= MAX_UPLOAD_BYTES:
            read_size = min(UPLOAD_CHUNK_BYTES, MAX_UPLOAD_BYTES + 1 - total)
            chunk = await upload.read(read_size)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise FileValidationError(
                    "upload_too_large",
                    f"Upload exceeds the {MAX_UPLOAD_BYTES}-byte limit",
                    status_code=413,
                )
            spool.write(chunk)
            digest.update(chunk)

        if total == 0:
            raise FileValidationError("empty_upload", "The uploaded file is empty", 400)

        spool.seek(0)
        if suffix == ".csv":
            _validate_csv(spool)
            content_type = CSV_MEDIA_TYPE
        else:
            _validate_xlsx(spool)
            content_type = XLSX_MEDIA_TYPE
        spool.seek(0)
        return ValidatedUpload(
            filename=filename,
            content_type=content_type,
            stream=spool,
            size=total,
            sha256=digest.hexdigest(),
        )
    except Exception:
        spool.close()
        raise
    finally:
        await upload.close()


def _validate_csv(stream: BinaryIO) -> None:
    decoder = codecs.getincrementaldecoder("utf-8-sig")("strict")
    forbidden_controls = 0
    try:
        while chunk := stream.read(UPLOAD_CHUNK_BYTES):
            if b"\x00" in chunk:
                raise FileValidationError(
                    "invalid_csv", "CSV files must not contain NUL or binary data"
                )
            text = decoder.decode(chunk)
            forbidden_controls += sum(
                ord(char) < 32 and char not in "\t\r\n" for char in text
            )
        tail = decoder.decode(b"", final=True)
        forbidden_controls += sum(
            ord(char) < 32 and char not in "\t\r\n" for char in tail
        )
    except UnicodeDecodeError as exc:
        raise FileValidationError(
            "invalid_csv", "CSV files must be UTF-8 or UTF-8 with BOM"
        ) from exc
    finally:
        stream.seek(0)

    if forbidden_controls:
        raise FileValidationError(
            "invalid_csv", "CSV files must not contain binary control data"
        )


def validate_csv_stream(stream: BinaryIO) -> None:
    """Validate generated CSV data without taking ownership of the stream."""
    _validate_csv(stream)


def _validate_xlsx(stream: BinaryIO) -> None:
    if stream.read(4) != b"PK\x03\x04":
        stream.seek(0)
        raise FileValidationError("invalid_xlsx", "XLSX ZIP signature is invalid")
    stream.seek(0)

    try:
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_XLSX_ENTRIES:
                raise FileValidationError(
                    "unsafe_xlsx", "XLSX contains too many ZIP entries"
                )

            names: set[str] = set()
            expanded_size = 0
            compressed_size = 0
            for entry in entries:
                _validate_zip_entry(entry)
                names.add(entry.filename)
                expanded_size += entry.file_size
                compressed_size += entry.compress_size
                if expanded_size > MAX_XLSX_EXPANDED_BYTES:
                    raise FileValidationError(
                        "unsafe_xlsx", "XLSX expanded content is too large"
                    )
                if entry.file_size and (
                    entry.compress_size == 0
                    or entry.file_size
                    > entry.compress_size * MAX_XLSX_COMPRESSION_RATIO
                ):
                    raise FileValidationError(
                        "unsafe_xlsx", "XLSX contains a suspicious compression ratio"
                    )

            required = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml"}
            if not required.issubset(names):
                raise FileValidationError(
                    "invalid_xlsx", "XLSX workbook entries are missing"
                )
            if expanded_size and (
                compressed_size == 0
                or expanded_size
                > compressed_size * MAX_XLSX_COMPRESSION_RATIO
            ):
                raise FileValidationError(
                    "unsafe_xlsx", "XLSX compression ratio exceeds the limit"
                )
            if any(name.lower().endswith("vbaproject.bin") for name in names):
                raise FileValidationError("unsafe_xlsx", "Macro-enabled XLSX is rejected")
            content_types = archive.read("[Content_Types].xml").lower()
            if b"macroenabled" in content_types or b"vba" in content_types:
                raise FileValidationError("unsafe_xlsx", "Macro-enabled XLSX is rejected")
    except zipfile.BadZipFile as exc:
        raise FileValidationError("invalid_xlsx", "XLSX ZIP data is invalid") from exc
    finally:
        stream.seek(0)
    try:
        workbook = load_workbook(
            stream,
            read_only=True,
            data_only=True,
            keep_links=False,
        )
        workbook.close()
    except Exception as exc:
        raise FileValidationError(
            "invalid_xlsx", "XLSX workbook could not be safely loaded"
        ) from exc
    finally:
        stream.seek(0)


def validate_xlsx_stream(stream: BinaryIO) -> None:
    """Validate a generated XLSX using the same policy as an uploaded workbook."""
    _validate_xlsx(stream)


def _validate_zip_entry(entry: zipfile.ZipInfo) -> None:
    name = entry.filename
    path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or bool(windows_path.drive)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise FileValidationError("unsafe_xlsx", "XLSX contains an unsafe ZIP path")
    unix_mode = entry.external_attr >> 16
    if stat.S_ISLNK(unix_mode):
        raise FileValidationError("unsafe_xlsx", "XLSX ZIP symlinks are rejected")
    if entry.flag_bits & 0x1:
        raise FileValidationError("unsafe_xlsx", "Encrypted XLSX entries are rejected")


def validate_and_reencode_png(data: bytes) -> ValidatedPng:
    """Verify PNG raster data, enforce pixel/size limits, and strip metadata."""
    if not data or len(data) > MAX_GENERATED_FILE_BYTES:
        raise FileValidationError(
            "generated_output_too_large",
            "Generated PNG exceeds the per-file output limit",
            status_code=413,
        )
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise FileValidationError("invalid_png", "Generated image is not PNG raster data")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                if probe.format != "PNG":
                    raise FileValidationError(
                        "invalid_png", "Generated image is not PNG raster data"
                    )
                width, height = probe.size
                if width <= 0 or height <= 0 or width * height > MAX_PNG_PIXELS:
                    raise FileValidationError(
                        "unsafe_png", "Generated PNG dimensions exceed the pixel limit"
                    )
                probe.verify()

            with Image.open(BytesIO(data)) as image:
                image.load()
                if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                    image = image.convert("RGBA")
                output = BytesIO()
                image.save(output, format="PNG", optimize=True)
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("invalid_png", "Generated PNG is corrupt") from exc

    normalized = output.getvalue()
    if len(normalized) > MAX_GENERATED_FILE_BYTES:
        raise FileValidationError(
            "generated_output_too_large",
            "Generated PNG exceeds the per-file output limit",
            status_code=413,
        )
    return ValidatedPng(
        data=normalized,
        size=len(normalized),
        sha256=hashlib.sha256(normalized).hexdigest(),
        width=width,
        height=height,
    )


def validate_and_reencode_raster(data: bytes, suffix: str) -> ValidatedRaster:
    """Decode and metadata-strip a supported raster format."""
    suffix = suffix.lower()
    if suffix == ".png":
        return validate_and_reencode_png(data)
    expected = {".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(suffix)
    if expected is None or not data or len(data) > MAX_GENERATED_FILE_BYTES:
        raise FileValidationError("invalid_image", "Unsupported generated image format")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                if probe.format != expected:
                    raise FileValidationError(
                        "invalid_image", "Generated image content does not match its extension"
                    )
                width, height = probe.size
                if width <= 0 or height <= 0 or width * height > MAX_PNG_PIXELS:
                    raise FileValidationError(
                        "unsafe_image", "Generated image dimensions exceed the pixel limit"
                    )
                probe.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
                output = BytesIO()
                if expected == "JPEG":
                    if image.mode not in {"L", "RGB"}:
                        image = image.convert("RGB")
                    image.save(output, format="JPEG", quality=90, optimize=True)
                else:
                    if image.mode not in {"RGB", "RGBA"}:
                        image = image.convert("RGBA")
                    image.save(output, format="WEBP", quality=90, method=6)
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("invalid_image", "Generated image is corrupt") from exc
    normalized = output.getvalue()
    if len(normalized) > MAX_GENERATED_FILE_BYTES:
        raise FileValidationError(
            "generated_output_too_large", "Generated image exceeds the per-file output limit", 413
        )
    return ValidatedRaster(
        data=normalized,
        size=len(normalized),
        sha256=hashlib.sha256(normalized).hexdigest(),
        width=width,
        height=height,
    )


def validate_utf8_text(data: bytes, *, json_document: bool = False) -> bytes:
    if not data or len(data) > MAX_GENERATED_FILE_BYTES or b"\x00" in data:
        raise FileValidationError("invalid_text", "Generated text is empty, oversized, or binary")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FileValidationError("invalid_text", "Generated text must be UTF-8") from exc
    if json_document:
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise FileValidationError("invalid_json", "Generated JSON is invalid") from exc
    return text.encode("utf-8")


_ACTIVE_PDF_NAMES = {
    "/JavaScript",
    "/JS",
    "/OpenAction",
    "/AA",
    "/Launch",
    "/EmbeddedFiles",
    "/RichMedia",
    "/XFA",
}


def validate_pdf(data: bytes) -> bytes:
    """Parse a PDF and reject encryption, embedded content, and active actions."""
    if not data or len(data) > MAX_GENERATED_FILE_BYTES or not data.startswith(b"%PDF-"):
        raise FileValidationError("invalid_pdf", "Generated PDF is invalid")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise FileValidationError("unsafe_pdf", "Encrypted PDFs are rejected")
        if len(reader.pages) > 1_000:
            raise FileValidationError("unsafe_pdf", "Generated PDF has too many pages")
        root = reader.trailer.get("/Root")
        serialized = repr(root)
        if any(name in serialized for name in _ACTIVE_PDF_NAMES):
            raise FileValidationError("unsafe_pdf", "Active or embedded PDF content is rejected")
        for page in reader.pages:
            page_text = repr(page.get_object())
            if any(name in page_text for name in _ACTIVE_PDF_NAMES):
                raise FileValidationError("unsafe_pdf", "Active PDF actions are rejected")
    except FileValidationError:
        raise
    except Exception as exc:
        raise FileValidationError("invalid_pdf", "Generated PDF could not be parsed") from exc
    return data
