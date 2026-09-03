"""Pinned smoke tests for the stdlib-only core pipeline.

These run with zero third-party dependencies (CI installs nothing) and fail
if a clean clone can no longer evaluate a job, import a snapshot, or reject a
path-traversal job_id. They are deliberately shallow: they prove the shipped
mirror runs, not that private-lane behavior (docx export, connectors) works.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=REPO)


class CliSmoke(unittest.TestCase):
    def test_evaluate_fixture_snapshot(self):
        stage = REPO / "jobs" / "inbox" / "smoke-demo"
        if stage.exists():
            self.fail("test left stale state")
        try:
            stage.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copytree(REPO / "jobs" / "example_synthetic" / "demo-ai-intern", stage)
            proc = run([sys.executable, str(SCRIPTS / "career_agent.py"), "evaluate-job", "smoke-demo"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            evaluation = json.loads((stage / "evaluation.json").read_text(encoding="utf-8"))
            self.assertIn(evaluation["label"], ("高度匹配", "可尝试", "低优先级", "不建议申请"))
            self.assertGreater(evaluation["total"], 0)
        finally:
            import shutil
            shutil.rmtree(stage, ignore_errors=True)

    def test_import_job_rejects_path_traversal(self):
        proc = run([sys.executable, str(SCRIPTS / "career_agent.py"),
                    "import-job", "../evil", "README.md"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("slug", proc.stdout + proc.stderr)

    def test_all_core_modules_import_without_extras(self):
        core = ["career_agent", "company_ats", "job_discovery", "rag_evidence",
                "universal_job_import", "windows_proxy", "hermes_resume_gate",
                "provenance_schema", "application_manager", "generate_base_resumes",
                "master_profile"]
        code = ("import sys; sys.path.insert(0, r'%s');"
                "import importlib; [importlib.import_module(m) for m in %r]; print('ok')"
                % (SCRIPTS, core))
        proc = run([sys.executable, "-c", code])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_demo_runs_and_is_honest(self):
        proc = run([sys.executable, str(SCRIPTS / "run_demo.py")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("gate status: passed (expected passed)", out)
        self.assertIn("gate status: blocked (expected blocked)", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
