#!/usr/bin/env python3
"""Local, evidence-first career agent MVP. Uses only the Python standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252; labels/statuses are non-ASCII
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
CONFIG = ROOT / "config" / "settings.local.json"


def load_json(path: Path, default=None):
    if not path.exists() and default is not None:
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def settings():
    if not CONFIG.exists():
        raise SystemExit(f"Missing local configuration: {CONFIG}")
    return load_json(CONFIG)


def parse_frontmatter(text: str):
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    frontmatter = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip().strip('"\'')
    return frontmatter, text[end + 4:].lstrip("\r\n")


def index_resumes(_args):
    source = Path(settings()["resume_source_directory"])
    if not source.exists():
        raise SystemExit(f"Resume source does not exist: {source}")
    documents = []
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".md"}:
            documents.append({
                "path": str(path), "filename": path.name, "format": path.suffix.lower()[1:],
                "sha256": sha256(path), "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
            })
    output = {"indexed_at": datetime.now(timezone.utc).isoformat(), "source_directory": str(source), "documents": documents}
    save_json(ROOT / "sources" / "master_resume" / "index.json", output)
    print(f"Indexed {len(documents)} resume files -> sources/master_resume/index.json")


def sync_profile(args):
    cfg = settings()
    vault = Path(cfg["obsidian_vault"])
    state_path = ROOT / "profile" / "sync_state.json"
    state = load_json(state_path) if state_path.exists() else {"processed_files": {}}
    candidates = []
    for allowed in cfg["allowed_obsidian_directories"]:
        root = vault / allowed
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            if frontmatter.get("resume_sync", "").lower() != "true":
                continue
            relative = str(path.relative_to(vault)).replace("\\", "/")
            file_hash = sha256(path)
            if state["processed_files"].get(relative, {}).get("hash") == file_hash:
                continue
            candidates.append({
                "source_path": str(path), "vault_relative_path": relative, "sha256": file_hash,
                "type": frontmatter.get("type", "unknown"), "date": frontmatter.get("date"),
                "title": next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), path.stem),
                "content": body.strip(), "confidence": "needs_verification"
            })
    if args.approve:
        proposal = ROOT / "profile" / "proposals" / f"{args.approve}.json"
        if not proposal.exists():
            raise SystemExit(f"Proposal not found: {proposal}")
        payload = load_json(proposal)
        facts_path = ROOT / "profile" / "facts.json"
        facts = load_json(facts_path)
        facts.setdefault("projects", []).extend(payload["candidates"])
        save_json(facts_path, facts)
        for item in payload["candidates"]:
            state["processed_files"][item["vault_relative_path"]] = {"hash": item["sha256"], "status": "approved", "approved_at": datetime.now(timezone.utc).isoformat()}
        save_json(state_path, state)
        print(f"Approved {len(payload['candidates'])} proposed facts into profile/facts.json")
        return
    proposal_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {"proposal_id": proposal_id, "created_at": datetime.now(timezone.utc).isoformat(), "candidates": candidates}
    save_json(ROOT / "profile" / "proposals" / f"{proposal_id}.json", payload)
    print(f"Found {len(candidates)} changed opt-in notes. Review then run: sync-profile --approve {proposal_id}")


def import_job(args):
    source = Path(args.job_file)
    if not source.exists():
        raise SystemExit(f"Job file not found: {source}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.job_id):
        raise SystemExit("job_id must be a slug: letters, digits, dash, underscore.")
    resolved_source = source.resolve()
    if ROOT not in resolved_source.parents and resolved_source.parent != ROOT:
        if not getattr(args, "allow_external", False):
            raise SystemExit(
                f"Refusing to import {resolved_source}: outside the workspace. "
                "Stage the file under jobs/_incoming/ first, or pass --allow-external "
                "to import an explicit absolute path.")
        source = resolved_source
    target = ROOT / "jobs" / "inbox" / args.job_id / "job.md"
    if target.exists():
        raise SystemExit(f"Refusing to overwrite immutable job snapshot: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    print(f"Imported job snapshot -> {target.relative_to(ROOT)}")


def keywords(text: str):
    return {item.lower() for item in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", text)}


def evaluate_job(args):
    job_path = ROOT / "jobs" / "inbox" / args.job_id / "job.md"
    if not job_path.exists():
        raise SystemExit(f"Job not found: {job_path}")
    frontmatter, body = parse_frontmatter(job_path.read_text(encoding="utf-8"))
    rules = load_json(ROOT / "config" / "evaluation_rules.json")
    facts_path = ROOT / "profile" / "facts.json"
    if not facts_path.exists():
        facts_path = ROOT / "profile" / "example_facts.json"
    facts = load_json(facts_path, {"skills": [], "projects": []})
    text = (json.dumps(frontmatter, ensure_ascii=False) + "\n" + body).lower()
    job_words = keywords(text)
    skills = {item["name"].lower() for item in facts.get("skills", [])}
    matched = sorted(skill for skill in skills if skill in job_words)
    location = str(frontmatter.get("remote_scope", "") or "").lower()
    rules_loc = rules["location_rules"]
    rejected = [term.lower() for term in rules_loc["rejected"]]
    accepted = [term.lower() for term in rules_loc["accepted"]]
    conditional = [term.lower() for term in rules_loc["conditional"]]
    # Rejected work-authorization / on-site-only conditions kill it outright.
    if any(term in location or term in text for term in rejected):
        location_score, location_status = 0, "不通过"
    # Any remote scope (global, WFH, China remote, etc.) qualifies:
    # The owner accepts remote work from anywhere.
    elif any(term in location or term in text for term in accepted) or "remote" in location:
        location_score, location_status = 30, "通过"
    # Region-conditional remote (e.g. Remote Asia, HK) that still permits China.
    elif any(term in location or term in text for term in conditional) or "asia" in location or "hong kong" in location or "taipei" in location:
        location_score, location_status = 18, "不确定：需确认中国大陆远程/合同可行性"
    else:
        location_score, location_status = 0, "不通过或信息不足"
    education_score = 20 if "undergraduate" in str(frontmatter.get("education", "")).lower() else 10
    technical_score = min(20, len(matched) * 4)
    evidence_score = min(20, len(matched) * 3 + (8 if facts.get("projects") else 0))
    availability_score = 3 if "five days" in text or "每周五天" in text else 8
    total = location_score + education_score + technical_score + evidence_score + availability_score
    label = next(label for threshold, label in rules["labels"] if total >= threshold)
    evaluation = {
        "job_id": args.job_id, "evaluated_at": datetime.now(timezone.utc).isoformat(), "source": frontmatter.get("source", "local snapshot"),
        "live_status": frontmatter.get("live_status", "not_verified"), "total": total, "label": label,
        "scores": {"location": location_score, "education": education_score, "technical": technical_score, "evidence": evidence_score, "availability": availability_score},
        "hard_conditions": location_status, "matched_skills": matched,
        "risks": ["岗位快照未做官方实时验证", location_status] if "不确定" in location_status else ["岗位快照未做官方实时验证"],
        "recommendation": "人工确认远程资格与岗位仍开放后再投递。" if label != "不建议申请" else "不建议投入申请时间。"
    }
    save_json(job_path.with_name("evaluation.json"), evaluation)
    print(json.dumps(evaluation, ensure_ascii=False, indent=2))


def rank_jobs(_args):
    evaluations = []
    for path in (ROOT / "jobs" / "inbox").glob("*/evaluation.json"):
        evaluations.append(load_json(path))
    evaluations.sort(key=lambda item: item["total"], reverse=True)
    lines = ["# Job ranking", "", "| Job | Score | Recommendation |", "| --- | ---: | --- |"]
    lines.extend(f"| {item['job_id']} | {item['total']} | {item['label']} |" for item in evaluations)
    (ROOT / "jobs" / "RANKING.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Ranked {len(evaluations)} jobs -> jobs/RANKING.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("index-resumes").set_defaults(func=index_resumes)
    sync = commands.add_parser("sync-profile"); sync.add_argument("--approve"); sync.set_defaults(func=sync_profile)
    importer = commands.add_parser("import-job"); importer.add_argument("job_id"); importer.add_argument("job_file")
    importer.add_argument("--allow-external", action="store_true", help="import a file from outside the workspace root")
    importer.set_defaults(func=import_job)
    evaluate = commands.add_parser("evaluate-job"); evaluate.add_argument("job_id"); evaluate.set_defaults(func=evaluate_job)
    commands.add_parser("rank-jobs").set_defaults(func=rank_jobs)
    args = parser.parse_args(); args.func(args)


if __name__ == "__main__":
    main()
