from io import BytesIO

from openpyxl import Workbook
from pypdf import PdfWriter

from app.routers.artifacts import _table_preview, _text_preview
from app.services.file_validation import PDF_MEDIA_TYPE, XLSX_MEDIA_TYPE


def test_table_preview_is_bounded_and_json_safe() -> None:
    csv = "value,date\n" + "\n".join(
        f"{index},2026-01-{(index % 28) + 1:02d}" for index in range(101)
    )
    preview = _table_preview(csv.encode(), "text/csv")
    assert preview["kind"] == "table"
    assert len(preview["rows"]) == 100
    assert preview["truncated"] is True


def test_xlsx_preview_reports_sheet_names() -> None:
    workbook = Workbook()
    workbook.active.title = "Summary"
    workbook.active.append(["value"])
    workbook.active.append([42])
    workbook.create_sheet("Details")
    output = BytesIO()
    workbook.save(output)
    workbook.close()

    preview = _table_preview(output.getvalue(), XLSX_MEDIA_TYPE)
    assert preview["sheet_names"] == ["Summary", "Details"]
    assert preview["selected_sheet"] == "Summary"


def test_pdf_preview_extracts_safe_metadata_without_embedding_bytes() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": "Safe report"})
    output = BytesIO()
    writer.write(output)

    preview = _text_preview(output.getvalue(), PDF_MEDIA_TYPE)
    assert preview["kind"] == "text"
    assert preview["metadata"]["pages"] == 1
    assert preview["metadata"]["title"] == "Safe report"
    assert "%PDF" not in preview["text"]
