"""W4: a file nothing can be read from must never report a clean roster."""

import json

import pytest

import roster_compiler as rc

HEADER = "date,shift,person\n"

IMAGE_ERROR = (
    "this looks like an image, not a roster: photos are not read. "
    "Ask for a PDF with a text layer or a spreadsheet."
)
XLS_ERROR = "this is the old .xls format: save as .xlsx (Excel 2007+) and try again"
SCAN_ERROR = (
    "this PDF has no text layer (it is a scan): it was not read. "
    "Export it as a spreadsheet or a text PDF."
)


def audit(path):
    return json.loads(rc.roster_audit({"path": str(path)}))


def scanned_pdf(path):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << >> >>",
    ]
    data = b"%PDF-1.4\n"
    offsets = []
    for index, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n".encode()
    data += b"0000000000 65535 f \n"
    for offset in offsets:
        data += f"{offset:010d} 00000 n \n".encode()
    data += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    path.write_bytes(data)


def test_empty_file_is_an_error_not_a_clean_roster(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")

    payload = audit(path)

    assert payload["ok"] is False
    assert (
        f"no roster rows found in {path}: "
        "expected a header row naming date, shift and person" == payload["error"]
    )


def test_header_only_file_warns_instead_of_going_clean(tmp_path):
    path = tmp_path / "header-only.csv"
    path.write_text("# month: 2026-11\n" + HEADER, encoding="utf-8")

    payload = audit(path)

    assert payload["ok"] is True
    assert payload["entry_count"] == 0
    assert payload["finding_count"] >= 1
    warnings = [item for item in payload["findings"] if item["type"] == "parse_warning"]
    assert len(warnings) == 1
    assert "header found but no shifts listed for 2026-11" in warnings[0]["message"]


@pytest.mark.parametrize(
    "name, body",
    [
        ("empty.csv", b""),
        ("header-only.csv", ("# month: 2026-11\n" + HEADER).encode()),
    ],
)
def test_no_entries_can_never_look_clean(tmp_path, name, body):
    path = tmp_path / name
    path.write_bytes(body)

    payload = audit(path)

    assert not (payload["ok"] is True and payload["finding_count"] == 0)


@pytest.mark.parametrize("name", ["photo.jpg", "photo.png", "photo.gif"])
def test_image_is_refused_as_a_photo(tmp_path, name):
    magic = {
        ".jpg": b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01",
        ".png": b"\x89PNG\r\n\x1a\n",
        ".gif": b"GIF89a",
    }[path_suffix(name)]
    path = tmp_path / name
    path.write_bytes(magic + b"\x00" * 32)

    payload = audit(path)

    assert payload["ok"] is False
    assert payload["error"] == IMAGE_ERROR


def test_legacy_xls_is_refused_with_a_save_as_hint(tmp_path):
    path = tmp_path / "old.xls"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 32)

    payload = audit(path)

    assert payload["ok"] is False
    assert payload["error"] == XLS_ERROR


def test_scanned_pdf_without_a_text_layer_is_refused(tmp_path):
    pytest.importorskip("pdfplumber")
    path = tmp_path / "scan.pdf"
    scanned_pdf(path)

    payload = audit(path)

    assert payload["ok"] is False
    assert payload["error"] == SCAN_ERROR


def path_suffix(name):
    return "." + name.rsplit(".", 1)[-1]
