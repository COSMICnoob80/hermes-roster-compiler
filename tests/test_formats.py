"""Format tests: .xlsx, .pdf and the messy handwritten text fixture."""

import json
import sys
from pathlib import Path

import pytest

import roster_compiler as rc

DEMO = Path(__file__).resolve().parents[1] / "demo"
CSV = DEMO / "ward3b-november.csv"
XLSX = DEMO / "ward3b-november.xlsx"
PDF = DEMO / "ward3b-november.pdf"
HANDWRITTEN = DEMO / "ward3b-handwritten.txt"

EXPECTED_SUMMARY = {
    "uncovered_shift": 1,
    "double_booking": 1,
    "consecutive_days": 1,
    "no_rest_after_night": 0,
    "parse_warning": 0,
}


def test_xlsx_matches_the_csv_entry_for_entry():
    pytest.importorskip("openpyxl")

    roster, findings = rc.audit_roster(XLSX)
    csv_roster, _ = rc.audit_roster(CSV)

    assert roster["format"] == "xlsx"
    assert roster["ward"] == "3B, General Hospital"
    assert roster["month"] == "2026-11"
    assert len(roster["entries"]) == 91
    assert roster["entries"] == csv_roster["entries"]
    assert rc.summarize(findings) == EXPECTED_SUMMARY


def test_pdf_matches_the_csv_entry_for_entry():
    pytest.importorskip("pdfplumber")

    roster, findings = rc.audit_roster(PDF)
    csv_roster, _ = rc.audit_roster(CSV)

    assert roster["format"] == "pdf"
    assert roster["ward"] == "3B, General Hospital"
    assert roster["month"] == "2026-11"
    assert len(roster["entries"]) == 91
    assert roster["entries"] == csv_roster["entries"]
    assert rc.summarize(findings) == EXPECTED_SUMMARY


def test_handwritten_rows_surface_as_parse_warnings_not_guesses():
    roster = rc.read_roster(HANDWRITTEN)
    findings = rc.audit_roster_data(roster)

    assert roster["format"] == "text"
    assert roster["ward"] == "3B, General Hospital"
    assert roster["month"] == "2026-11"
    assert len(roster["entries"]) == 16

    warnings = [item for item in findings if item["type"] == "parse_warning"]
    assert len(warnings) == 2
    assert {warning["line"] for warning in warnings} == {21, 22}
    assert any("unknown shift" in warning["message"] for warning in warnings)
    assert any("unreadable date" in warning["message"] for warning in warnings)

    dates = {entry["date"] for entry in roster["entries"]}
    assert {"2026-11-01", "2026-11-02", "2026-11-05"} <= dates
    assert "2026-11-14" not in dates
    assert "2026-11-30" not in dates


def test_missing_library_returns_an_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)

    payload = json.loads(rc.roster_read({"path": str(XLSX)}))

    assert payload["ok"] is False
    assert "openpyxl" in payload["error"]
    assert "pip install" in payload["error"]


def test_xlsx_ignores_padded_empty_columns(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["date", "shift", "role", "person"])
    sheet.append(["2026-11-04", "evening", "SHO", None])
    sheet["F1"] = "notes"
    path = tmp_path / "padded.xlsx"
    workbook.save(path)

    roster, findings = rc.audit_roster(path)

    assert len(roster["entries"]) == 1
    summary = rc.summarize(findings)
    assert summary["uncovered_shift"] == 1
    assert summary["parse_warning"] == 0
