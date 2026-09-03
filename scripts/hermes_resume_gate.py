#!/usr/bin/env python3
"""Block resume drafts whose bullets lack exact fact and evidence traceability.

The gate is deterministic and stdlib-only. It checks a draft Markdown file and
its provenance JSON against a career-profile fact store, and refuses to pass
any bullet that is unmapped, cites an unknown fact ID, omits evidence, has an
evidence path that does not resolve, or violates the canonical provenance
schema (schemas/provenance.schema.json, enforced via provenance_schema.py).

Run against an isolated fixture workspace with --root (used by the test suite
and scripts/run_demo.py); without it, it gates the real workspace.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from provenance_schema import validate_manifest  # noqa: E402

SECTIONS = ("education", "projects", "experience", "leadership", "skills", "awards", "certificates")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def known_fact_ids(profile: dict) -> set[str]:
    ids = set(profile.get("evidence_index", {}).keys())
    for section in SECTIONS:
        ids.update(item["id"] for item in profile.get(section, []) if item.get("id"))
    return ids


def resume_bullets(path: Path) -> list[str]:
    """Every '- ' line is a claim that must be provenance-mapped.

    The parser is deliberately line-based: any '- ' prefix counts as a claim,
    including section-style lists (a Skills block written with '- ' lines must
    therefore carry provenance per line). This makes the rule visible to the
    authoring side instead of silently ignoring content. tests/test_gate.py
    pins the behavior so it can never widen or narrow without a test failure.
    """
    return [line[2:].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]


def verify(job_id: str, root: Path) -> int:
    folder = root / "resumes" / "generated" / job_id
    resume = folder / "resume.md"
    provenance = folder / "provenance.json"
    report = folder / "gate_report.json"
    profile_path = root / "profile" / "master" / "profile.json"
    errors: list[str] = []

    if not profile_path.exists():
        print(
            f"Gate needs a profile fact store at {profile_path.relative_to(root)}.\n"
            "The public mirror ships no personal data: run `python scripts/run_demo.py` "
            "for a synthetic end-to-end demonstration, or populate your local profile first.",
            file=sys.stderr,
        )
        return 2

    if not resume.exists():
        errors.append(f"Missing draft: {resume}")
    if not provenance.exists():
        errors.append(f"Missing required provenance: {provenance}")

    bullets = resume_bullets(resume) if resume.exists() else []
    if not bullets:
        errors.append("Draft contains no Markdown bullets to validate.")

    profile = read_json(profile_path)
    known = known_fact_ids(profile)

    mapped: dict[str, dict] = {}
    if provenance.exists():
        try:
            data = read_json(provenance)
        except json.JSONDecodeError as exc:
            data = {}
            errors.append(f"Unreadable provenance JSON: {exc}")
        if data:
            if data.get("job_id") != job_id:
                errors.append("Provenance job_id does not match the draft folder.")
            errors.extend(validate_manifest({**data, "job_id": job_id}))
            for item in data.get("bullets", []):
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str) or not text:
                    continue
                mapped[text] = item
                for fact_id in item.get("fact_ids") or []:
                    if fact_id not in known:
                        errors.append(f"Unknown fact id for bullet: {text}")
                for entry in item.get("evidence_paths") or []:
                    candidate = Path(entry)
                    resolved = candidate if candidate.is_absolute() else root / candidate
                    if not resolved.exists():
                        errors.append(f"Evidence path not found for bullet: {item.get('bullet_id', text[:40])}")

    for bullet in bullets:
        if bullet not in mapped:
            errors.append(f"Unmapped resume bullet: {bullet}")
    for text in mapped:
        if resume.exists() and text not in bullets:
            errors.append(f"Provenance entry with no matching bullet: {text[:80]}")

    result = {
        "job_id": job_id,
        "draft": str(resume.relative_to(root)),
        "provenance": str(provenance.relative_to(root)),
        "status": "passed" if not errors else "blocked",
        "errors": errors,
        "validated_bullets": len(bullets) - sum(1 for bullet in bullets if bullet not in mapped),
    }
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Resume gate: {result['status']} -> {report.relative_to(root)}")
    for error in errors:
        print(f"- {error}")
    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="workspace root containing resumes/generated/ and profile/master/ (default: this repo)")
    args = parser.parse_args()
    return verify(args.job_id, args.root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
