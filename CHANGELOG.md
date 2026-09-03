# Changelog

## 0.1.0 — 2026-07-26

- Created the local, evidence-first career-agent MVP.
- Added opt-in Obsidian proposal sync, resume indexing, job import/evaluation/ranking.
- Added user-provided job snapshots; imported snapshots are not live-verified by default.

## 0.2.0 — 2026-07-26

- Parsed all indexed resume files into a local extraction manifest and source-text archive.
- Added a master career profile, evidence index, review queues, and review command.
- Added source-linked Markdown base-resume drafts and DOCX rendering.
- Deferred DOCX visual rendering because LibreOffice is unavailable on this machine.

## 0.2.1 — 2026-07-26

- Installed LibreOffice 26.2.5 after SHA-256 verification against the official release hash.
- Rendered and visually checked DOCX resume drafts.
- Contact header moved to config/settings.local.json (never committed).
