#!/usr/bin/env python3
"""One-way, evidence-minimizing sync from local Career Agent records to Notion."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import notion_mcp

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252; labels/statuses are non-ASCII
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
CONFIG = ROOT / "config" / "notion.local.json"
MANIFEST = ROOT / "config" / "notion_sync_manifest.json"


def load(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else ({} if default is None else default)


def _relative_label(value: str) -> str:
    """Never ship absolute local paths to Notion: keep only the trailing
    <repo-relative> fragment, e.g. 'resumes/foo/resume.md'."""
    if not value:
        return ""
    v = value.replace("\\", "/")
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if v.lower().startswith(root.lower()):
        return v[len(root):].lstrip("/")
    return Path(v).name  # outside the repo: filename only


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def frontmatter(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def job_records() -> list[tuple[str, dict]]:
    rows = []
    for job in sorted((ROOT / "jobs" / "inbox").glob("*/job.md")):
        meta = frontmatter(job)
        evaluation_path = job.with_name("evaluation.json")
        evaluation = load(evaluation_path, {})
        title_line = next((line[2:] for line in job.read_text(encoding="utf-8").splitlines() if line.startswith("# ")), job.parent.name)
        role, _, company = title_line.partition(" — ")
        rows.append((job.parent.name, {"Job ID": job.parent.name, "Company": company or "Unknown", "Role": role, "Source URL": meta.get("source_url", ""), "Fit Score": evaluation.get("total", 0), "Status": "进行中", "date:Last Reviewed:start": datetime.now(timezone.utc).date().isoformat(), "date:Last Reviewed:is_datetime": 0}))
    return rows


def application_records() -> list[tuple[str, dict]]:
    rows = []
    for path in sorted((ROOT / "applications").glob("*/application.json")):
        data = load(path)
        status = {"draft": "未开始", "applied": "进行中", "interview": "进行中", "offer": "完成", "rejected": "完成", "withdrawn": "完成", "no_response": "进行中"}.get(data.get("status"), "未开始")
        rows.append((data["job_id"], {"Job ID": data["job_id"], "Company": "", "Role": "", "Status": status, "Resume Path": _relative_label(data.get("materials", {}).get("resume", "")), "date:Applied Date:start": (data.get("submitted_at") or "")[:10] or None, "date:Applied Date:is_datetime": 0}))
    return rows


def evidence_records() -> list[tuple[str, dict]]:
    master = load(ROOT / "profile" / "master" / "profile.json")
    rows = []
    for field, category in (("projects", "project"), ("experience", "experience"), ("skills", "skill")):
        for item in master.get(field, []):
            fact_id = item.get("id") or item.get("name")
            if not fact_id:
                continue
            paths = "; ".join(_relative_label(entry.get("path", "")) for entry in item.get("evidence", [])[:3])
            status = "完成" if item.get("status") in {"verified_consensus", "verified"} else "未开始"
            rows.append((fact_id, {"Fact ID": fact_id, "Category": category, "Status": status, "Source Paths": paths, "date:Last Reviewed:start": datetime.now(timezone.utc).date().isoformat(), "date:Last Reviewed:is_datetime": 0}))
    return rows


async def call(name: str, arguments: dict) -> list[str]:
    async def operation(session):
        result = await session.call_tool(name, arguments=arguments)
        if result.isError:
            raise SystemExit(f"Notion {name} failed: {result.content}")
        return [block.text for block in result.content or [] if getattr(block, "text", None)]
    return await notion_mcp.with_session(operation)


def created_page_id(blocks: list[str]) -> str:
    for block in blocks:
        try:
            payload = json.loads(block)
            pages = payload.get("pages", [])
            if pages and pages[0].get("id"):
                return pages[0]["id"]
        except json.JSONDecodeError:
            continue
    raise SystemExit("Notion did not return a created page ID.")


async def sync_collection(label: str, data_source_id: str, records: list[tuple[str, dict]], manifest: dict) -> tuple[int, int]:
    created = updated = 0
    state = manifest.setdefault(label, {})
    for key, properties in records:
        current = fingerprint(properties)
        old = state.get(key, {})
        if old.get("fingerprint") == current:
            continue
        if old.get("page_id"):
            await call("notion-update-page", {"page_id": old["page_id"], "command": "update_properties", "properties": properties})
            updated += 1
        else:
            blocks = await call("notion-create-pages", {"parent": {"data_source_id": data_source_id}, "pages": [{"properties": properties}]})
            old["page_id"] = created_page_id(blocks)
            created += 1
        old["fingerprint"] = current
        state[key] = old
    return created, updated


def _confirm_local_payload(columns: list[tuple]) -> None:
    """This sync ships job titles, fit scores, resume paths and evidence source
    paths to an external workspace. Require an explicit acknowledgement."""
    print("About to sync the following LOCAL record columns to Notion:")
    for label, rows in columns:
        keys = sorted({k for _, props in rows[:50] for k in props})[:12]
        print(f"  - {label}: {len(rows)} records, fields like {keys}")
    answer = input("Type 'sync' to confirm sending this metadata to Notion: ")
    if answer.strip() != "sync":
        raise SystemExit("Notion sync cancelled (no confirmation).")


async def run_sync(args):
    config = load(CONFIG)
    manifest = load(MANIFEST, {})
    databases = config["databases"]
    if getattr(args, "dry_run", False):
        report = {label: len(recs) for label, _, recs in (
            ("jobs", None, job_records()),
            ("applications", None, application_records()),
            ("career_evidence", None, evidence_records()))}
        print(json.dumps({"dry_run": True, "would_sync": report}, ensure_ascii=False))
        return
    prepared = (("jobs", databases["jobs"]["data_source_id"], job_records()),
                ("applications", databases["applications"]["data_source_id"], application_records()),
                ("career_evidence", databases["career_evidence"]["data_source_id"], evidence_records()))
    if not getattr(args, "confirm", False):
        _confirm_local_payload([(label, recs) for label, _, recs in prepared])
    totals = []
    for label, source, records in (("jobs", databases["jobs"]["data_source_id"], job_records()), ("applications", databases["applications"]["data_source_id"], application_records()), ("career_evidence", databases["career_evidence"]["data_source_id"], evidence_records())):
        totals.append((label, *await sync_collection(label, source, records, manifest)))
    manifest["synced_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({label: {"created": created, "updated": updated} for label, created, updated in totals}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sync_cmd = sub.add_parser("sync")
    sync_cmd.add_argument("--dry-run", action="store_true", help="print what would sync; send nothing")
    sync_cmd.add_argument("--confirm", action="store_true", help="skip the interactive confirmation word")
    sync_cmd.set_defaults(func=run_sync)
    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
