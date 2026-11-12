"""Roster compiler: parse, audit and export hospital duty rosters.

Deterministic by design. No network, no model calls. CSV and plain text need
only the standard library; .xlsx and .pdf readers import their library lazily,
so registration and validation work without those packages installed. Every
finding is reproducible from the bytes of the input file.
"""

from __future__ import annotations

import calendar
import csv
import html
import io
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

MAX_CONSECUTIVE_DAYS = 6

SHIFT_ORDER = ("morning", "evening", "night")
DAY_SHIFTS = ("morning", "evening")

FINDING_TYPES = (
    "uncovered_shift",
    "double_booking",
    "consecutive_days",
    "no_rest_after_night",
    "parse_warning",
)

_SEVERITY = {
    "uncovered_shift": "high",
    "double_booking": "high",
    "no_rest_after_night": "high",
    "consecutive_days": "medium",
    "parse_warning": "medium",
}

_SHIFT_ALIASES = {
    "morning": "morning",
    "morn": "morning",
    "am": "morning",
    "a.m.": "morning",
    "m": "morning",
    "evening": "evening",
    "eve": "evening",
    "pm": "evening",
    "p.m.": "evening",
    "e": "evening",
    "night": "night",
    "noc": "night",
    "n": "night",
    "nights": "night",
}

_UNASSIGNED = {
    "",
    "-",
    "--",
    "---",
    "\u2013",
    "\u2014",
    "?",
    "??",
    "tbd",
    "tba",
    "vacant",
    "unassigned",
    "none",
    "n/a",
    "na",
}

_COLUMN_ALIASES = {
    "date": {"date", "duty date", "roster date"},
    "weekday": {"day", "weekday", "dow"},
    "shift": {"shift", "duty", "session"},
    "role": {"role", "post", "grade", "designation", "rank", "designation/post"},
    "person": {"person", "name", "doctor", "officer", "staff", "assigned", "assigned to"},
}

_META_KEYS = {"ward": "ward", "unit": "ward", "month": "month", "period": "month"}

_META_RE = re.compile(r"^([A-Za-z][A-Za-z /]{0,24}?)\s*:\s*(.+)$")

_HEADER_SPLIT_RE = re.compile(r"\s{2,}")

_DASH = "\u2014"

_MONTH_NAMES = {
    name.casefold(): index for index, name in enumerate(calendar.month_name) if name
}
_MONTH_NAMES.update(
    {name.casefold(): index for index, name in enumerate(calendar.month_abbr) if name}
)

_XLSX_SUFFIXES = {".xlsx", ".xlsm"}
_PDF_SUFFIXES = {".pdf"}

_INSTALL_LINES = {
    "openpyxl": "pip install 'openpyxl>=3.1'",
    "pdfplumber": "pip install 'pdfplumber>=0.11'",
}


class RosterError(Exception):
    """A roster could not be read at all (missing file, unreadable bytes)."""


