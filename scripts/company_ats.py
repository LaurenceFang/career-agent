#!/usr/bin/env python3
"""Import public company careers boards from Greenhouse, Lever, or Ashby."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from career_agent import evaluate_job, rank_jobs
from windows_proxy import proxied_environment

ROOT = Path(__file__).resolve().parents[1]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80]


def fetch_json(url: str) -> object:
    proxy = proxied_environment()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy.get("HTTP_PROXY", ""), "https": proxy.get("HTTPS_PROXY", "")}))
    request = urllib.request.Request(url, headers={"User-Agent": "CareerAgent/1.0 (personal job search; public ATS board)"})
    with opener.open(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def board(url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
    host, parts = parsed.netloc.lower(), [piece for piece in parsed.path.split("/") if piece]
    if "greenhouse" in host and parts:
        return "greenhouse", parts[-1]
    if "lever.co" in host and parts:
        return "lever", parts[-1]
    if "ashbyhq.com" in host and parts:
        return "ashby", parts[-1]
    raise SystemExit("Unsupported ATS URL. Use a Greenhouse, Lever, or Ashby company careers-board URL.")


def normalize(provider: str, token: str) -> list[dict]:
    if provider == "greenhouse":
        payload = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
        return [{"id": str(row["id"]), "title": row.get("title", "Untitled"), "location": row.get("location", {}).get("name", ""), "url": row.get("absolute_url", ""), "description": row.get("content", ""), "company": token} for row in payload.get("jobs", [])]
    if provider == "lever":
        payload = fetch_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
        return [{"id": str(row.get("id")), "title": row.get("text", "Untitled"), "location": row.get("categories", {}).get("location", ""), "url": row.get("hostedUrl", ""), "description": row.get("descriptionPlain", row.get("description", "")), "company": token} for row in payload]
    payload = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    return [{"id": str(row.get("jobUrl", row.get("id", row.get("title")))), "title": row.get("title", "Untitled"), "location": row.get("location", ""), "url": row.get("jobUrl", ""), "description": row.get("descriptionPlain", ""), "company": token} for row in payload.get("jobs", []) if row.get("isListed", True)]


def write_job(provider: str, company: str, row: dict) -> str | None:
    job_id = f"ats-{provider}-{slug(company)}-{slug(str(row['id']))}"
    target = ROOT / "jobs" / "inbox" / job_id / "job.md"
    if target.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    location = row.get("location", "")
    remote = "Remote" if "remote" in location.lower() else location or "Unknown"
    cleaned = re.sub(r"<[^>]+>", " ", row.get("description", ""))
    target.write_text("\n".join(["---", f"source: {provider}", f"source_url: {row.get('url','')}", "live_status: imported_from_public_company_ats", f"retrieved_at: {datetime.now(timezone.utc).isoformat()}", f"remote_scope: {remote}", "education: unknown", "---", "", f"# {row.get('title','Untitled')} — {row.get('company', company)}", "", "## Public company ATS listing", f"- Provider: {provider}", f"- Location: {location}", f"- Apply URL: {row.get('url','')}", "", "## Description", cleaned.strip()]) + "\n", encoding="utf-8")
    evaluate_job(SimpleNamespace(job_id=job_id))
    return job_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board_url")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--no-notion-sync", action="store_true")
    args = parser.parse_args()
    provider, token = board(args.board_url)
    rows = normalize(provider, token)
    snapshot = ROOT / "jobs" / "discovery" / provider / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{slug(token)}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(json.dumps({"provider": provider, "board": token, "retrieved_at": datetime.now(timezone.utc).isoformat(), "jobs": rows}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    imported = [job_id for row in rows[:args.limit] if (job_id := write_job(provider, token, row))]
    rank_jobs(SimpleNamespace())
    if not args.no_notion_sync:
        try:
            from notion_sync import run_sync
            import asyncio
            asyncio.run(run_sync(SimpleNamespace()))
        except ImportError:
            print("NOTE: Notion sync skipped (notion lane needs a local Hermes runtime).")
    print(json.dumps({"provider": provider, "snapshot": str(snapshot.relative_to(ROOT)), "found": len(rows), "imported": imported}, ensure_ascii=False))


if __name__ == "__main__":
    main()
