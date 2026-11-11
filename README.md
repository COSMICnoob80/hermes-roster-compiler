# roster-compiler

A ward roster is typed in Word, photographed, or emailed as a spreadsheet, and nobody checks it — so a doctor gets booked twice on the same night and a shift goes uncovered. This plugin reads that roster, checks it against four hard rules, and writes a clean schedule plus a readable list of what is wrong.

No model, no network. CSV and plain-text rosters need only the standard library; `.xlsx` and `.pdf` readers import `openpyxl` and `pdfplumber` lazily. The same file always produces the same findings.

## Install

```
hermes plugins install COSMICnoob80/hermes-roster-plugin --enable
```

Or, from a local checkout: copy this directory to `~/.hermes/plugins/roster-compiler`, then `hermes plugins enable roster-compiler`.

Check it loaded:

```
hermes plugins list
```

## What it reads

CSV, whitespace-aligned plain text, Excel (`.xlsx`, first worksheet) or a text-layer PDF (ruled tables are read cell by cell).

The Excel and PDF readers turn their input into the same rows the text parser already understands, so every format produces identical findings. Their libraries are imported only when a file of that type is opened: without `openpyxl` or `pdfplumber` installed, the tool returns a clear error naming the `pip install` line instead of crashing.

CSV, with optional `#` metadata lines:

```
# ward: 3B, General Hospital
# month: 2026-11
date,shift,role,person
2026-11-01,morning,SHO,Dr. Zara Whitfield
2026-11-01,evening,Registrar,Dr. Peter Voss
```

Plain text, columns separated by two or more spaces:

```
WARD: 3B, General Hospital
MONTH: 2026-11
DATE         SHIFT     ROLE        PERSON
2026-11-01   morning   SHO         Dr. Zara Whitfield
2026-11-01   evening   Registrar   Dr. Peter Voss
```

- **Dates**: `2026-11-01`, `01/11/2026` (day first) or `01-11-2026`.
- **Shifts**: `morning`/`am`, `evening`/`pm`, `night` (also `M`, `E`, `N`). Anything else is reported, never guessed.
- **A shift is uncovered** when the person cell is blank or says `-`, `TBD`, `vacant`, `??`, `n/a`.
- **A row that cannot be read** becomes a `parse_warning` finding with its line number. It is not skipped silently and it is not guessed at.

## The four rules

| Finding | Meaning |
|---|---|
| `uncovered_shift` | A dated shift has no person assigned. |
| `double_booking` | The same person appears twice on the same date and shift — in two places at once. |
| `consecutive_days` | More than 6 consecutive calendar days with at least one shift. |
| `no_rest_after_night` | A night shift followed the next day by a morning or evening shift. |

## Tools

| Tool | Returns |
|---|---|
| `roster_read(path)` | Ward, month and `entries[{date, shift, role, person}]`, plus any parse warnings. |
| `roster_audit(path)` | All findings and a per-type summary. |
| `roster_export(path, out_path)` | A clean CSV (sorted by date, then shift) and an HTML exception report beside it. |

`roster_export` writes `out_path` as the CSV and puts the report next to it with an `.html` extension. If `out_path` ends in `.html` the roles swap instead. The input roster is opened read-only and is never modified; exporting onto the input path is refused.

## 90-second demo

```bash
cd hermes-roster-plugin
hermes plugins validate .          # manifest, registration, declared tools, security scan
/hermes chat
```

Inside the session, ask:

> Audit `demo/ward3b-november.csv` and tell me what is wrong with the roster.

Expected answer: exactly three problems — an 8-day unbroken run for Dr. Zara Whitfield, Dr. Ines Duarte booked twice on the 13th morning, and the 25th evening shift uncovered. Then:

> Export the clean schedule to `/tmp/ward3b-clean.csv` and open the HTML report.

Without installing anything:

```bash
python -m pytest tests/ -q
python -c "import roster_compiler, json; print(json.loads(roster_compiler.roster_audit({'path':'demo/ward3b-november.csv'}))['summary'])"
```

## Safety and privacy

- Rosters contain staff names only. No clinical or patient data is read, written or required.
- No network access, no LLM calls, no telemetry.
- The plugin reads the input and writes only the paths you name. It refuses to overwrite its own input.
- `demo/ward3b-november.csv` is synthetic: an invented ward, eight invented doctors and three deliberately planted defects.

## Limits

- Photographs and scanned images are not read; a PDF needs a text layer.
- `.xlsx` and `.pdf` need `openpyxl` and `pdfplumber`, declared under `python_dependencies` in `plugin.yaml` so install and catalog CI provide them. Missing libraries produce an install hint, never a crash.
- Headerless files are rejected with a parse warning rather than guessed at.
- Public holidays, leave balances and skill mix are not checked — only the four rules above.

## Development

```bash
python -m pytest tests/ -q
hermes plugins validate .
```

MIT licensed.
