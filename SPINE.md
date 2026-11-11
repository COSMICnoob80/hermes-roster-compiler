# SPINE — roster-compiler (Hermes plugin hackathon entry)

**Only state file. Append, never rewrite history.**

## Decision (made 2026-11-11, operator-approved)
- Entry: idea ① `roster-compiler`. Idea ③ (model-failover) is DEAD: the catalog already ships
  `model-fallback-heuristic` plus ~10 routing plugins.
- Deadline: submissions close 2026-11-12 03:00 PKT (5PM EST 11 Nov). Hard.
- Judging: usefulness, reliability, polish, creativity. Must do more than a prompt or a skill could.
- Shift Buddy Handover is NOT this: that belongs to Agentware, 27-30 Nov.

## Scope
- Deterministic hospital duty-roster compiler. Input: messy roster. Output: checked schedule + exception report.
- No LLM in the critical path. No network. No patient data ever (staff rosters only).
- Plugin never edits the input file.

## Waves
- W1 (tonight): plugin skeleton, 3 tools, CSV/plain-text parsing, 8 pytest tests, synthetic demo ward, README, MIT. Gate: pytest + `hermes plugins validate`.
- W2: xlsx + pdf input via declared deps (`validate --install-deps` CI gate), leave-file cross-check.
- W3: single-file HTML demo (judge touches it without installing), fake-data safe.
- W4: demo video <90s, X post tagging @NousResearch, catalog PR pinned to full SHA, Typeform before 22:00 PKT 11 Nov.

## Gates (never skip)
1. pytest green.
2. `hermes plugins validate` green.
3. Audit run by hand on the demo roster reports exactly the 3 planted defects.
4. No edits anywhere under ~/.hermes/ (running agent).

## W1 — DELIVERED 2026-11-11 (verified on disk, not intended)
- Files: `plugin.yaml` (roster-compiler 0.1.0), `__init__.py`, `roster_compiler.py`, `tests/test_roster.py`
  (12 tests), `tests/conftest.py`, `demo/ward3b-november.csv` (91 rows, 8 synthetic doctors, 30 days),
  `README.md`, `LICENSE`, `.gitignore`.
- Gate 1 `pytest tests/ -q`: 12 passed.
- Gate 2 `hermes plugins validate`: Validation passed — 15 checks green, "declared tools — matches registrations".
- Gate 3 root `pytest -q`: 12 passed; `import roster_compiler` → `import ok`.
- Gate 4 audit of demo: exactly 3 findings — consecutive_days 8 (Zara Whitfield 11-05→11-12),
  double_booking (Ines Duarte 11-13 morning), uncovered_shift (11-25 evening). parse_warning 0, no_rest 0.
- Notes: no writes under ~/.hermes. Unreadable rows → `parse_warning` with line number, never guessed.
  `__init__.py` guards its relative import so bare-module collectors (pytest) can load it.
- Open: W2 xlsx/pdf input + leave-file cross-check; W3 single-file HTML demo; W4 video, X post, catalog PR
  at full SHA, Typeform before 2026-11-12 03:00 PKT.
