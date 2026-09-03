# Hermes integration

This workspace is operated through the isolated Hermes profile `careeragent`.
The profile contains the `/career-job-search` skill at:

`~/AppData/Local/hermes/profiles/careeragent/skills/career-job-search/SKILL.md`

The upstream job-search reference project (set via `AI_JOB_SEARCH_UPSTREAM`) remains unchanged as a reference for
workflow coverage. Hermes is the runtime for the local adaptation; its skill
uses this workspace's verified facts, local scripts, and provenance records.

## Start it

Open Hermes Desktop, switch to the `careeragent` profile, and set the active
project to **Career Agent**. Then use, for example:

```text
/career-job-search rank
/career-job-search resume demo-ai-intern
/career-job-search interview demo-ai-intern
```

## Covered workflow

| Hermes operation | Replaces upstream Claude workflow |
| --- | --- |
| `profile`, `sync` | `/setup`, `/expand` |
| `import-job`, `rank` | `/scrape`, `/rank` |
| `resume`, `review`, `cover` | `/apply`, `/add-template` |
| `interview` | `/interview` |
| `outcome`, `report` | `/outcome`, `/html-report` |
| `portal` | `/add-portal` |
| `template` | `/add-template` |
| `email-sync`, `notion-sync` | `/gmail-sync`, `/notion-sync` |
| `reset` | `/reset` |

Notion now supports a one-way local-to-Notion sync through
`scripts/notion_sync.py sync`; the local workspace remains the source of
truth. Job submission and email sending remain deliberately non-automatic.

## Google connector

`scripts/google_workspace.py` is a local connector, not a third-party email
proxy. It inherits the current Windows user proxy for Google API calls. Place a Google Cloud **Desktop app** OAuth client JSON at
`config/google_oauth_client.json`, then run `authorize`; the browser OAuth
window is used for login. Gmail access is read-only and writes local proposals;
only `approve-gmail-proposal ... --confirm` changes a local application status.
Calendar writes require `--confirm` for each event.
