import json
from datetime import date
from pathlib import Path

import pytest

import roster_compiler as rc

DEMO = Path(__file__).resolve().parents[1] / "demo" / "ward3b-november.csv"

HEADER = "date,shift,role,person\n"
CLEAN = {"uncovered_shift": 0, "double_booking": 0, "consecutive_days": 0,
         "no_rest_after_night": 0, "parse_warning": 0}


def write(tmp_path, text, name="roster.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def findings_for(tmp_path, text, name="roster.csv"):
    roster = rc.read_roster(write(tmp_path, text, name))
    return roster, rc.audit_roster_data(roster)


def test_reads_csv_metadata_and_entries(tmp_path):
    roster, _ = findings_for(
        tmp_path,
        "# ward: 3B, General Hospital\n# month: 2026-11\n"
        + HEADER
        + "2026-11-01,morning,SHO,Dr. Zara Whitfield\n"
        + "2026-11-01,evening,Registrar,  Dr. Omar   Haddad \n",
    )
    assert roster["format"] == "csv"
    assert roster["ward"] == "3B, General Hospital"
    assert roster["month"] == "2026-11"
    assert len(roster["entries"]) == 2
    assert roster["entries"][0] == {
        "date": "2026-11-01",
        "shift": "morning",
        "role": "SHO",
        "person": "Dr. Zara Whitfield",
    }
    assert roster["entries"][1]["person"] == "Dr. Omar Haddad"


def test_reads_whitespace_aligned_text(tmp_path):
    text = (
        "ward: 3B, General Hospital\n"
        "month: November 2026\n"
        "DATE         SHIFT     ROLE        PERSON\n"
        "2026-11-01   morning   SHO         Dr. Zara Whitfield\n"
        "2026-11-01   night     Registrar   Dr. Omar Haddad\n"
    )
    roster = rc.read_roster(write(tmp_path, text, "roster.txt"))
    assert roster["format"] == "text"
    assert roster["month"] == "2026-11"
    assert [entry["shift"] for entry in roster["entries"]] == ["morning", "night"]
    assert roster["entries"][1]["person"] == "Dr. Omar Haddad"


def test_malformed_rows_become_parse_warnings(tmp_path):
    text = (
        HEADER
        + "2026-11-01,morning,SHO,Dr. Zara Whitfield\n"
        + "2026-11-02,late,SHO,Dr. Omar Haddad\n"
        + "2026-11-03,morning\n"
        + "2026-11-04,morning,SHO,Dr. Priya Nadar\n"
    )
    roster, findings = findings_for(tmp_path, text)

    assert [entry["date"] for entry in roster["entries"]] == ["2026-11-01", "2026-11-04"]
    warnings = [finding for finding in findings if finding["type"] == "parse_warning"]
    assert len(warnings) == 2
    assert {warning["line"] for warning in warnings} == {3, 4}
    assert any("unknown shift" in warning["message"] for warning in warnings)
    assert all(warning["severity"] == "medium" for warning in warnings)


def test_weekday_column_mismatch_is_reported(tmp_path):
    wrong = "Mon" if date(2026, 11, 1).strftime("%a") != "Mon" else "Tue"
    text = (
        "date,day,shift,role,person\n"
        + f"2026-11-01,{wrong},morning,SHO,Dr. Zara Whitfield\n"
    )
    roster, findings = findings_for(tmp_path, text)
    assert roster["entries"] == []
    assert len(findings) == 1
    assert findings[0]["type"] == "parse_warning"
    assert "weekday" in findings[0]["message"]


def test_uncovered_shift_is_reported(tmp_path):
    text = HEADER + "2026-11-04,evening,SHO,\n2026-11-04,evening,SHO,-\n"
    roster, findings = findings_for(tmp_path, text)
    assert len(roster["entries"]) == 2
    assert all(entry["person"] is None for entry in roster["entries"])
    uncovered = [finding for finding in findings if finding["type"] == "uncovered_shift"]
    assert len(uncovered) == 2
    assert uncovered[0]["date"] == "2026-11-04"
    assert uncovered[0]["shift"] == "evening"
    assert uncovered[0]["severity"] == "high"


def test_double_booking_is_reported(tmp_path):
    text = (
        HEADER
        + "2026-11-03,morning,SHO,Dr. Ines Duarte\n"
        + "2026-11-03,morning,Registrar,Dr. Ines Duarte\n"
        + "2026-11-03,night,SHO,Dr. Ines Duarte\n"
    )
    _, findings = findings_for(tmp_path, text)
    double = [finding for finding in findings if finding["type"] == "double_booking"]
    assert len(double) == 1
    assert double[0]["date"] == "2026-11-03"
    assert double[0]["shift"] == "morning"
    assert double[0]["roles"] == ["Registrar", "SHO"]
    assert double[0]["count"] == 2


def test_seven_consecutive_days_flagged_six_not(tmp_path):
    seven = HEADER + "".join(
        f"2026-11-{day:02d},morning,SHO,Dr. Lina Farouk\n" for day in range(1, 8)
    )
    _, findings = findings_for(tmp_path, seven, "seven.csv")
    runs = [finding for finding in findings if finding["type"] == "consecutive_days"]
    assert len(runs) == 1
    assert runs[0]["days"] == 7

    six = HEADER + "".join(
        f"2026-11-{day:02d},morning,SHO,Dr. Lina Farouk\n" for day in range(1, 7)
    )
    _, findings = findings_for(tmp_path, six, "six.csv")
    assert rc.summarize(findings) == CLEAN


def test_night_then_day_is_a_rest_violation_but_night_then_night_is_not(tmp_path):
    violation = (
        HEADER
        + "2026-11-01,night,SHO,Dr. Kwame Asante\n"
        + "2026-11-02,morning,SHO,Dr. Kwame Asante\n"
    )
    _, findings = findings_for(tmp_path, violation, "violation.csv")
    rest = [finding for finding in findings if finding["type"] == "no_rest_after_night"]
    assert len(rest) == 1
    assert rest[0]["next_shift"] == "morning"
    assert rest[0]["next_date"] == "2026-11-02"

    repeat = (
        HEADER
        + "2026-11-01,night,SHO,Dr. Kwame Asante\n"
        + "2026-11-02,night,SHO,Dr. Kwame Asante\n"
    )
    _, findings = findings_for(tmp_path, repeat, "repeat.csv")
    assert rc.summarize(findings) == CLEAN


def test_clean_roster_has_no_findings(tmp_path):
    crew = {
        "morning": "Dr. Tomas Reyes",
        "evening": "Dr. Priya Nadar",
        "night": "Dr. Lina Farouk",
    }
    text = HEADER + "".join(
        f"2026-11-{day:02d},{shift},SHO,{crew[shift]}\n"
        for day in (1, 2, 3)
        for shift in ("morning", "evening", "night")
    )
    _, findings = findings_for(tmp_path, text)
    assert findings == []
    assert rc.summarize(findings) == CLEAN


def test_export_writes_csv_and_html_without_touching_input(tmp_path):
    source = write(
        tmp_path,
        HEADER
        + "2026-11-04,evening,SHO,\n"
        + "2026-11-05,morning,SHO,Dr. Priya Nadar\n",
    )
    before = source.read_bytes()
    out = tmp_path / "out" / "schedule.csv"

    result = rc.export_roster(source, out)

    assert source.read_bytes() == before
    csv_path = Path(result["csv"])
    html_path = Path(result["html"])
    assert csv_path.exists() and html_path.exists()
    assert csv_path.name == "schedule.csv" and html_path.name == "schedule.html"

    rows = csv_path.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "date,day,shift,role,person,status"
    assert rows[1] == "2026-11-04,Wed,evening,SHO,,uncovered"

    report = html_path.read_text(encoding="utf-8")
    assert "<html" in report
    assert "UNCOVERED" in report
    assert "has no person assigned" in report
    assert result["summary"]["uncovered_shift"] == 1

    with pytest.raises(rc.RosterError):
        rc.export_roster(source, source)
    assert source.read_bytes() == before


def test_demo_roster_has_exactly_the_three_planted_defects():
    roster, findings = rc.audit_roster(DEMO)

    assert roster["ward"] == "3B, General Hospital"
    assert roster["month"] == "2026-11"
    assert len(roster["entries"]) == 91
    assert len({entry["person"] for entry in roster["entries"] if entry["person"]}) == 8
    assert rc.summarize(findings) == {
        "uncovered_shift": 1,
        "double_booking": 1,
        "consecutive_days": 1,
        "no_rest_after_night": 0,
        "parse_warning": 0,
    }
    runs = [finding for finding in findings if finding["type"] == "consecutive_days"]
    assert runs[0]["days"] == 8
    assert {finding["type"] for finding in findings} == {
        "uncovered_shift",
        "double_booking",
        "consecutive_days",
    }


def test_tool_handlers_return_json_strings(tmp_path):
    source = write(tmp_path, HEADER + "2026-11-04,evening,SHO,\n")

    payload = json.loads(rc.roster_read({"path": str(source)}))
    assert payload["ok"] is True
    assert payload["entry_count"] == 1
    assert payload["entries"][0]["status"] == "uncovered"
    assert payload["uncovered_count"] == 1

    payload = json.loads(rc.roster_audit({"path": str(source)}))
    assert payload["ok"] is True
    assert payload["finding_count"] == 1
    assert payload["summary"]["uncovered_shift"] == 1

    payload = json.loads(rc.roster_export({"path": str(source), "out_path": str(tmp_path / "clean")}))
    assert payload["ok"] is True
    assert Path(payload["csv"]).name == "clean.csv"

    missing = json.loads(rc.roster_read({"path": str(tmp_path / "nope.csv")}))
    assert missing["ok"] is False
    assert "not found" in missing["error"]

    empty = json.loads(rc.roster_read({}))
    assert empty["ok"] is False
