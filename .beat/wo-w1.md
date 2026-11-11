# WORK ORDER W1 — roster-compiler, vertical slice

You are building a Hermes Agent plugin in /home/cosmicnoob/hermes-roster-plugin.
Owner is a medical officer, not a programmer. Deadline is hours away, not days. Ship one thing that works.

## Read first, in this order
1. `SPINE.md` in this repo — the state of truth.
2. `/home/cosmicnoob/.hermes/hermes-agent/website/docs/developer-guide/plugins/index.md` — the plugin contract. Read the sections on `plugin.yaml`, tool registration, and what `plugins validate` checks.
3. `/home/cosmicnoob/.hermes/hermes-agent/website/docs/developer-guide/plugins/catalog-submission.md` — admission rules (no core patches, declared capabilities must match what is registered).
4. `/home/cosmicnoob/.hermes/hermes-agent/plugins/disk-cleanup/` — a real, working plugin. Copy its shape.

## What this plugin is for
Hospital duty rosters arrive as mess. A ward clerk types one in Word, someone photographs it, the HOD emails an
Excel sheet. Nobody checks them, so a doctor gets booked twice on the same night and a shift goes uncovered.
This plugin reads a roster, checks it, and writes a clean schedule plus a list of what is wrong.

Three tools, no model in the path, no network:
- `roster_read(path)` — parse a roster file, return JSON: ward, month, entries[{date, shift, role, person}]
- `roster_audit(path)` — return findings: uncovered shift, double booking (same person, two places, same shift),
  more than 6 consecutive working days, night shift followed by a day shift with no rest
- `roster_export(path, out_path)` — write a clean CSV plus a readable HTML exception report

## Scope for THIS run only
- Input: CSV and whitespace-aligned plain text. NOT PDF, NOT xlsx, NOT images. Those are W2.
- ZERO third-party dependencies. stdlib only (csv, re, datetime, json). `openpyxl` and `pdfplumber` are not
  installed in the Hermes venv and must not be added tonight.
- No LLM calls anywhere. Every decision must be reproducible from the file bytes.
- Keep the parser honest about ambiguity: if a row cannot be understood, report it as a `parse_warning`
  finding instead of guessing.

## Deliverables, exact paths
- `plugin.yaml` — name `roster-compiler`, version `0.1.0`, description in plain words, `provides_tools: [roster_read, roster_audit, roster_export]`
- `__init__.py` and `roster_compiler.py` — registration plus logic, split as you prefer
- `tests/test_roster.py` — pytest, at least 8 tests, including one case with a real defect and one malformed row
- `demo/ward3b-november.csv` — SYNTHETIC ONLY. Ward "3B, General Hospital", 8 invented doctors, 30 days of
  morning/evening/night shifts, and exactly 3 planted defects: one uncovered shift, one double booking,
  one 8-day unbroken run. No real names, no real hospital, no patient data.
- `README.md` — what it does, the problem in two sentences, install line, and a 90-second demo script
- `LICENSE` — MIT
- `.gitignore`

## Hard rules
- Work only inside this directory. NEVER write, edit or delete anything under `/home/cosmicnoob/.hermes/`.
  That is the user's live agent; touching it can take his system down.
- The plugin never modifies its input file. It reads, then writes new files.
- Rosters contain staff names only. No clinical data, ever.

## Gate — all four must pass, paste raw output in your report
1. `/home/cosmicnoob/.hermes/hermes-agent/venv/bin/python -m pytest tests/ -q`
2. `hermes plugins validate /home/cosmicnoob/hermes-roster-plugin`
3. `/home/cosmicnoob/.hermes/hermes-agent/venv/bin/python -m pytest -q` from the repo root, then a direct
   import check: `cd /home/cosmicnoob/hermes-roster-plugin && /home/cosmicnoob/.hermes/hermes-agent/venv/bin/python -c "import roster_compiler; print('import ok')"`
4. Run `roster_audit` by hand against `demo/ward3b-november.csv` and paste the findings. It must report
   exactly the 3 planted defects, no more, no fewer.

## Report
State what you verified on disk, not what you intended. If a gate fails, name it and say why. Never claim
done without pasted gate output.
