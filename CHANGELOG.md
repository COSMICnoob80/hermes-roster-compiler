# Changelog

## 0.1.1 — 2026-11-12

- A file with no readable roster rows is never reported as clean: no header is an error, and a header with no shifts below it emits a `parse_warning`, so `finding_count` is never 0.
- Image files (JPEG, PNG, GIF) are refused with their own message instead of being parsed as text.
- Legacy `.xls` (CFB) files are refused with a save-as-`.xlsx` hint.
- A PDF with no text layer (a scan) is refused instead of returning an empty, clean roster.
