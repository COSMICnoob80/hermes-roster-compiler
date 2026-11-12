"""Denylist, overwrite and missing-folder safety checks for the three tools."""

import json
from pathlib import Path

import pytest

import roster_compiler as rc

DEMO = Path(__file__).resolve().parents[1] / "demo"

HEADER = "date,shift,role,person\n"


def make_roster(tmp_path, name="roster.csv"):
    path = tmp_path / name
    path.write_text(
        HEADER + "2026-11-04,evening,SHO,Dr. Priya Nadar\n", encoding="utf-8"
    )
    return path


def test_denied_read_returns_error_not_content(tmp_path, monkeypatch):
    file_safety = pytest.importorskip("agent.file_safety")
    source = make_roster(tmp_path)
    message = f"Access denied: {source} is a protected file"

    def deny(path):
        return message if Path(path).resolve() == source.resolve() else None

    monkeypatch.setattr(file_safety, "get_read_block_error", deny)

    for tool in (rc.roster_read, rc.roster_audit):
        payload = json.loads(tool({"path": str(source)}))
        assert payload["ok"] is False
        assert payload["error"] == message
        assert "entries" not in payload and "findings" not in payload

    payload = json.loads(
        rc.roster_export({"path": str(source), "out_path": str(tmp_path / "out.csv")})
    )
    assert payload["ok"] is False
    assert payload["error"] == message
    assert not (tmp_path / "out.csv").exists()


def test_denied_write_returns_error(tmp_path, monkeypatch):
    file_safety = pytest.importorskip("agent.file_safety")
    source = make_roster(tmp_path)
    out = tmp_path / "clean.csv"
    message = f"Write denied: '{out}' is a protected system/credential file"

    def deny(path):
        return message if Path(path).resolve() == out.resolve() else None

    monkeypatch.setattr(file_safety, "get_write_denied_error", deny)

    payload = json.loads(
        rc.roster_export({"path": str(source), "out_path": str(out)})
    )
    assert payload["ok"] is False
    assert payload["error"] == message
    assert not out.exists() and not out.with_suffix(".html").exists()


def test_export_refuses_to_overwrite_without_permission(tmp_path):
    source = make_roster(tmp_path)
    out = tmp_path / "clean.csv"
    out.write_text("old\n", encoding="utf-8")

    payload = json.loads(
        rc.roster_export({"path": str(source), "out_path": str(out)})
    )
    assert payload["ok"] is False
    assert payload["error"] == (
        f"refusing to overwrite {out.resolve()}: pass overwrite: true if you mean it"
    )
    assert out.read_text(encoding="utf-8") == "old\n"

    payload = json.loads(
        rc.roster_export(
            {"path": str(source), "out_path": str(out), "overwrite": True}
        )
    )
    assert payload["ok"] is True
    assert out.read_text(encoding="utf-8").splitlines()[0] == (
        "date,day,shift,role,person,status"
    )


def test_export_refuses_missing_parent_folder(tmp_path):
    source = make_roster(tmp_path)
    out = tmp_path / "missing" / "clean.csv"

    payload = json.loads(
        rc.roster_export({"path": str(source), "out_path": str(out)})
    )
    assert payload["ok"] is False
    assert "does not exist" in payload["error"]
    assert str(out.parent) in payload["error"]
    assert not out.parent.exists()


def test_export_refuses_hidden_output_file(tmp_path):
    source = make_roster(tmp_path)
    out = tmp_path / ".env"

    payload = json.loads(
        rc.roster_export(
            {"path": str(source), "out_path": str(out), "overwrite": True}
        )
    )

    assert payload["ok"] is False
    assert payload["error"] == f"refusing to write a hidden file: {out}.csv"
    assert sorted(p.name for p in tmp_path.iterdir()) == [source.name]


@pytest.mark.parametrize(
    "name, dependency",
    [
        ("ward3b-november.csv", None),
        ("ward3b-november.xlsx", "openpyxl"),
        ("ward3b-november.pdf", "pdfplumber"),
    ],
)
def test_demo_formats_still_yield_three_findings(name, dependency):
    if dependency is not None:
        pytest.importorskip(dependency)

    payload = json.loads(rc.roster_audit({"path": str(DEMO / name)}))

    assert payload["ok"] is True
    assert payload["entry_count"] == 91
    assert payload["finding_count"] == 3
    assert payload["summary"] == {
        "uncovered_shift": 1,
        "double_booking": 1,
        "consecutive_days": 1,
        "no_rest_after_night": 0,
        "parse_warning": 0,
    }
