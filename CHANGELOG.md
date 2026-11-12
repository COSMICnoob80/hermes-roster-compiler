# Changelog

## 0.1.2 — 2026-11-12

- Reads now respect Hermes's read denylist: a protected path (credential store, `.env`, internal cache) returns an error instead of its contents, so secrets cannot be read through the roster tools and echoed back in warnings.
- Writes now respect Hermes's write denylist. `roster_export` also refuses to overwrite an existing file unless called with `overwrite: true`, and reports a missing output folder instead of creating it.
- Dependency bounds narrowed to `openpyxl>=3.1,<4` and `pdfplumber>=0.11,<1`.

## 0.1.1 — 2026-11-12

- A file with no readable roster rows is never reported as clean: no header is an error, and a header with no shifts below it emits a `parse_warning`, so `finding_count` is never 0.
- Image files (JPEG, PNG, GIF) are refused with their own message instead of being parsed as text.
- Legacy `.xls` (CFB) files are refused with a save-as-`.xlsx` hint.
- A PDF with no text layer (a scan) is refused instead of returning an empty, clean roster.
