# MVP architecture

`ai-job-search` is a strong workflow reference: its profile, fit evaluation, application archive, drafter-reviewer, and safety boundaries are reusable. Its Denmark-focused portal CLIs, Claude-specific command layout, and LaTeX-first output are not part of this MVP.

This adaptation has four local layers:

1. `sources/` indexes existing resumes without copying them.
2. `profile/facts.json` is an evidence-bearing career fact store.
3. `jobs/inbox/` stores one immutable source snapshot per role and its evaluation.
4. `applications/`, `resumes/generated/`, and `resumes/submitted/` are reserved for later human-reviewed material generation.

The first release deliberately implements only resume indexing, opt-in Obsidian scan proposals, explicit approval, job import, deterministic fit evaluation, and ranking. It does not scrape portals, call an LLM, generate a resume, or submit applications.

## Reuse decision

| Upstream capability | MVP decision |
| --- | --- |
| Candidate profile and fit workflow | Reuse as `profile/` and `jobs/` data model |
| Application archive and outcome tracking | Keep directory boundary; implement later |
| Drafter-reviewer CV pipeline | Keep as phase 2; needs evidence review and document rendering |
| Danish portal CLIs | Replace later with source-specific importers |
| Claude command files | Adapt to Python CLI now; Codex prompts can be added later |
| LaTeX template pipeline | Defer; existing Word/PDF resumes are current source material |

## Privacy boundary

The vault path comes from `config/settings.local.json`; only its `Career/` child is in scope. The application installation folder was checked and excluded — it is not the vault.
