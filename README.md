# Career Agent

A local, evidence-first job-search workspace driven by Python scripts + an AI agent
(Hermes Agent profile). It keeps a verified career profile, imports job snapshots,
scores them against hard constraints, gates every resume bullet on traceable
provenance, and tracks applications — all offline, with nothing sent anywhere
without an explicit human confirmation.

## Why this exists

Most AI-assisted job hunting produces confident nonsense: invented metrics,
unverified claims, resumes that read well and die in screening. This workspace
enforces one rule everywhere: **no claim without evidence**. Every resume line
maps to a fact ID with an original source path; a deterministic gate script
refuses to export a draft whose provenance is incomplete.

## Pipeline

```
raw notes (Obsidian vault)
  └─> master_profile.py      parse → review queue → approved facts (profile/facts.json)
        └─> career_agent.py  import-job (immutable snapshots) → evaluate-job (scored rubric)
              └─> application_manager.py  generate-resume / cover-letter / interview-pack
                    └─> hermes_resume_gate.py  BLOCKS export unless every bullet has
                          a provenance entry with known fact IDs + evidence paths
```

- `rag_evidence.py` — small retrieval layer over the evidence corpus so the agent
  quotes documents instead of recalling them.
- `job_discovery.py` / `company_ats.py` / `universal_job_import.py` — pull postings
  straight from public ATS APIs (Ashby/Greenhouse/Lever JSON), verify liveness,
  and decode eligibility fine print before a lead is trusted.
- `google_workspace.py` / `notion_sync.py` — optional read-only connector lanes;
  proposals are only applied with `--confirm`.

## Design decisions

- **Immutable job snapshots.** An imported posting is never edited; all evaluation
  runs against the snapshot plus its retrieval timestamp, so a verdict can always
  be replayed.
- **Deterministic scoring.** `evaluate-job` (see `config/evaluation_rules.json`)
  weights location / education / technical / evidence / availability with hard
  constraints first — a broken work-authorization clause zeroes the score
  regardless of how good the prose looks.
- **The agent drafts, the human ships.** Email sending, application submission and
  tracker writes require an explicit confirmation step outside the agent's reach.

## Example in the repo

`jobs/example_synthetic/demo-ai-intern/` holds a synthetic job snapshot and its
`evaluation.json` output — the whole import → evaluate loop in two files.

## Layout

```
scripts/    the pipeline (stdlib-only Python; connector extras in requirements-connectors.txt)
config/     evaluation rubric + settings/oauth examples (copy *.example.* to *.local.*)
docs/       architecture and agent-integration notes
jobs/       inbox snapshots; _incoming staging
```

Personal data (profile facts, resumes, applications, outreach lists) lives in
gitignored local directories by design — this repo is the machinery, not the
payload. Copy `config/settings.example.json` to `config/settings.local.json`
and fill in your own identity/parse rules; scripts read candidate identity and
profile parse rules only from that local file, never from source.

## Requirements

Python 3.11+, standard library only for the core pipeline.
`pip install -r requirements-connectors.txt` for the Gmail/Notion lanes.
