"""Block Hermes resume drafts that lack exact fact and evidence traceability."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def known_fact_ids(profile: dict) -> set[str]:
    ids = set(profile.get("evidence_index", {}).keys())
    for section in ("education", "projects", "experience", "leadership", "skills", "awards", "certificates"):
        ids.update(item["id"] for item in profile.get(section, []) if item.get("id"))
    return ids


def resume_bullets(path: Path) -> list[str]:
    return [line[2:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def verify(job_id: str) -> int:
    folder = ROOT / "resumes" / "generated" / job_id
    resume = folder / "hermes_resume_draft.md"
    provenance = folder / "hermes_provenance.json"
    report = folder / "hermes_validation.json"
    errors: list[str] = []

    if not resume.exists():
        errors.append(f"Missing Hermes draft: {resume}")
    if not provenance.exists():
        errors.append(f"Missing required provenance: {provenance}")

    bullets = resume_bullets(resume) if resume.exists() else []
    if not bullets:
        errors.append("Draft contains no Markdown bullets to validate.")

    mapped: dict[str, dict] = {}
    profile_path = ROOT / "profile" / "master" / "profile.json"
    profile = read_json(profile_path)
    known = known_fact_ids(profile)
    if provenance.exists():
        try:
            data = read_json(provenance)
            if data.get("job_id") != job_id:
                errors.append("Provenance job_id does not match the draft folder.")
            for item in data.get("bullets", []):
                text = item.get("text")
                if not text:
                    errors.append("A provenance bullet is missing text.")
                    continue
                mapped[text] = item
                fact_ids = item.get("fact_ids")
                paths = item.get("evidence_paths")
                if not isinstance(fact_ids, list) or not fact_ids:
                    errors.append(f"No fact_ids for bullet: {text}")
                elif any(fact_id not in known for fact_id in fact_ids):
                    errors.append(f"Unknown fact id for bullet: {text}")
                if not isinstance(paths, list) or not paths:
                    errors.append(f"No evidence_paths for bullet: {text}")
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"Unreadable provenance JSON: {exc}")

    for bullet in bullets:
        if bullet not in mapped:
            errors.append(f"Unmapped resume bullet: {bullet}")

    result = {
        "job_id": job_id,
        "draft": str(resume),
        "provenance": str(provenance),
        "status": "passed" if not errors else "blocked",
        "errors": errors,
        "validated_bullets": len(bullets) - sum(1 for bullet in bullets if bullet not in mapped),
    }
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Hermes resume gate: {result['status']} -> {report.relative_to(ROOT)}")
    for error in errors:
        print(f"- {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    args = parser.parse_args()
    raise SystemExit(verify(args.job_id))
