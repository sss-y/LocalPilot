from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

from p0_baseline.preflight import sanitized_worker_env


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class DirtySemanticVerificationTests(unittest.TestCase):
    def test_real_p0_reports_dirty_as_the_only_acceptance_blocker(self) -> None:
        manifest = json.loads(
            (REPOSITORY_ROOT / "p0_baseline" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        active_test_ids = {
            test_id
            for check in manifest["checks"]
            for test_id in check.get("test_ids", [])
        }
        self.assertNotIn(self.id(), active_test_ids)

        completed = subprocess.run(
            [sys.executable, "-m", "p0_baseline", "--format", "json"],
            cwd=REPOSITORY_ROOT,
            env=sanitized_worker_env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        self.assertEqual("", completed.stderr)
        self.assertEqual(2, completed.returncode)
        report = json.loads(completed.stdout)
        self.assertEqual("incomplete", report["overall_status"])
        self.assertEqual(2, report["exit_code"])
        self.assertFalse(report["acceptance_eligible"])
        self.assertEqual("dirty", report["environment"]["working_tree_state"])
        self.assertTrue(report["environment"]["supported"])
        self.assertEqual([], report["environment"]["violations"])
        self.assertEqual([], report["run_diagnostics"])
        self.assertEqual(
            report["summary"]["required_total"],
            report["summary"]["passed"],
        )
        self.assertTrue(report["checks"])
        self.assertEqual(
            {"passed"},
            {check["status"] for check in report["checks"] if check["required"]},
        )


if __name__ == "__main__":
    unittest.main()
