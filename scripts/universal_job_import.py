#!/usr/bin/env python3
"""Evidence-preserving import for a public job URL or a Chrome-copied JD text file."""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from career_agent import evaluate_job, rank_jobs
from windows_proxy import proxied_environment

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252; labels/statuses are non-ASCII
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:72] or "job"


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.text = []; self.meta = {}; self.scripts = []; self._script_type = None; self._script = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key and attrs.get("content"): self.meta[key.lower()] = attrs["content"]
        if tag == "script":
            self._script_type = attrs.get("type", "").lower(); self._script = []
    def handle_endtag(self, tag):
        if tag == "script" and self._script_type == "application/ld+json": self.scripts.append("".join(self._script))
        if tag == "script": self._script_type = None
    def handle_data(self, data):
        if self._script_type is not None: self._script.append(data)
        elif data.strip(): self.text.append(data.strip())


def get_url(url: str) -> tuple[str, str]:
    env = proxied_environment()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": env.get("HTTP_PROXY", ""), "https": env.get("HTTPS_PROXY", "")}))
    if urlparse(url).scheme not in ("http", "https"):
        raise SystemExit(f"Refusing non-HTTP scheme: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "CareerAgent/1.0 (personal job search; user-requested URL import)"})
    with opener.open(request, timeout=30) as response:
        ctype = response.headers.get("Content-Type", "")
        if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
            raise SystemExit(f"Refusing non-text response: {ctype}")
        body = response.read(5_000_000)  # hard cap: 5 MB
        return response.url, body.decode("utf-8", errors="replace")


def find_job_posting(value):
    if isinstance(value, list):
        for item in value:
            result = find_job_posting(item)
            if result: return result
    if isinstance(value, dict):
        kind = value.get("@type", "")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind): return value
        for item in value.values():
            result = find_job_posting(item)
            if result: return result
    return None


def extract_url(url: str) -> dict:
    final_url, raw = get_url(url)
    parser = PageParser(); parser.feed(raw)
    posting = None
    for script in parser.scripts:
        try:
            posting = find_job_posting(json.loads(script))
        except json.JSONDecodeError:
            continue
        if posting: break
    if posting:
        company = posting.get("hiringOrganization", {})
        company = company.get("name", "Unknown company") if isinstance(company, dict) else str(company)
        location = posting.get("jobLocation", "")
        if isinstance(location, list): location = location[0] if location else ""
        if isinstance(location, dict): location = location.get("address", {}).get("addressLocality", "") or location.get("name", "")
        return {"url": final_url, "title": posting.get("title", "Untitled"), "company": company, "location": str(location), "description": re.sub(r"<[^>]+>", " ", posting.get("description", "")), "extraction": "json_ld_jobposting"}
    title = parser.meta.get("og:title") or parser.meta.get("twitter:title") or next((item for item in parser.text if len(item) < 180), "Untitled")
    description = "\n".join(parser.text)
    return {"url": final_url, "title": html.unescape(title), "company": "Unknown company", "location": "Unknown", "description": description, "extraction": "visible_page_text"}


def import_record(record: dict, requested_id: str | None, no_notion_sync: bool) -> str:
    job_id = requested_id or f"url-{slug(urlparse(record['url']).netloc)}-{slug(record['title'])}"
    target = ROOT / "jobs" / "inbox" / job_id / "job.md"
    if target.exists(): raise SystemExit(f"Refusing to overwrite immutable job snapshot: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    scope_text = f"{record['title']} {record['location']} {record['description']}".lower()
    remote_scope = "Remote" if ("remote" in scope_text or "work from home" in scope_text or "work-from-home" in scope_text or "wfh" in scope_text or "fully remote" in scope_text) else (record["location"] or "Unknown")
    target.write_text("\n".join(["---", "source: universal_job_import", f"source_url: {record['url']}", "live_status: imported_from_user_requested_url", f"retrieved_at: {datetime.now(timezone.utc).isoformat()}", f"remote_scope: {remote_scope}", "education: unknown", f"extraction: {record['extraction']}", "---", "", f"# {record['title']} — {record['company']}", "", "## Imported job description", record["description"].strip()]) + "\n", encoding="utf-8")
    evaluate_job(SimpleNamespace(job_id=job_id)); rank_jobs(SimpleNamespace())
    if not no_notion_sync:
        try:
            from notion_sync import run_sync
            asyncio.run(run_sync(SimpleNamespace()))
        except ImportError:
            print("NOTE: Notion sync skipped (notion lane needs a local Hermes runtime).")
    return job_id


def import_url(args):
    record = extract_url(args.url)
    job_id = import_record(record, args.job_id, args.no_notion_sync)
    print(json.dumps({"job_id": job_id, "source_url": record["url"], "extraction": record["extraction"]}, ensure_ascii=False))


def import_text(args):
    source = Path(args.text_file)
    if not source.exists(): raise SystemExit(f"JD text file not found: {source}")
    text = source.read_text(encoding="utf-8").strip()
    if len(text) < 120: raise SystemExit("JD text is too short; copy the full visible job description from Chrome.")
    record = {"url": args.source_url, "title": args.title, "company": args.company, "location": args.location, "description": text, "extraction": "user_copied_chrome_text"}
    print(json.dumps({"job_id": import_record(record, args.job_id, args.no_notion_sync), "source_url": args.source_url, "extraction": record["extraction"]}, ensure_ascii=False))


def import_clipboard(args):
    copied = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True, text=True, timeout=10)
    if copied.returncode or len(copied.stdout.strip()) < 120:
        raise SystemExit("Copy the full visible job description from Chrome first.")
    record = {"url": args.source_url, "title": args.title, "company": args.company, "location": args.location, "description": copied.stdout.strip(), "extraction": "user_copied_chrome_text"}
    print(json.dumps({"job_id": import_record(record, args.job_id, args.no_notion_sync), "source_url": args.source_url, "extraction": record["extraction"]}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    url = sub.add_parser("url"); url.add_argument("url"); url.add_argument("--job-id"); url.add_argument("--no-notion-sync", action="store_true"); url.set_defaults(func=import_url)
    text = sub.add_parser("text"); text.add_argument("job_id"); text.add_argument("text_file"); text.add_argument("--source-url", required=True); text.add_argument("--title", required=True); text.add_argument("--company", required=True); text.add_argument("--location", default="Unknown"); text.add_argument("--no-notion-sync", action="store_true"); text.set_defaults(func=import_text)
    clip = sub.add_parser("clipboard"); clip.add_argument("job_id"); clip.add_argument("--source-url", required=True); clip.add_argument("--title", required=True); clip.add_argument("--company", required=True); clip.add_argument("--location", default="Unknown"); clip.add_argument("--no-notion-sync", action="store_true"); clip.set_defaults(func=import_clipboard)
    args = parser.parse_args(); args.func(args)


if __name__ == "__main__": main()
