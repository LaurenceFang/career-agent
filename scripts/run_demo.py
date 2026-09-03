#!/usr/bin/env python3
"""Synthetic end-to-end demonstration of the provenance gate.

Builds a throwaway workspace from fixtures/demo/, then runs the real gate
three times and shows, from actual exit codes and reports:

  1. a valid draft          -> PASSED
  2. a bullet with no fact_ids / unknown fact id / missing evidence -> BLOCKED
  3. the same draft repaired -> PASSED again

No personal data is read or written. Run: python scripts/run_demo.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hermes_resume_gate import verify  # noqa: E402

FIXTURES = ROOT / "fixtures" / "demo"


def build_workspace(tmp: Path) -> Path:
    """Lay fixtures out in the exact directory shape the gate expects."""
    (tmp / "profile" / "master").mkdir(parents=True)
    shutil.copyfile(FIXTURES / "profile" / "master" / "profile.json",
                    tmp / "profile" / "master" / "profile.json")
    evidence = tmp / "fixtures" / "demo" / "evidence"
    evidence.mkdir(parents=True)
    for item in (FIXTURES / "evidence").iterdir():
        shutil.copyfile(item, evidence / item.name)
    draft_dir = tmp / "resumes" / "generated" / "demo-gate"
    draft_dir.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "resume_good.md", draft_dir / "resume.md")
    return draft_dir


def write_provenance(draft_dir: Path, mutations: dict | None = None) -> Path:
    data = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
    if mutations:
        for index, changes in mutations.items():
            for key, value in changes.items():
                if value is None:
                    data["bullets"][index].pop(key, None)
                else:
                    data["bullets"][index][key] = value
    path = draft_dir / "provenance.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_step(title: str, root: Path, provenance: Path, expect: str) -> int:
    print(f"\n=== {title}")
    print(f"--- provenance.json under test: {provenance.relative_to(root)}")
    print(provenance.read_text(encoding="utf-8").rstrip())
    code = verify("demo-gate", root)
    report = json.loads((root / "resumes" / "generated" / "demo-gate" / "gate_report.json")
                        .read_text(encoding="utf-8"))
    status = report["status"]
    verdict = "ok" if status == expect else "MISMATCH"
    print(f"--- gate status: {status} (expected {expect}) [{verdict}] exit={code}")
    if verdict == "MISMATCH":
        sys.exit(1)
    return code


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="career-agent-demo-") as raw:
        root = Path(raw)
        draft_dir = build_workspace(root)

        prov = write_provenance(draft_dir)
        run_step("STEP 1 — valid synthetic draft", root, prov, "passed")

        prov = write_provenance(draft_dir, {
            0: {"fact_ids": None},                      # missing required field
            1: {"fact_ids": ["fact_that_does_not_exist"]},  # unknown fact id
        })
        (root / "fixtures" / "demo" / "evidence" / "example_agent.md").unlink()
        run_step("STEP 2 — broken provenance (missing fact_ids, unknown fact id, "
                 "evidence file deleted from disk)", root, prov, "blocked")

        shutil.copyfile(FIXTURES / "evidence" / "example_agent.md",
                        root / "fixtures" / "demo" / "evidence" / "example_agent.md")
        prov = write_provenance(draft_dir)
        run_step("STEP 3 — repaired: same gate, same code, honest inputs", root, prov, "passed")

    print("\nDemo complete: the checker demonstrably fails on bad input and only "
          "then counts as real when it passes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
