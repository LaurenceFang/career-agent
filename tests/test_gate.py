#!/usr/bin/env python3
"""Negative and positive tests for the deterministic provenance gate.

Every test builds an isolated fixture workspace in a temp directory; none of
them touch the real profile or resumes. The point of this suite is not a
green checkmark: each negative case exists because that exact class of bad
input once produced a wrong-looking-correct resume artifact.

Run: python -m unittest discover -s tests -v   (stdlib only)
     pytest tests                              (works too, optional)
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from hermes_resume_gate import verify  # noqa: E402
from provenance_schema import validate_manifest  # noqa: E402

FIXTURES = REPO / "fixtures" / "demo"

GOOD_RESUME = """# Demo Resume

## Experience

- Built a local agent workflow with tool wiring and written definitions of done.
- Added human review gates so consequential actions need explicit confirmation.

## Skills
Python, Git
"""

BULLET_ONE = "Built a local agent workflow with tool wiring and written definitions of done."
BULLET_TWO = "Added human review gates so consequential actions need explicit confirmation."


def build_workspace(tmp: Path, *, resume: str = GOOD_RESUME,
                    provenance: dict | None = "default") -> Path:
    """Materialize the directory shape the gate expects inside tmp/."""
    (tmp / "profile" / "master").mkdir(parents=True)
    shutil.copyfile(FIXTURES / "profile" / "master" / "profile.json",
                    tmp / "profile" / "master" / "profile.json")
    evidence = tmp / "fixtures" / "demo" / "evidence"
    evidence.mkdir(parents=True)
    for item in (FIXTURES / "evidence").iterdir():
        shutil.copyfile(item, evidence / item.name)
    draft = tmp / "resumes" / "generated" / "demo-gate"
    draft.mkdir(parents=True)
    (draft / "resume.md").write_text(resume, encoding="utf-8")
    if provenance == "default":
        provenance = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
    if provenance is not None:
        (draft / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False), encoding="utf-8")
    return draft


def run_gate(tmp: Path) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = verify("demo-gate", tmp)
    report_path = tmp / "resumes" / "generated" / "demo-gate" / "gate_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    return code, report


class GatePositive(unittest.TestCase):
    def test_valid_synthetic_draft_passes(self):
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw))
            code, report = run_gate(Path(raw))
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["validated_bullets"], 2)


class GateNegative(unittest.TestCase):
    """Each case: one precise defect, asserted to BLOCK with a matching reason."""

    def _blocked(self, tmp, expect_fragment):
        code, report = run_gate(tmp)
        self.assertEqual(code, 1, "gate must exit nonzero on bad input")
        self.assertEqual(report["status"], "blocked")
        joined = "\n".join(report["errors"])
        self.assertIn(expect_fragment, joined)

    def test_missing_provenance_file_blocks(self):
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=None)
            self._blocked(Path(raw), "Missing required provenance")

    def test_missing_fact_ids_blocks(self):
        prov = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
        del prov["bullets"][0]["fact_ids"]
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=prov)
            self._blocked(Path(raw), "fact_ids missing")

    def test_empty_fact_ids_blocks(self):
        prov = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
        prov["bullets"][0]["fact_ids"] = []
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=prov)
            self._blocked(Path(raw), "fact_ids is empty")

    def test_unknown_fact_id_blocks(self):
        prov = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
        prov["bullets"][0]["fact_ids"] = ["fact_nobody_approved"]
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=prov)
            self._blocked(Path(raw), "Unknown fact id")

    def test_missing_evidence_paths_blocks(self):
        prov = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
        del prov["bullets"][1]["evidence_paths"]
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=prov)
            self._blocked(Path(raw), "evidence_paths missing")

    def test_evidence_path_not_on_disk_blocks(self):
        prov = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
        prov["bullets"][0]["evidence_paths"] = ["fixtures/demo/evidence/deleted_note.md"]
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=prov)
            self._blocked(Path(raw), "Evidence path not found")

    def test_unmapped_bullet_blocks(self):
        resume = GOOD_RESUME + "\n- Invented achievement with no provenance at all.\n"
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), resume=resume)
            self._blocked(Path(raw), "Unmapped resume bullet")

    def test_wrong_job_id_blocks(self):
        prov = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
        prov["job_id"] = "some-other-role"
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=prov)
            self._blocked(Path(raw), "job_id does not match")

    def test_orphan_provenance_entry_blocks(self):
        """A provenance entry that matches nothing in the draft is also a lie."""
        prov = json.loads((FIXTURES / "provenance_good.json").read_text(encoding="utf-8"))
        prov["bullets"].append({
            "bullet_id": "ghost", "text": "Bullet that does not exist in the draft.",
            "fact_ids": ["project_example"],
            "evidence_paths": ["fixtures/demo/evidence/example_agent.md"]})
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), provenance=prov)
            self._blocked(Path(raw), "no matching bullet")

    def test_markdown_bold_in_bullet_breaks_exact_match(self):
        """Pinned authoring rule: gate compares raw '- ' text, so **bold**
        inside a bullet must never be used; this test documents why."""
        resume = GOOD_RESUME.replace(BULLET_ONE[:12], BULLET_ONE[:12] + "**x**")
        with tempfile.TemporaryDirectory() as raw:
            build_workspace(Path(raw), resume=resume)
            self._blocked(Path(raw), "Unmapped resume bullet")

    def test_absent_profile_store_exits_two_with_guidance(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            build_workspace(tmp)
            (tmp / "profile" / "master" / "profile.json").unlink()
            code, _ = run_gate(tmp)
            self.assertEqual(code, 2)


class SchemaContract(unittest.TestCase):
    def test_schema_file_agrees_with_python_validator(self):
        schema = json.loads((REPO / "schemas" / "provenance.schema.json").read_text(encoding="utf-8"))
        doc_required = set(schema["definitions"]["bullet"]["required"])
        self.assertEqual(doc_required, set({"bullet_id", "text", "fact_ids", "evidence_paths"}))
        # validator enforces exactly these four
        errors = validate_manifest({"job_id": "x", "bullets": [{"bullet_id": "b", "text": "t"}]})
        joined = "\n".join(errors)
        for field in ("fact_ids", "evidence_paths"):
            self.assertIn(field, joined)

    def test_non_string_fact_id_entries_rejected(self):
        errors = validate_manifest({"job_id": "x", "bullets": [{
            "bullet_id": "b", "text": "t", "fact_ids": [123],
            "evidence_paths": ["p"]}]})
        self.assertTrue(any("non-empty strings" in e for e in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
