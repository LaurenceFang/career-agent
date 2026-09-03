# Changelog

## 0.3.1 — 2026-09-03 (review patch)

- Fixed a gate false-negative: nonexistent absolute evidence paths escaped
  the existence check; both relative and absolute paths now must resolve,
  with paired regression tests (bad absolute path blocks, real absolute path
  passes).
- Documentation honesty: email sending and application submission described
  as unimplemented capabilities rather than confirmation-gated actions;
  implemented external writes stated precisely — Notion tracker sync and
  Google Calendar event creation, both requiring explicit confirmation,
  while Gmail and ATS access remain read-only.
- Test rationale reworded as adversarial design, with the two genuinely
  historical incidents (schema-shape drift, absolute-path review catch)
  labeled as such.

## 0.3.0 — 2026-09-03 (public mirror hardening)

- Republished as a sanitized public mirror: personal facts, real job
  evaluations, generated resumes and application records excluded; synthetic
  fixtures added (`profile/example_facts.json`, `jobs/example_synthetic/`,
  `fixtures/demo/`).
- Canonical provenance schema (`schemas/provenance.schema.json` +
  `scripts/provenance_schema.py`): one shape (`bullet_id`, `text`,
  `fact_ids`, `evidence_paths`) shared by base resumes, generated
  provenance and the gate.
- Gate rewritten: `--root` for isolated fixture workspaces, schema
  validation, evidence-path resolution checks, orphan provenance entries
  blocked, friendly missing-profile guidance instead of bare traceback.
- Fixed clean-clone failures: `generate_base_resumes` KeyError, hard-coded
  base names in `application_manager`, module-level `docx`/`pypdf` imports
  (now optional `requirements-docs.txt` extras).
- Added negative-proof test rig (`tests/test_gate.py`, `tests/test_smoke_cli.py`,
  18 tests, stdlib-only) and `scripts/run_demo.py` (valid → deliberately
  broken → repaired, real gate output).
- GitHub Actions CI (`python -m unittest discover` + demo on Ubuntu/Windows,
  3.11/3.12; extras job separately).
- Input boundaries: workspace-root confinement for `import-job`, slug
  validation, HTTP(S)-only + content-type + 5 MB cap on URL imports,
  argument checks on adapter runs; absolute paths and `%USERPROFILE%`
  assumptions replaced with env/`sys.executable` defaults.
- Notion lane: typed confirmation or `--confirm`, `--dry-run`, and
  repo-relative path labels — absolute local paths no longer leave the
  machine.
- Published the sanitized agent instruction surface
  (`docs/AGENT_CONTRACT.md`), rewrote `docs/ARCHITECTURE.md` for the current
  mirror, added limitations and upstream attribution (MIT, © Mads Lorentzen
  for the reference workflow design; no upstream code copied).

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
