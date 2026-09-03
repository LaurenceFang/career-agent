#!/usr/bin/env python3
"""Low-volume public-job discovery with snapshot-first import gates."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from windows_proxy import proxied_environment

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("AI_JOB_SEARCH_UPSTREAM", str(Path.home() / "ai-job-search")))
LINKEDIN = UPSTREAM / ".agents" / "skills" / "linkedin-search" / "cli" / "src" / "cli.ts"
FREEHIRE = UPSTREAM / ".agents" / "skills" / "freehire-search" / "cli" / "src" / "cli.ts"


def run_cli(script: Path, command: list[str]) -> dict:
    # Boundary: run_cli executes upstream adapter CLIs pinned to UPSTREAM as cwd
    # with a fixed timeout and no shell. `--query`/`--location` values are passed
    # as argv (never interpolated), but the upstream code itself runs with this
    # process's privileges: point AI_JOB_SEARCH_UPSTREAM only at a trusted checkout.
    if not script.is_file():
        raise SystemExit(f"Adapter script missing: {script}")
    for token in command:
        if not isinstance(token, str) or "\x00" in token or len(token) > 200:
            raise SystemExit("Adapter argument rejected (length/encoding).")
    launcher = "npx.cmd" if sys.platform == "win32" else "npx"
    resolved = shutil.which(launcher)
    if not resolved:
        raise SystemExit("npx/tsx is required for the upstream public-job adapter but was not found on PATH.")
    completed = subprocess.run([resolved, "--yes", "tsx", str(script), *command], cwd=UPSTREAM, text=True, capture_output=True, timeout=60, env=proxied_environment())
    if completed.returncode:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip() or "Job source request failed")
    return json.loads(completed.stdout)


def save_snapshot(source: str, query: str, data: dict) -> Path:
    stamped = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "jobs" / "discovery" / source / f"{stamped}_{slug(query)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"source": source, "retrieved_at": datetime.now(timezone.utc).isoformat(), "query": query, "data": data}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return path


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "jobs"


def discover_freehire(args) -> None:
    cmd = ["search", "--query", args.query, "--limit", str(args.limit), "--format", "json"]
    if args.remote: cmd += ["--remote", args.remote]
    if args.jobage: cmd += ["--jobage", str(args.jobage)]
    data = run_cli(FREEHIRE, cmd)
    path = save_snapshot("freehire", args.query, data)
    print(f"Saved {len(data.get('results', []))} FreeHire results -> {path.relative_to(ROOT)}")


def discover_linkedin(args) -> None:
    cmd = ["search", "--query", args.query, "--location", args.location, "--limit", str(args.limit), "--format", "json"]
    if args.remote: cmd += ["--remote", args.remote]
    if args.jobage: cmd += ["--jobage", str(args.jobage)]
    try:
        data = run_cli(LINKEDIN, cmd)
    except SystemExit as exc:
        raise SystemExit(f"LinkedIn public source unavailable: {exc}. Use FreeHire or import a Chrome-captured job URL instead.")
    path = save_snapshot("linkedin", args.query, data)
    print(f"Saved {len(data.get('results', []))} LinkedIn results -> {path.relative_to(ROOT)}")


def import_freehire(args) -> None:
    snapshot = Path(args.snapshot)
    if not snapshot.exists(): raise SystemExit(f"Snapshot not found: {snapshot}")
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    result = next((item for item in payload.get("data", {}).get("results", []) if item.get("id") == args.result_id), None)
    if not result: raise SystemExit(f"Result id not found: {args.result_id}")
    target = ROOT / "jobs" / "inbox" / args.job_id / "job.md"
    if target.exists(): raise SystemExit(f"Refusing to overwrite immutable job snapshot: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = ["---", "source: freehire", f"source_url: {result.get('url','')}", "live_status: imported_from_public_snapshot", f"retrieved_at: {payload.get('retrieved_at','')}", f"work_mode: {result.get('work_mode','')}", f"location: {result.get('location','')}", "---", ""]
    body = [f"# {result.get('title','Untitled')} — {result.get('company','Unknown company')}", "", "## Imported public listing", f"- Source: {result.get('url','')}", f"- Posted: {result.get('date','')}", f"- Location: {result.get('location','')}", f"- Work mode: {result.get('work_mode','')}", "", "## Listed skills", *[f"- {item}" for item in result.get('skills', [])]]
    target.write_text("\n".join(frontmatter + body)+"\n", encoding="utf-8")
    print(f"Imported immutable job snapshot -> {target.relative_to(ROOT)}")


def verify_job(args) -> None:
    job = ROOT / "jobs" / "inbox" / args.job_id / "job.md"
    if not job.exists(): raise SystemExit(f"Job snapshot not found: {job}")
    source_url = next((line.split(":", 1)[1].strip() for line in job.read_text(encoding="utf-8").splitlines() if line.startswith("source_url:")), "")
    if not source_url: raise SystemExit("Job snapshot contains no source_url.")
    request = urllib.request.Request(source_url, method="GET", headers={"User-Agent": "CareerAgent/1.0 (local personal use)"})
    checked = {"job_id": args.job_id, "source_url": source_url, "checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxied_environment().get("HTTP_PROXY", ""), "https": proxied_environment().get("HTTPS_PROXY", "")}))
        with opener.open(request, timeout=20) as response:
            checked.update({"status_code": response.status, "reachable": 200 <= response.status < 400, "final_url": response.url})
    except urllib.error.HTTPError as exc:
        checked.update({"status_code": exc.code, "reachable": False, "error": str(exc)})
    except urllib.error.URLError as exc:
        checked.update({"reachable": False, "error": str(exc.reason)})
    output = job.with_name("verification.json")
    output.write_text(json.dumps(checked, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(checked, ensure_ascii=False, indent=2))


def skill_gap_report(_args) -> None:
    facts_path = ROOT / "profile" / "facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    known = {str(item.get("name", "")).lower() for item in facts.get("skills", [])}
    vocabulary = {
        "python", "go", "typescript", "javascript", "java", "c++", "sql", "git", "linux", "api", "rest", "graphql",
        "pytorch", "tensorflow", "scikit-learn", "transformer", "llama", "qwen", "lora", "qlora", "rag", "llm", "agent",
        "langchain", "langgraph", "crewai", "autogen", "openai", "anthropic", "huggingface", "bert", "embedding",
        "evaluation", "annotation", "data-cleaning", "data-pipelines", "database", "sqlite", "duckdb", "postgresql",
        "docker", "kubernetes", "aws", "azure", "gcp", "fastapi", "react", "tauri", "websocket", "n8n",
        "mlops", "langsmith", "llamaindex", "vector-databases", "ci-cd", "devsecops", "observability",
    }
    gaps: dict[str, list[str]] = {}
    for job in sorted((ROOT / "jobs" / "inbox").glob("*/job.md")):
        text = job.read_text(encoding="utf-8").lower()
        candidates = {word.rstrip(".") for word in re.findall(r"[a-z][a-z0-9+.#-]{2,}", text) if word.rstrip(".") in vocabulary}
        for word in candidates - known:
            gaps.setdefault(word, []).append(job.parent.name)
    ranked = sorted(gaps.items(), key=lambda item: (-len(set(item[1])), item[0]))[:30]
    lines = ["# Skill-gap report", "", "This is a prioritization signal from imported job snapshots, not a claim that a skill is absent from your life.", "", "| Skill signal | Imported jobs mentioning it |", "| --- | --- |"]
    lines.extend(f"| {skill} | {', '.join(sorted(set(job_ids)))} |" for skill, job_ids in ranked)
    output = ROOT / "reports" / "skill-gap-report.md"; output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(f"Created skill-gap report -> {output.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False); common.add_argument("--query", required=True); common.add_argument("--limit", type=int, default=10); common.add_argument("--remote", choices=["remote", "hybrid", "onsite"]); common.add_argument("--jobage", type=int, choices=[1,7,14,30])
    sub.add_parser("freehire", parents=[common]).set_defaults(func=discover_freehire)
    linkedin = sub.add_parser("linkedin", parents=[common]); linkedin.add_argument("--location", required=True); linkedin.set_defaults(func=discover_linkedin)
    imp = sub.add_parser("import-freehire"); imp.add_argument("snapshot"); imp.add_argument("result_id"); imp.add_argument("job_id"); imp.set_defaults(func=import_freehire)
    verify = sub.add_parser("verify"); verify.add_argument("job_id"); verify.set_defaults(func=verify_job)
    sub.add_parser("skill-gap-report").set_defaults(func=skill_gap_report)
    args = parser.parse_args(); args.func(args)


if __name__ == "__main__": main()