def _clean(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def _normalize_person(raw):
    person = _clean(raw)
    return None if person.casefold() in _UNASSIGNED else person


def _person_key(person):
    return _clean(person).casefold()


def _normalize_shift(raw):
    return _SHIFT_ALIASES.get(_clean(raw).casefold())


def _parse_date(raw):
    text = _clean(raw)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_month(raw):
    text = _clean(raw)
    if not text:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None
    match = re.fullmatch(r"(\d{1,2})/(\d{4})", text)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None
    match = re.fullmatch(r"([A-Za-z]+)[\s,/-]+(\d{4})", text)
    if match:
        month = _MONTH_NAMES.get(match.group(1).casefold())
        if month:
            return f"{int(match.group(2)):04d}-{month:02d}"
        return None
    match = re.fullmatch(r"(\d{4})", text)
    if match:
        return match.group(1)
    return None


def _metadata(line):
    match = _META_RE.match(line)
    if not match:
        return None
    key = _clean(match.group(1)).casefold()
    logical = _META_KEYS.get(key)
    if logical is None:
        return None
    return logical, _clean(match.group(2))


def _parse_warning(line, message):
    return {
        "type": "parse_warning",
        "severity": _SEVERITY["parse_warning"],
        "date": None,
        "shift": None,
        "role": "",
        "people": [],
        "line": line or None,
        "message": f"line {line}: {message}" if line else message,
    }


def _extract_entry(fields, line, warnings):
    date_raw = fields.get("date", "")
    shift_raw = fields.get("shift", "")
    person_raw = fields.get("person", "")
    role_raw = fields.get("role", "")
    weekday_raw = fields.get("weekday", "")

    problems = []
    day = _parse_date(date_raw)
    if day is None:
        problems.append(f"unreadable date {date_raw!r}")
    shift = _normalize_shift(shift_raw)
    if shift is None:
        problems.append(
            f"unknown shift {shift_raw!r} (expected morning, evening or night)"
        )
    if day is not None and weekday_raw:
        declared = _clean(weekday_raw).casefold()
        actual = day.strftime("%a").casefold()
        if len(declared) >= 3 and not actual.startswith(declared[:3]):
            problems.append(
                f"weekday {weekday_raw!r} does not match {day.isoformat()} ({day.strftime('%A')})"
            )

    if problems:
        warnings.append(_parse_warning(line, "; ".join(problems)))
        return None

    return {
        "date": day.isoformat(),
        "shift": shift,
        "role": _clean(role_raw),
        "person": _normalize_person(person_raw),
    }


def _columns_from_tokens(tokens):
    mapping = {}
    for index, token in enumerate(tokens):
        key = re.sub(r"[^a-z /]", "", token.casefold()).strip()
        for logical, aliases in _COLUMN_ALIASES.items():
            if key in aliases and logical not in mapping:
                mapping[logical] = index
                break
    if "date" not in mapping and "weekday" in mapping:
        mapping["date"] = mapping.pop("weekday")
    if "date" not in mapping or "shift" not in mapping or "person" not in mapping:
        return None
    return mapping


def _header_columns(line):
    tokens = [token for token in _HEADER_SPLIT_RE.split(line.strip()) if token]
    if len(tokens) < 3:
        tokens = [token for token in line.split() if token]
    return _columns_from_tokens(tokens)


def _split_text_row(line):
    expanded = line.replace("\t", "    ").rstrip()
    pieces = [piece.strip() for piece in _HEADER_SPLIT_RE.split(expanded) if piece.strip()]
    if len(pieces) > 1:
        return pieces
    return [token for token in expanded.split() if token]


def _parse_csv_rows(rows, warnings):
    entries = []
    columns = None
    for line, text in rows:
        try:
            cells = next(csv.reader([text]))
        except csv.Error as exc:
            warnings.append(_parse_warning(line, f"unreadable CSV row ({exc})"))
            continue
        cells = [cell.strip() for cell in cells]
        if not any(cells):
            continue

        if columns is None:
            mapping = _columns_from_tokens(cells)
            if mapping is not None:
                columns = mapping
                continue
            warnings.append(
                _parse_warning(
                    line,
                    "expected a header row naming date, shift and person columns; got "
                    + repr(cells),
                )
            )
            continue

        width = max(columns.values()) + 1
        if len(cells) < width:
            warnings.append(
                _parse_warning(
                    line,
                    f"row has {len(cells)} field(s), header needs at least {width}",
                )
            )
            continue
        if len(cells) > width:
            warnings.append(
                _parse_warning(
                    line,
                    f"row has {len(cells)} field(s), expected {width}; "
                    "check for an unquoted comma",
                )
            )
            continue

        fields = {logical: cells[index] for logical, index in columns.items()}
        entry = _extract_entry(fields, line, warnings)
        if entry is not None:
            entries.append(entry)

    if columns is None and not entries:
        warnings.append(_parse_warning(0, "no usable header row found in CSV roster"))
    return entries, columns is not None


def _parse_text_rows(rows, warnings):
    entries = []
    columns = None
    for line, text in rows:
        if columns is None:
            header = _header_columns(text)
            if header is not None and not re.search(r"\d", text):
                columns = header
                continue

        pieces = _split_text_row(text)
        if columns is not None:
            if len(pieces) != len(columns):
                warnings.append(
                    _parse_warning(
                        line,
                        f"row has {len(pieces)} field(s), header has {len(columns)}",
                    )
                )
                continue
            fields = {logical: pieces[index] for logical, index in columns.items()}
        elif len(pieces) == 4:
            fields = {
                "date": pieces[0],
                "shift": pieces[1],
                "role": pieces[2],
                "person": pieces[3],
            }
        elif len(pieces) == 3:
            fields = {"date": pieces[0], "shift": pieces[1], "person": pieces[2]}
        else:
            warnings.append(
                _parse_warning(
                    line,
                    f"row has {len(pieces)} field(s), expected 3 (date shift person) "
                    "or 4 (date shift role person)",
                )
            )
            continue

        entry = _extract_entry(fields, line, warnings)
        if entry is not None:
            entries.append(entry)
    return entries, columns is not None


def _looks_like_csv(rows):
    if not rows:
        return False
    return rows[0][1].count(",") >= 2


def parse_roster_text(text, source="<text>"):
    """Parse roster text (CSV or whitespace-aligned) into a roster dict."""
    warnings = []
    if "\ufffd" in text:
        warnings.append(
            _parse_warning(
                0, "file contains bytes that are not valid UTF-8; names may be damaged"
            )
        )

    ward = ""
    month = ""
    rows = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            meta = _metadata(stripped.lstrip("#").strip())
            if meta:
                key, value = meta
                if key == "ward" and not ward:
                    ward = value
                elif key == "month" and not month:
                    month = _parse_month(value) or value
            continue
        meta = _metadata(stripped)
        if meta:
            key, value = meta
            if key == "ward" and not ward:
                ward = value
            elif key == "month" and not month:
                month = _parse_month(value) or value
            continue
        rows.append((line_number, stripped))

    if _looks_like_csv(rows):
        fmt = "csv"
        entries, header_found = _parse_csv_rows(rows, warnings)
    else:
        fmt = "text"
        entries, header_found = _parse_text_rows(rows, warnings)

    entries.sort(
        key=lambda item: (
            item["date"],
            SHIFT_ORDER.index(item["shift"]),
            item["role"].casefold(),
            _person_key(item["person"] or ""),
        )
    )
    return {
        "source": source,
        "format": fmt,
        "ward": ward,
        "month": month,
        "entries": entries,
        "header_found": header_found,
        "warnings": warnings,
    }


def _missing_dependency(name):
    return RosterError(
        f"reading this format needs the {name!r} package, which is not installed. "
        f"Install it with: {_INSTALL_LINES[name]} "
        "(or run: hermes plugins install --install-deps <plugin>)"
    )


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return _clean(str(value))


def _trim_cells(cells):
    trimmed = list(cells)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


def _xlsx_text(path):
    """Serialize the first worksheet to CSV-ish lines for the shared parser."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise _missing_dependency("openpyxl") from exc

    try:
        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise RosterError(f"could not open {path.name} as a workbook: {exc}") from exc

    try:
        if not workbook.worksheets:
            raise RosterError(f"{path.name} has no worksheets")
        rows = [
            _trim_cells([_cell_text(value) for value in row])
            for row in workbook.worksheets[0].iter_rows(values_only=True)
        ]
    finally:
        workbook.close()

    width = None
    for cells in rows:
        mapping = _columns_from_tokens(cells) if cells else None
        if mapping is not None:
            width = max(mapping.values()) + 1
            break
    if width is None:
        width = max((len(cells) for cells in rows), default=0)

    lines = []
    for cells in rows:
        if not any(cells):
            lines.append("")
            continue
        if len(cells) == 1:
            meta = _metadata(cells[0].lstrip("#").strip())
            if meta is not None and not cells[0].startswith("#"):
                lines.append(f"# {meta[0]}: {meta[1]}")
                continue
            if cells[0].startswith("#"):
                lines.append(cells[0])
                continue
        if len(cells) == 2:
            meta = _metadata(f"{cells[0]}: {cells[1]}")
            if meta is not None:
                lines.append(f"# {meta[0]}: {meta[1]}")
                continue
        padded = cells + [""] * max(0, width - len(cells))
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="").writerow(padded)
        lines.append(buffer.getvalue())
    return "\n".join(lines)


def _pdf_text(path):
    """Extract metadata lines and table-ish rows from a PDF for the shared parser."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise _missing_dependency("pdfplumber") from exc

    lines = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text(layout=True) or ""
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    tables = []
                if not tables:
                    lines.extend(text.splitlines())
                    continue
                for raw_line in text.splitlines():
                    if _metadata(raw_line.lstrip("#").strip()):
                        lines.append(raw_line)
                for table in tables:
                    for row in table:
                        cells = [_cell_text(cell) or "-" for cell in row]
                        if _columns_from_tokens(cells) is not None:
                            continue
                        lines.append("    ".join(cells))
    except RosterError:
        raise
    except Exception as exc:
        raise RosterError(f"could not read {path.name} as a PDF: {exc}") from exc
    return "\n".join(lines)


def _sniff_error(head):
    if head.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8")):
        return (
            "this looks like an image, not a roster: photos are not read. "
            "Ask for a PDF with a text layer or a spreadsheet."
        )
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "this is the old .xls format: save as .xlsx (Excel 2007+) and try again"
    return None


def _require_entries(roster, target):
    """A roster with zero entries is never reported as clean."""
    if roster["entries"]:
        return
    if not roster["header_found"]:
        raise RosterError(
            f"no roster rows found in {target}: expected a header row naming "
            "date, shift and person"
        )
    if not roster["warnings"]:
        month = roster["month"] or "the given month"
        roster["warnings"].append(
            _parse_warning(0, f"header found but no shifts listed for {month}")
        )


def read_roster(path):
    """Read and parse a roster file. Raises RosterError when it cannot be read."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise RosterError(f"roster file not found: {target}")

    try:
        with target.open("rb") as handle:
            head = handle.read(8)
    except OSError as exc:
        raise RosterError(f"could not read {target}: {exc}") from exc

    sniffed = _sniff_error(head)
    if sniffed is not None:
        raise RosterError(sniffed)

    suffix = target.suffix.casefold()
    if suffix in _XLSX_SUFFIXES:
        roster = parse_roster_text(_xlsx_text(target), source=target.name)
        roster["format"] = "xlsx"
    elif suffix in _PDF_SUFFIXES:
        text = _pdf_text(target)
        if not text.strip():
            raise RosterError(
                "this PDF has no text layer (it is a scan): it was not read. "
                "Export it as a spreadsheet or a text PDF."
            )
        roster = parse_roster_text(text, source=target.name)
        roster["format"] = "pdf"
    else:
        try:
            text = target.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            raise RosterError(f"could not read {target}: {exc}") from exc
        roster = parse_roster_text(text, source=target.name)

    _require_entries(roster, target)
    return roster


def _finding(kind, message, **extra):
    finding = {
        "type": kind,
        "severity": _SEVERITY[kind],
        "date": None,
        "shift": None,
        "role": "",
        "people": [],
        "line": None,
        "message": message,
    }
    finding.update(extra)
    return finding


def _covered_shifts_by_person(entries):
    by_person = {}
    for entry in entries:
        if not entry["person"]:
            continue
        person = by_person.setdefault(
            _person_key(entry["person"]), {"name": entry["person"], "shifts": {}}
        )
        person["shifts"].setdefault(entry["date"], set()).add(entry["shift"])
    return by_person


def _consecutive_days_findings(by_person):
    findings = []
    for key in sorted(by_person):
        person = by_person[key]
        days = sorted(date.fromisoformat(value) for value in person["shifts"])
        if not days:
            continue
        run_start = run_last = days[0]
        runs = []
        for day in days[1:]:
            if day == run_last + timedelta(days=1):
                run_last = day
                continue
            runs.append((run_start, run_last))
            run_start = run_last = day
        runs.append((run_start, run_last))

        for start, end in runs:
            length = (end - start).days + 1
            if length > MAX_CONSECUTIVE_DAYS:
                findings.append(
                    _finding(
                        "consecutive_days",
                        f"{person['name']} works {length} consecutive days "
                        f"({start.isoformat()} to {end.isoformat()})",
                        date=start.isoformat(),
                        people=[person["name"]],
                        end_date=end.isoformat(),
                        days=length,
                    )
                )
    return findings


def _rest_findings(by_person):
    findings = []
    for key in sorted(by_person):
        person = by_person[key]
        for day_text in sorted(person["shifts"]):
            if "night" not in person["shifts"][day_text]:
                continue
            day = date.fromisoformat(day_text)
            following = (day + timedelta(days=1)).isoformat()
            next_shifts = person["shifts"].get(following, set())
            day_shifts = [shift for shift in DAY_SHIFTS if shift in next_shifts]
            if not day_shifts:
                continue
            findings.append(
                _finding(
                    "no_rest_after_night",
                    f"{person['name']}: night shift on {day_text} followed by "
                    f"{day_shifts[0]} shift on {following} with no rest",
                    date=day_text,
                    shift="night",
                    people=[person["name"]],
                    next_shift=day_shifts[0],
                    next_date=following,
                )
            )
    return findings


def audit_roster_data(roster):
    """Return findings for a parsed roster dict."""
    entries = roster["entries"]
    findings = [dict(warning) for warning in roster.get("warnings", [])]

    for entry in entries:
        if entry["person"]:
            continue
        findings.append(
            _finding(
                "uncovered_shift",
                f"{entry['date']} {entry['shift']} shift"
                + (f" ({entry['role']})" if entry["role"] else "")
                + " has no person assigned",
                date=entry["date"],
                shift=entry["shift"],
                role=entry["role"],
            )
        )

    bookings = {}
    for entry in entries:
        if not entry["person"]:
            continue
        key = (entry["date"], entry["shift"], _person_key(entry["person"]))
        bookings.setdefault(key, []).append(entry)
    for (day, shift, key), items in sorted(bookings.items()):
        if len(items) < 2:
            continue
        person = items[0]["person"]
        roles = sorted({item["role"] or "unstated role" for item in items})
        findings.append(
            _finding(
                "double_booking",
                f"{person} is booked {len(items)} times on {day} {shift} "
                f"({', '.join(roles)})",
                date=day,
                shift=shift,
                people=[person],
                roles=roles,
                count=len(items),
            )
        )

    by_person = _covered_shifts_by_person(entries)
    findings.extend(_consecutive_days_findings(by_person))
    findings.extend(_rest_findings(by_person))

    findings.sort(
        key=lambda item: (
            item["date"] or "",
            SHIFT_ORDER.index(item["shift"]) if item["shift"] in SHIFT_ORDER else 9,
            item["type"],
            item["message"],
        )
    )
    return findings


def summarize(findings):
    summary = {kind: 0 for kind in FINDING_TYPES}
    for finding in findings:
        summary[finding["type"]] += 1
    return summary


def audit_roster(path):
    """Read and audit a roster file."""
    roster = read_roster(path)
    findings = audit_roster_data(roster)
    return roster, findings


def _entry_payload(entry):
    return {
        "date": entry["date"],
        "shift": entry["shift"],
        "role": entry["role"],
        "person": entry["person"] or "",
        "status": "covered" if entry["person"] else "uncovered",
    }


def _render_html(roster, findings, summary, source_name):
    ward = html.escape(roster["ward"] or "Duty roster")
    month = html.escape(roster["month"] or "")
    subtitle = " \u00b7 ".join(
        part
        for part in (
            ward,
            month,
            f"{len(roster['entries'])} entries",
            f"{len(findings)} problem{'s' if len(findings) != 1 else ''}",
        )
        if part
    )

    cards = [
        ("Uncovered shifts", summary["uncovered_shift"]),
        ("Double bookings", summary["double_booking"]),
        ("Long runs (>6 days)", summary["consecutive_days"]),
        ("Night then day", summary["no_rest_after_night"]),
        ("Unreadable rows", summary["parse_warning"]),
    ]
    card_html = "".join(
        f'<div class="card{" bad" if count else ""}"><span class="n">{count}</span>'
        f'<span class="l">{html.escape(label)}</span></div>'
        for label, count in cards
    )

    if findings:
        rows = "".join(
            "<tr>"
            f'<td class="t">{html.escape(finding["type"].replace("_", " "))}</td>'
            f'<td>{html.escape(finding.get("date") or _DASH)}</td>'
            f'<td>{html.escape(finding.get("shift") or _DASH)}</td>'
            f'<td>{html.escape(finding["message"])}</td>'
            "</tr>"
            for finding in findings
        )
        exceptions = (
            '<table class="exceptions"><thead><tr><th>Problem</th><th>Date</th>'
            "<th>Shift</th><th>Detail</th></tr></thead><tbody>"
            + rows
            + "</tbody></table>"
        )
    else:
        exceptions = (
            '<p class="ok">No exceptions found. Every shift is covered and every '
            "doctor has adequate rest.</p>"
        )

    schedule_rows = []
    for entry in roster["entries"]:
        day = date.fromisoformat(entry["date"])
        person = entry["person"]
        cell = html.escape(person) if person else '<span class="missing">UNCOVERED</span>'
        schedule_rows.append(
            "<tr>"
            f"<td>{entry['date']}</td><td>{day.strftime('%a')}</td>"
            f"<td>{html.escape(entry['shift'])}</td>"
            f"<td>{html.escape(entry['role'])}</td>"
            f"<td>{cell}</td>"
            "</tr>"
        )
    schedule = (
        '<table class="schedule"><thead><tr><th>Date</th><th>Day</th><th>Shift</th>'
        "<th>Role</th><th>Person</th></tr></thead><tbody>"
        + "".join(schedule_rows)
        + "</tbody></table>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Roster exceptions \u2014 {ward}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 32px 24px 48px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color: #1c2024; background: #f6f7f9; line-height: 1.45; }}
  main {{ max-width: 1040px; margin: 0 auto; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; letter-spacing: -0.02em; }}
  .sub {{ margin: 0 0 24px; color: #5b6470; font-size: 14px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 28px; }}
  .card {{ background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 2px; }}
  .card.bad {{ border-color: #e7b4ae; background: #fff7f6; }}
  .card .n {{ font-size: 26px; font-weight: 650; letter-spacing: -0.02em; }}
  .card.bad .n {{ color: #b3261e; }}
  .card .l {{ font-size: 12px; color: #5b6470; text-transform: uppercase; letter-spacing: 0.04em; }}
  h2 {{ font-size: 17px; margin: 32px 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e3e6ea; border-radius: 10px; overflow: hidden; }}
  th, td {{ text-align: left; padding: 9px 12px; font-size: 13px; border-bottom: 1px solid #eef0f2; vertical-align: top; }}
  th {{ background: #fafbfc; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: #5b6470; }}
  tr:last-child td {{ border-bottom: none; }}
  td.t {{ white-space: nowrap; font-weight: 600; }}
  .missing {{ color: #b3261e; font-weight: 650; }}
  .ok {{ background: #f1f8f2; border: 1px solid #bfe0c4; color: #1e6b2c; padding: 14px 16px; border-radius: 10px; margin: 0; }}
  footer {{ margin-top: 36px; color: #7a828c; font-size: 12px; }}
</style>
</head>
<body>
<main>
  <h1>Duty roster exceptions</h1>
  <p class="sub">{subtitle}</p>
  <div class="cards">{card_html}</div>
  {exceptions}
  <h2>Clean schedule</h2>
  {schedule}
  <footer>Generated by roster-compiler from <code>{html.escape(source_name)}</code>. Deterministic \u2014 no network, no model, input file unmodified.</footer>
</main>
</body>
</html>
"""


def export_roster(path, out_path):
    """Write a clean CSV plus an HTML exception report. Returns a result dict."""
    roster, findings = audit_roster(path)
    source = Path(path).expanduser()

    target = Path(out_path).expanduser()
    if target.suffix.casefold() == ".html":
        html_path = target
        csv_path = target.with_suffix(".csv")
    elif target.suffix.casefold() == ".csv":
        csv_path = target
        html_path = target.with_suffix(".html")
    else:
        csv_path = target.with_suffix(".csv")
        html_path = target.with_suffix(".html")

    for candidate in (csv_path, html_path):
        if candidate.resolve() == source.resolve():
            raise RosterError(
                f"refusing to overwrite the input roster: {candidate.resolve()}"
            )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["date", "day", "shift", "role", "person", "status"])
        for entry in roster["entries"]:
            day = date.fromisoformat(entry["date"])
            writer.writerow(
                [
                    entry["date"],
                    day.strftime("%a"),
                    entry["shift"],
                    entry["role"],
                    entry["person"] or "",
                    "covered" if entry["person"] else "uncovered",
                ]
            )

    html_path.write_text(
        _render_html(roster, findings, summarize(findings), source.name),
        encoding="utf-8",
    )

    return {
        "source": str(source),
        "csv": str(csv_path.resolve()),
        "html": str(html_path.resolve()),
        "entry_count": len(roster["entries"]),
        "finding_count": len(findings),
        "summary": summarize(findings),
    }


def _json(payload):
    return json.dumps(payload, indent=2, ensure_ascii=False)


def roster_read(args, **kwargs):
    """Tool handler: parse a roster file and return its entries as JSON."""
    path = (args or {}).get("path", "")
    if not str(path).strip():
        return _json({"ok": False, "error": "path is required"})
    try:
        roster = read_roster(path)
    except RosterError as exc:
        return _json({"ok": False, "error": str(exc)})
    except Exception as exc:
        return _json({"ok": False, "error": f"could not parse roster: {exc}"})

    entries = [_entry_payload(entry) for entry in roster["entries"]]
    return _json(
        {
            "ok": True,
            "source": roster["source"],
            "format": roster["format"],
            "ward": roster["ward"],
            "month": roster["month"],
            "entry_count": len(entries),
            "uncovered_count": sum(
                1 for entry in entries if entry["status"] == "uncovered"
            ),
            "parse_warning_count": len(roster["warnings"]),
            "entries": entries,
            "warnings": roster["warnings"],
        }
    )


def roster_audit(args, **kwargs):
    """Tool handler: parse a roster file and return its findings as JSON."""
    path = (args or {}).get("path", "")
    if not str(path).strip():
        return _json({"ok": False, "error": "path is required"})
    try:
        roster, findings = audit_roster(path)
    except RosterError as exc:
        return _json({"ok": False, "error": str(exc)})
    except Exception as exc:
        return _json({"ok": False, "error": f"could not audit roster: {exc}"})

    return _json(
        {
            "ok": True,
            "source": roster["source"],
            "ward": roster["ward"],
            "month": roster["month"],
            "entry_count": len(roster["entries"]),
            "finding_count": len(findings),
            "summary": summarize(findings),
            "findings": findings,
        }
    )


def roster_export(args, **kwargs):
    """Tool handler: write a clean CSV and HTML exception report."""
    args = args or {}
    path = args.get("path", "")
    out_path = args.get("out_path", "")
    if not str(path).strip():
        return _json({"ok": False, "error": "path is required"})
    if not str(out_path).strip():
        return _json({"ok": False, "error": "out_path is required"})
    try:
        result = export_roster(path, out_path)
    except RosterError as exc:
        return _json({"ok": False, "error": str(exc)})
    except Exception as exc:
        return _json({"ok": False, "error": f"could not export roster: {exc}"})

    return _json({"ok": True, **result})
